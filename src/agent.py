"""
Autonomous SQL Optimization Agent

Production-ready ReAct agent for iterative query optimization.
Based on Anthropic 2025 best practices for building effective agents.

Architecture:
    1. Analyze: Get EXPLAIN plan and identify bottlenecks
    2. Plan: Use Claude with extended thinking to decide next action
    3. Act: Execute optimization (CREATE INDEX, REWRITE, ANALYZE)
    4. Observe: Validate improvement
    5. Repeat: Until optimized or max iterations reached
"""

import json
import re
from dataclasses import dataclass, field
from typing import Any

import psycopg2

from .actions import Action, ActionType, parse_action_from_llm_response
from .analyzer import ExplainAnalyzer
from .display import display
from .error_classifier import ErrorClassifier
from .extensions.detector import ExtensionDetector
from .llm import BaseLLMClient, create_llm_client
from .schema_fetcher import SchemaFetcher
from .semanticizer import SemanticTranslator
from .tools.hypopg import HypoPGTool
from .validators.base import ValidationResult
from .validators.differential import NoRECValidator
from .validators.metamorphic import TLPValidator


@dataclass
class FailedAction:
    """
    Record of a failed optimization action.

    Attributes:
        action: The action that failed
        error: Error message from the failure
        iteration: Iteration number when failure occurred
        timestamp: When the failure occurred (for context pruning)
    """
    action: Action
    error: str
    iteration: int
    timestamp: float = field(default_factory=lambda: __import__('time').time())


@dataclass
class OptimizationResult:
    """
    Result of a query optimization attempt.

    Attributes:
        success: Whether optimization met the performance constraints
        final_query: The optimized SQL query
        actions: List of actions taken during optimization
        metrics: Performance metrics (cost, execution time, etc.)
        iterations: Number of optimization iterations performed
        reason: Explanation of the result
    """
    success: bool
    final_query: str
    actions: list[Action] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    iterations: int = 0
    reason: str = ""


class SQLOptimizationAgent:
    """
    Autonomous SQL query optimization agent using ReAct pattern.

    Features:
    - Extended thinking for complex reasoning (Claude Sonnet 4.5+)
    - Statement timeout protection against runaway queries
    - Two-phase EXPLAIN strategy (estimate first, ANALYZE if safe)
    - Configurable performance constraints and iteration limits
    - Transaction-wrapped EXPLAIN ANALYZE for safety

    Example:
        ```python
        agent = SQLOptimizationAgent()
        result = await agent.optimize_query(
            sql="SELECT * FROM users WHERE email='test@example.com'",
            db_connection="postgresql://localhost:5432/mydb",
            max_cost=1000.0,
            max_time_ms=5000
        )
        ```
    """

    def __init__(
        self,
        max_iterations: int = 10,
        timeout_seconds: int = 120,
        statement_timeout_ms: int = 60000,
        use_thinking: bool = True,
        thinking_budget: int = 4000,
        provider: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
        llm_client: BaseLLMClient | None = None,
    ):
        """
        Initialize the SQL optimization agent.

        Args:
            max_iterations: Maximum optimization iterations (default: 10)
            timeout_seconds: Overall timeout for optimization task (default: 120)
            statement_timeout_ms: PostgreSQL statement timeout in ms (default: 60000)
            use_thinking: Enable extended thinking (Claude) or CoT (others) (default: True)
            thinking_budget: Token budget for thinking (default: 4000)
            provider: LLM provider ("anthropic", "groq", "openrouter") - auto-detected if not set
            model: Model name (uses provider default if not specified)
            api_key: API key (or uses environment variable for provider)
            llm_client: Pre-configured LLM client (overrides provider/model/api_key)
        """
        self.max_iterations = max_iterations
        self.timeout_seconds = timeout_seconds
        self.statement_timeout_ms = statement_timeout_ms
        self.use_thinking = use_thinking
        self.thinking_budget = max(thinking_budget, 1024)

        # Initialize components
        self.analyzer = ExplainAnalyzer()
        self.error_classifier = ErrorClassifier()

        # Initialize correctness validators
        self.tlp_validator = TLPValidator()
        self.norec_validator = NoRECValidator()

        # Initialize LLM client (use provided or create new)
        if llm_client:
            self.llm_client = llm_client
        else:
            self.llm_client = create_llm_client(
                provider=provider,
                api_key=api_key,
                model=model,
                max_tokens=8000,
            )

        # Initialize semantic translator with same LLM client
        self.translator = SemanticTranslator(llm_client=self.llm_client)

        # Track executed DDLs to avoid re-applying same optimization
        self.executed_ddls: set = set()

        # Track failed DDLs to avoid immediate retry
        self.failed_ddls: set = set()

        # Track created index names to avoid duplicates
        self.created_indexes: set = set()

        # Efficiency controls
        self.max_actions_without_improvement = 2  # Stop after N actions with no improvement
        self.min_improvement_threshold = 0.05     # 5% minimum improvement required

        # Lazy-init schema fetcher (only created when needed)
        self.schema_fetcher: SchemaFetcher | None = None

        # Extension detection and tools (lazy-init per connection)
        self.extension_detector = ExtensionDetector()
        self.hypopg_tool: HypoPGTool | None = None
        self.can_use_hypopg: bool = False

    async def optimize_query(
        self,
        sql: str,
        db_connection: str,
        max_cost: float = 500.0,
        max_time_ms: int = 50,
        analyze_cost_threshold: float = 5_000_000.0,
        schema_info: str | None = None,
        auto_fetch_schema: bool = True,
        validate_correctness: bool = True,
    ) -> dict[str, Any]:
        """
        Autonomously optimize a SQL query with optional correctness validation.

        Uses a two-phase approach:
        1. CORRECTNESS VALIDATION (if enabled):
           - Validates query correctness using metamorphic testing (TLP + NoREC)
           - Attempts to fix any detected correctness issues
           - Proceeds to optimization only if query is correct

        2. PERFORMANCE OPTIMIZATION:
           - Analyze current query execution plan
           - Plan next optimization action using Claude
           - Act by executing the planned optimization
           - Observe the results and determine if constraints are met
           - Repeat until optimized or max iterations reached

        Args:
            sql: SQL query to optimize
            db_connection: PostgreSQL connection string
            max_cost: Maximum acceptable query cost (default: 10000.0)
            max_time_ms: Maximum acceptable execution time in ms (default: 30000)
            analyze_cost_threshold: Cost threshold for EXPLAIN ANALYZE (default: 5M)
            schema_info: Optional database schema information (manual override)
            auto_fetch_schema: Automatically fetch schema from database (default: True)
            validate_correctness: Validate query correctness before optimization (default: True)

        Returns:
            Dictionary with optimization results:
            {
                "success": bool,
                "final_query": str,
                "actions": List[Action],
                "metrics": dict,
                "reason": str,
                "validation": Optional[ValidationResult]  # If validate_correctness=True
            }
        """
        current_query = sql.strip()
        actions_taken: list[Action] = []
        failed_actions: list[FailedAction] = []
        iteration = 0

        constraints = {
            "max_cost": max_cost,
            "max_time_ms": max_time_ms,
            "analyze_cost_threshold": analyze_cost_threshold,
        }

        # Auto-fetch schema if not provided
        if auto_fetch_schema and schema_info is None:
            try:
                if self.schema_fetcher is None:
                    self.schema_fetcher = SchemaFetcher(db_connection)
                schema_info = self.schema_fetcher.fetch_schema_for_query(sql)
                # Schema fetching details hidden for clean UI
            except Exception:
                # Schema fetching is optional - continue without it
                schema_info = None

        # Detect available extensions (hypopg for virtual index testing)
        extensions = self.extension_detector.detect(db_connection)
        self.can_use_hypopg = self.extension_detector.has_hypopg(extensions)
        if self.can_use_hypopg:
            self.hypopg_tool = HypoPGTool(db_connection)
            display.info("hypopg extension detected - virtual index testing enabled")

        # PHASE 1: CORRECTNESS VALIDATION (if enabled)
        # Validate query correctness BEFORE optimizing performance
        # Rationale: A fast query returning wrong data is worse than a slow correct query
        validation_result = None
        if validate_correctness:
            with display.spinner("Validating query correctness..."):
                validation_result = await self._validate_correctness(
                    current_query,
                    db_connection
                )

            if not validation_result.passed:
                # Correctness validation failed - report issues
                display.error("Correctness validation failed")
                for issue in validation_result.issues:
                    display.warning(f"{issue.issue_type}: {issue.description}")

                # Return early - don't optimize incorrect queries
                return {
                    "success": False,
                    "final_query": current_query,
                    "actions": actions_taken,
                    "metrics": {},
                    "reason": "Correctness validation failed - query may return incorrect results",
                    "validation": validation_result,
                }
            else:
                # Validation passed
                display.success(f"Correctness validated ({validation_result.method})")

        # PHASE 2: PERFORMANCE OPTIMIZATION
        # ReAct Loop: Reason → Act → Observe
        # max_iterations is a safety mechanism only - agent decides when to stop
        iteration = 0
        initial_cost = None
        last_cost = None
        last_action_type = None
        # Track failures per action type - only stop when same type fails twice
        failures_by_type: dict[str, int] = {}

        while iteration < self.max_iterations:
            iteration += 1

            # STEP 1: ANALYZE - Get execution plan and identify bottlenecks
            with display.spinner("Analyzing query performance..."):
                analysis = await self._analyze_query(
                    current_query, db_connection, constraints, schema_info
                )

            # Track cost for improvement measurement
            current_cost = analysis["analysis"]["total_cost"]
            if initial_cost is None:
                initial_cost = current_cost
                last_cost = current_cost
            else:
                # Check if we made meaningful improvement from last action
                if last_cost > 0 and last_action_type:
                    improvement = (last_cost - current_cost) / last_cost
                    if improvement < self.min_improvement_threshold:
                        # Track failure for the action type that was just tried
                        failures_by_type[last_action_type] = failures_by_type.get(last_action_type, 0) + 1

                        # Check if this action type has failed too many times
                        if failures_by_type[last_action_type] >= self.max_actions_without_improvement:
                            # Check if ALL action types have been exhausted
                            exhausted_types = [t for t, count in failures_by_type.items()
                                             if count >= self.max_actions_without_improvement]
                            if len(exhausted_types) >= 2:  # At least 2 action types exhausted
                                display.info(f"Stopping: exhausted {exhausted_types} without improvement")
                                return {
                                    "success": analysis["feedback"]["status"] == "pass",
                                    "final_query": current_query,
                                    "actions": actions_taken,
                                    "metrics": {
                                        "final_cost": current_cost,
                                        "initial_cost": initial_cost,
                                        "improvement_pct": ((initial_cost - current_cost) / initial_cost * 100) if initial_cost > 0 else 0,
                                    },
                                    "reason": f"Optimization plateaued after {len(actions_taken)} actions. Best cost: {current_cost:.0f}"
                                }
                    else:
                        # Reset failure counter for this action type on success
                        failures_by_type[last_action_type] = 0
                last_cost = current_cost

            # STEP 2: OBSERVE - Record current status but always try to optimize further
            # Only stop early if we've already taken actions AND constraints are met
            if analysis["feedback"]["status"] == "pass" and len(actions_taken) > 0:
                display.success("Optimization complete")
                return {
                    "success": True,
                    "final_query": current_query,
                    "actions": actions_taken,
                    "metrics": {
                        "final_cost": analysis["analysis"]["total_cost"],
                        "final_time_ms": analysis["analysis"].get("execution_time_ms", 0),
                        "initial_cost": actions_taken[0].metrics.get("cost_before", 0) if actions_taken else analysis["analysis"]["total_cost"],
                    },
                    "reason": analysis["feedback"]["reason"]
                }

            # STEP 3: PLAN - Decide next action (always try to find optimizations)
            action = await self._plan_action(
                current_query, analysis, actions_taken, failed_actions, iteration
            )

            if action.type == ActionType.DONE:
                # Agent decided optimization is complete
                # Check if constraints are actually met
                final_cost = analysis["analysis"]["total_cost"]
                final_time = analysis["analysis"].get("execution_time_ms", 0)
                meets_constraints = (
                    final_cost <= constraints["max_cost"] and
                    (final_time == 0 or final_time <= constraints["max_time_ms"])
                )

                if meets_constraints:
                    display.success("Optimization complete")
                else:
                    display.info("Optimization complete")

                return {
                    "success": meets_constraints,
                    "final_query": current_query,
                    "actions": actions_taken,
                    "metrics": {
                        "final_cost": final_cost,
                        "final_time_ms": final_time,
                        "initial_cost": actions_taken[0].metrics.get("cost_before", 0) if actions_taken else final_cost,
                    },
                    "reason": action.reasoning
                }

            if action.type == ActionType.FAILED:
                # Agent determined query cannot be optimized further
                display.warning("Query cannot be optimized further")
                return {
                    "success": False,
                    "final_query": current_query,
                    "actions": actions_taken,
                    "metrics": {},
                    "reason": action.reasoning
                }

            # Record metrics before action
            action.metrics = {
                "cost_before": analysis["analysis"]["total_cost"],
                "iteration": iteration,
            }

            # STEP 4: ACT - Execute the planned optimization
            execution_result = await self._execute_action(action, db_connection, current_query)

            if not execution_result["success"]:
                error_msg = execution_result['error']
                display.error(f"Action failed: {error_msg}")

                # Record the failed action for learning
                failed_action = FailedAction(
                    action=action,
                    error=error_msg,
                    iteration=iteration
                )
                failed_actions.append(failed_action)

                # Track failed DDL to prevent immediate retry
                if action.ddl:
                    self.failed_ddls.add(action.ddl)

                # Continue to next iteration with failure context
                continue

            # Update current query if it was rewritten
            if action.type == ActionType.REWRITE_QUERY and action.new_query:
                current_query = action.new_query
                display.tool_result(action.type.value, "Query rewritten")
            elif action.type == ActionType.TEST_INDEX:
                # TEST_INDEX may create real index or skip it
                if execution_result.get("virtual_test"):
                    display.tool_result(action.type.value, "Index skipped (not beneficial)")
                else:
                    display.tool_result(action.type.value, "Index created (verified beneficial)")
                    # Track created index name to avoid duplicates
                    if action.ddl:
                        match = re.search(r'CREATE\s+INDEX\s+(?:CONCURRENTLY\s+)?(?:IF\s+NOT\s+EXISTS\s+)?(\w+)', action.ddl, re.IGNORECASE)
                        if match:
                            self.created_indexes.add(match.group(1).lower())
            elif action.type == ActionType.CREATE_INDEX:
                display.tool_result(action.type.value, "Index created")
                # Track created index name to avoid duplicates
                if action.ddl:
                    match = re.search(r'CREATE\s+INDEX\s+(?:CONCURRENTLY\s+)?(?:IF\s+NOT\s+EXISTS\s+)?(\w+)', action.ddl, re.IGNORECASE)
                    if match:
                        self.created_indexes.add(match.group(1).lower())
            elif action.type == ActionType.RUN_ANALYZE:
                display.tool_result(action.type.value, "Statistics updated")

            # Track action type for per-type failure counting
            last_action_type = action.type.value
            actions_taken.append(action)

        # Safety limit reached (should rarely happen with autonomous agent)
        display.warning(f"Reached iteration limit ({self.max_iterations})")
        final_analysis = await self._analyze_query(
            current_query, db_connection, constraints, schema_info
        )

        return {
            "success": False,
            "final_query": current_query,
            "actions": actions_taken,
            "metrics": {
                "final_cost": final_analysis["analysis"]["total_cost"],
            },
            "iterations": self.max_iterations,
            "reason": f"Reached max iterations ({self.max_iterations}). {final_analysis['feedback']['reason']}"
        }

    async def _validate_correctness(
        self,
        sql: str,
        db_connection: str,
    ) -> ValidationResult:
        """
        Validate query correctness using metamorphic testing.

        Runs both TLP (Ternary Logic Partitioning) and NoREC validators
        in parallel for comprehensive correctness validation.

        Args:
            sql: SQL query to validate
            db_connection: PostgreSQL connection string

        Returns:
            Combined ValidationResult from TLP and NoREC validators
        """
        import asyncio

        # Run TLP and NoREC validators in parallel for efficiency
        try:
            tlp_result, norec_result = await asyncio.gather(
                self.tlp_validator.validate(sql, db_connection),
                self.norec_validator.validate(sql, db_connection),
                return_exceptions=True
            )
        except Exception as e:
            # If validation fails completely, return error result
            from .validators.base import ValidationIssue
            return ValidationResult(
                passed=False,
                confidence=0.0,
                method="TLP+NoREC",
                issues=[ValidationIssue(
                    issue_type="VALIDATION_ERROR",
                    description=f"Validation failed: {str(e)}",
                    severity="ERROR",
                    suggested_fix="Check database connection and query syntax"
                )],
                execution_time_ms=0,
                queries_executed=0
            )

        # Handle exceptions from individual validators
        if isinstance(tlp_result, Exception):
            tlp_result = ValidationResult(
                passed=True, confidence=0.0, method="TLP",
                issues=[], execution_time_ms=0, queries_executed=0
            )

        if isinstance(norec_result, Exception):
            norec_result = ValidationResult(
                passed=True, confidence=0.0, method="NoREC",
                issues=[], execution_time_ms=0, queries_executed=0
            )

        # Combine results from both validators
        all_issues = tlp_result.issues + norec_result.issues

        if all_issues:
            # At least one validator found issues
            return ValidationResult(
                passed=False,
                confidence=min(tlp_result.confidence, norec_result.confidence),
                method="TLP+NoREC",
                issues=all_issues,
                execution_time_ms=max(
                    tlp_result.execution_time_ms,
                    norec_result.execution_time_ms
                ),
                queries_executed=(
                    tlp_result.queries_executed +
                    norec_result.queries_executed
                ),
                metadata={
                    'tlp_result': tlp_result.to_dict(),
                    'norec_result': norec_result.to_dict(),
                }
            )

        # Both validators passed
        return ValidationResult(
            passed=True,
            confidence=max(tlp_result.confidence, norec_result.confidence),
            method="TLP+NoREC",
            issues=[],
            execution_time_ms=max(
                tlp_result.execution_time_ms,
                norec_result.execution_time_ms
            ),
            queries_executed=(
                tlp_result.queries_executed +
                norec_result.queries_executed
            ),
            metadata={
                'tlp_result': tlp_result.to_dict(),
                'norec_result': norec_result.to_dict(),
            }
        )

    async def _analyze_query(
        self,
        sql: str,
        db_connection: str,
        constraints: dict[str, Any],
        schema_info: str | None = None,
    ) -> dict[str, Any]:
        """
        Analyze query execution plan and get semantic feedback.

        Uses two-phase EXPLAIN strategy:
        1. EXPLAIN (FORMAT JSON) - Fast cost estimation without execution
        2. EXPLAIN (ANALYZE, FORMAT JSON) - Full analysis only if cost < threshold

        Args:
            sql: SQL query to analyze
            db_connection: PostgreSQL connection string
            constraints: Performance constraints
            schema_info: Optional schema information

        Returns:
            Dictionary with analysis and feedback
        """
        # Get EXPLAIN plan from database
        explain_result = await self._get_explain_plan(
            sql, db_connection, constraints["analyze_cost_threshold"]
        )

        # Analyze the plan
        analysis = self.analyzer.analyze(explain_result)

        # Translate to semantic feedback
        feedback = self.translator.translate(analysis, constraints, schema_info)

        return {
            "analysis": analysis,
            "feedback": feedback,
            "explain_plan": explain_result
        }

    async def _get_explain_plan(
        self,
        sql: str,
        db_connection: str,
        analyze_cost_threshold: float,
    ) -> list[dict]:
        """
        Get EXPLAIN plan from PostgreSQL using two-phase strategy.

        Phase 1: EXPLAIN (FORMAT JSON) - Estimate cost without execution
        Phase 2: EXPLAIN (ANALYZE, FORMAT JSON) - Full analysis if safe

        Wraps EXPLAIN ANALYZE in transaction for safety per PostgreSQL best practices.

        Args:
            sql: SQL query to explain
            db_connection: PostgreSQL connection string
            analyze_cost_threshold: Cost threshold for running EXPLAIN ANALYZE

        Returns:
            EXPLAIN JSON output as list
        """
        conn = psycopg2.connect(db_connection)
        cursor = conn.cursor()

        try:
            # Set statement timeout for safety
            cursor.execute(f"SET statement_timeout = {self.statement_timeout_ms}")

            # Phase 1: Get estimated cost without execution
            cursor.execute(f"EXPLAIN (FORMAT JSON) {sql}")
            result = cursor.fetchone()[0]
            estimated_cost = result[0]["Plan"]["Total Cost"]

            # Phase 2: Run EXPLAIN ANALYZE only if cost is below threshold
            if estimated_cost < analyze_cost_threshold:
                # Wrap in transaction for safety (per PostgreSQL docs)
                cursor.execute("BEGIN")
                try:
                    cursor.execute(f"EXPLAIN (ANALYZE, FORMAT JSON) {sql}")
                    result = cursor.fetchone()[0]
                finally:
                    cursor.execute("ROLLBACK")  # Always rollback to prevent side effects

            return result

        finally:
            cursor.close()
            conn.close()

    async def _plan_action(
        self,
        current_query: str,
        analysis: dict[str, Any],
        previous_actions: list[Action],
        failed_actions: list[FailedAction],
        iteration: int,
    ) -> Action:
        """
        Plan next optimization action using Claude with extended thinking.

        Per Anthropic 2025 best practices:
        - Use extended thinking for complex reasoning
        - No explicit chain-of-thought prompts (handled automatically)
        - Provide clear context and let the model reason

        Args:
            current_query: Current SQL query
            analysis: Latest analysis results
            previous_actions: Actions taken in previous iterations
            failed_actions: Actions that failed in previous iterations
            iteration: Current iteration number

        Returns:
            Action to take
        """
        # Build context for the planning prompt
        feedback = analysis["feedback"]
        bottlenecks = analysis["analysis"]["bottlenecks"]

        # Format previous actions for context
        history = ""
        if previous_actions:
            history = "\n\nSuccessful actions taken:\n"
            for i, action in enumerate(previous_actions, 1):
                history += f"{i}. {action.type.value}: {action.reasoning}\n"

        # Format failed actions with full error context using ErrorClassifier
        failure_context = ""
        if failed_actions:
            failure_context = "\n\nFailed attempts (DO NOT RETRY THESE EXACT ACTIONS):\n"
            for i, failed in enumerate(failed_actions, 1):
                # Classify the error for structured guidance
                error_classification = self.error_classifier.classify(failed.error)

                failure_context += f"{i}. {failed.action.type.value}: {failed.action.reasoning}\n"
                failure_context += f"   DDL: {failed.action.ddl}\n" if failed.action.ddl else ""
                failure_context += f"   Error: {failed.error}\n"
                failure_context += f"   → Error Category: {error_classification.category.value}\n"
                failure_context += f"   → {error_classification.guidance}\n"
                failure_context += f"   → {self.error_classifier.format_alternatives_for_llm(error_classification)}\n"

        # Build context about created indexes
        indexes_context = ""
        if self.created_indexes:
            indexes_context = f"\nAlready created indexes (DO NOT recreate): {', '.join(self.created_indexes)}\n"

        # Build context about available tools
        hypopg_context = ""
        if self.can_use_hypopg:
            hypopg_context = """
VIRTUAL INDEX TESTING (hypopg available):
- Use TEST_INDEX instead of CREATE_INDEX to test indexes virtually first
- TEST_INDEX creates a virtual index and checks if PostgreSQL would use it
- Only creates the real index if improvement > 10%
- Saves time by avoiding useless index creation

Example:
{
    "type": "TEST_INDEX",
    "ddl": "CREATE INDEX idx_users_email ON users(email)",
    "reasoning": "Testing if email index would help the WHERE clause filter"
}
"""

        prompt = f"""You are optimizing this SQL query:

```sql
{current_query}
```

Current performance analysis:
- Status: {feedback['status']}
- Reason: {feedback['reason']}
- Suggestion: {feedback['suggestion']}
- Priority: {feedback['priority']}
- Current iteration: {iteration}

Detected bottlenecks:
{json.dumps(bottlenecks, indent=2)}
{indexes_context}
{history}
{failure_context}
{hypopg_context}

EFFICIENCY CONSTRAINTS:
- Maximum {self.max_actions_without_improvement} consecutive actions allowed without >{self.min_improvement_threshold*100:.0f}% cost improvement
- Think strategically: pick the SINGLE most impactful action first
- Avoid redundant actions (don't undo previous changes, don't create similar indexes)

PLANNING APPROACH:
1. Identify the PRIMARY bottleneck (highest cost contributor)
2. Choose ONE targeted fix for that bottleneck
3. If index helps, create it. If query structure is the issue, rewrite.
4. Don't create multiple indexes - pick the best one

OPTIMIZATION PHILOSOPHY:
- The goal is BEST POSSIBLE performance with MINIMAL actions
- Prioritize: Index on filter columns > Expression indexes > Query rewrites
- One good index is better than three mediocre ones

CRITICAL RULES:
1. DO NOT retry failed actions - learn from them and try alternatives
2. DO NOT recreate indexes that already exist (check list above)
3. DO NOT undo previous optimizations (e.g., adding CTE then removing it)
4. Choose DONE early if the main bottleneck is addressed

Respond with JSON in this exact format:
{{
    "type": "TEST_INDEX" | "CREATE_INDEX" | "REWRITE_QUERY" | "RUN_ANALYZE" | "DONE" | "FAILED",
    "reasoning": "Brief explanation of why this action",
    "ddl": "SQL DDL statement (for TEST_INDEX, CREATE_INDEX, or RUN_ANALYZE)",
    "new_query": "Rewritten query (for REWRITE_QUERY)"
}}

Choose DONE when:
- You've optimized the query to its best achievable state
- Further optimizations would have negligible impact (<5% improvement)
- The query is already well-optimized (index scans, efficient joins)

Choose FAILED when:
- Constraints are impossible to meet given the data/query structure
- You've exhausted all reasonable optimization strategies
- Include the best achievable metrics in your reasoning
"""

        # Call LLM with thinking (extended thinking for Claude, CoT for others)
        try:
            with display.spinner("Planning optimization..."):
                response = self.llm_client.chat(
                    messages=[{"role": "user", "content": prompt}],
                    use_thinking=self.use_thinking,
                    thinking_budget=self.thinking_budget,
                )

            # Parse action from response
            action = parse_action_from_llm_response(response.content)

            # Show planned action as tool call
            display.tool_call("planner", {
                "action": action.type.value,
                "reasoning": action.reasoning[:80] + "..." if len(action.reasoning) > 80 else action.reasoning
            })

            return action

        except ValueError as e:
            # JSON parsing or validation error - likely empty/malformed LLM response
            # Default to DONE since this usually happens when optimization is complete
            display.error(f"Planning failed: {e}")
            display.warning("Query cannot be optimized further")
            return Action(
                type=ActionType.DONE,
                reasoning=(
                    f"LLM response parsing failed (likely empty or malformed response). "
                    f"Defaulting to DONE as this typically occurs when optimization is complete. "
                    f"Original error: {str(e)}"
                )
            )
        except Exception as e:
            # Other unexpected errors - treat as failure
            display.error(f"Planning failed: {e}")
            return Action(
                type=ActionType.FAILED,
                reasoning=f"Failed to plan action: {str(e)}"
            )

    async def _execute_action(
        self,
        action: Action,
        db_connection: str,
        current_query: str | None = None,
    ) -> dict[str, Any]:
        """
        Execute an optimization action.

        Args:
            action: Action to execute
            db_connection: PostgreSQL connection string
            current_query: Current SQL query (needed for TEST_INDEX)

        Returns:
            Execution result with success status
        """
        if action.type == ActionType.TEST_INDEX:
            # Virtual index testing via hypopg
            return await self._execute_test_index(action, db_connection, current_query)

        elif action.type == ActionType.CREATE_INDEX:
            return await self._execute_ddl(action.ddl, db_connection)

        elif action.type == ActionType.RUN_ANALYZE:
            return await self._execute_ddl(action.ddl, db_connection)

        elif action.type == ActionType.REWRITE_QUERY:
            # Query rewrite doesn't execute anything
            return {"success": True, "message": "Query rewritten"}

        else:
            return {"success": True, "message": f"Action {action.type.value} completed"}

    async def _execute_test_index(
        self,
        action: Action,
        db_connection: str,
        current_query: str | None,
    ) -> dict[str, Any]:
        """
        Execute TEST_INDEX action using hypopg.

        Tests index virtually, only creates real index if beneficial.
        Falls back to CREATE_INDEX if hypopg unavailable.

        Args:
            action: Action with index DDL
            db_connection: PostgreSQL connection string
            current_query: Query to test index against

        Returns:
            Execution result
        """
        if not self.can_use_hypopg or not self.hypopg_tool:
            # Fallback: create the index directly
            display.warning("hypopg not available - creating real index")
            return await self._execute_ddl(action.ddl, db_connection)

        if not current_query:
            # Can't test without a query - fall back to creating
            display.warning("No query context - creating real index")
            return await self._execute_ddl(action.ddl, db_connection)

        # Test the index virtually
        result = self.hypopg_tool.test_index(current_query, action.ddl)

        if result.error:
            return {
                "success": False,
                "error": f"Virtual index test failed: {result.error}"
            }

        if self.hypopg_tool.is_worthwhile(result):
            # Index would be beneficial - create it for real
            display.success(
                f"Virtual test: {result.improvement_pct:.1f}% improvement - creating index"
            )
            return await self._execute_ddl(action.ddl, db_connection)
        else:
            # Index not beneficial - skip creation
            if result.would_be_used:
                reason = f"Index would be used but only {result.improvement_pct:.1f}% improvement (threshold: 10%)"
            else:
                reason = "PostgreSQL would not use this index"

            display.info(f"Virtual test: {reason} - skipping")
            return {
                "success": True,
                "message": f"Index skipped: {reason}",
                "virtual_test": result.to_dict()
            }

    async def _execute_ddl(
        self,
        ddl: str,
        db_connection: str,
    ) -> dict[str, Any]:
        """
        Execute DDL statement with safety checks.

        Args:
            ddl: DDL statement to execute
            db_connection: PostgreSQL connection string

        Returns:
            Execution result
        """
        # Avoid re-executing same DDL
        if ddl in self.executed_ddls:
            return {"success": True, "message": "DDL already executed"}

        # Check if this exact DDL failed before
        if ddl in self.failed_ddls:
            return {
                "success": False,
                "error": "This DDL was already attempted and failed. Try a different approach."
            }

        conn = psycopg2.connect(db_connection)

        # CREATE INDEX CONCURRENTLY cannot run inside a transaction block
        # Enable autocommit for CONCURRENTLY operations
        uses_concurrently = "CONCURRENTLY" in ddl.upper()
        if uses_concurrently:
            conn.autocommit = True

        cursor = conn.cursor()

        try:
            cursor.execute(f"SET statement_timeout = {self.statement_timeout_ms}")
            cursor.execute(ddl)

            if not uses_concurrently:
                conn.commit()

            self.executed_ddls.add(ddl)

            return {"success": True, "message": "DDL executed successfully"}

        except Exception as e:
            if not uses_concurrently:
                conn.rollback()
            return {"success": False, "error": str(e)}

        finally:
            cursor.close()
            conn.close()

    def _interpret_error(self, error: str) -> str:
        """
        Interpret PostgreSQL error messages for the LLM.

        Args:
            error: Raw error message from PostgreSQL

        Returns:
            Human-readable interpretation with suggested alternatives
        """
        error_lower = error.lower()

        # Index already exists
        if "already exists" in error_lower and "relation" in error_lower:
            return "The index/table already exists. Try checking if it's being used, or create a different index."

        # Permission denied
        if "permission denied" in error_lower:
            return "Permission denied. You may not have CREATE INDEX privileges on this table."

        # Syntax error
        if "syntax error" in error_lower:
            return "SQL syntax error. Check the DDL statement format."

        # Timeout
        if "timeout" in error_lower or "canceling statement" in error_lower:
            return "Query timeout. The operation took too long. Try a different optimization approach."

        # Lock timeout
        if "lock" in error_lower and ("timeout" in error_lower or "deadlock" in error_lower):
            return "Lock/deadlock detected. The table may be in use. Try again or use CONCURRENTLY."

        # Table doesn't exist
        if "does not exist" in error_lower and "relation" in error_lower:
            return "Table/relation doesn't exist. Check table name spelling."

        # Generic fallback
        return "Unexpected error. Consider trying a different optimization strategy."
