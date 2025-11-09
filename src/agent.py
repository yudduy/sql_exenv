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
import os
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List
import psycopg2
import anthropic

from analyzer import ExplainAnalyzer
from semanticizer import SemanticTranslator
from actions import Action, ActionType, parse_action_from_llm_response


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
    actions: List[Action] = field(default_factory=list)
    metrics: Dict[str, Any] = field(default_factory=dict)
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
        use_extended_thinking: bool = True,
        thinking_budget: int = 4000,
        model: str = "claude-sonnet-4-5-20250929",
        api_key: Optional[str] = None,
    ):
        """
        Initialize the SQL optimization agent.

        Args:
            max_iterations: Maximum optimization iterations (default: 10)
            timeout_seconds: Overall timeout for optimization task (default: 120)
            statement_timeout_ms: PostgreSQL statement timeout in ms (default: 60000)
            use_extended_thinking: Enable Claude extended thinking mode (default: True)
            thinking_budget: Token budget for extended thinking (default: 4000)
            model: Claude model to use (default: claude-sonnet-4-5-20250929)
            api_key: Anthropic API key (or uses ANTHROPIC_API_KEY env var)
        """
        self.max_iterations = max_iterations
        self.timeout_seconds = timeout_seconds
        self.statement_timeout_ms = statement_timeout_ms
        self.use_extended_thinking = use_extended_thinking
        self.thinking_budget = max(thinking_budget, 1024)  # Minimum per Anthropic docs
        self.model = model

        # Initialize components
        self.analyzer = ExplainAnalyzer()
        self.translator = SemanticTranslator(api_key=api_key)

        api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("Anthropic API key required (set ANTHROPIC_API_KEY env var)")

        self.client = anthropic.Anthropic(api_key=api_key)

        # Track executed DDLs to avoid re-applying same optimization
        self.executed_ddls: set = set()

    async def optimize_query(
        self,
        sql: str,
        db_connection: str,
        max_cost: float = 10000.0,
        max_time_ms: int = 30000,
        analyze_cost_threshold: float = 5_000_000.0,
        schema_info: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Autonomously optimize a SQL query.

        Uses a ReAct loop to iteratively improve query performance:
        1. Analyze current query execution plan
        2. Plan next optimization action using Claude
        3. Act by executing the planned optimization
        4. Observe the results and determine if constraints are met
        5. Repeat until optimized or max iterations reached

        Args:
            sql: SQL query to optimize
            db_connection: PostgreSQL connection string
            max_cost: Maximum acceptable query cost (default: 10000.0)
            max_time_ms: Maximum acceptable execution time in ms (default: 30000)
            analyze_cost_threshold: Cost threshold for EXPLAIN ANALYZE (default: 5M)
            schema_info: Optional database schema information

        Returns:
            Dictionary with optimization results:
            {
                "success": bool,
                "final_query": str,
                "actions": List[Action],
                "metrics": dict,
                "iterations": int,
                "reason": str
            }
        """
        current_query = sql.strip()
        actions_taken: List[Action] = []
        iteration = 0

        constraints = {
            "max_cost": max_cost,
            "max_time_ms": max_time_ms,
            "analyze_cost_threshold": analyze_cost_threshold,
        }

        print(f"\n{'='*70}")
        print(f"Starting autonomous optimization")
        print(f"{'='*70}")
        print(f"Query: {current_query[:100]}...")
        print(f"Constraints: max_cost={max_cost}, max_time_ms={max_time_ms}")
        print(f"{'='*70}\n")

        # ReAct Loop: Reason → Act → Observe
        for iteration in range(1, self.max_iterations + 1):
            print(f"\n--- Iteration {iteration}/{self.max_iterations} ---")

            # STEP 1: ANALYZE - Get execution plan and identify bottlenecks
            analysis = await self._analyze_query(
                current_query, db_connection, constraints, schema_info
            )

            # STEP 2: OBSERVE - Check if query meets constraints
            if analysis["feedback"]["status"] == "pass":
                print(f"✓ Query meets performance constraints")
                return {
                    "success": True,
                    "final_query": current_query,
                    "actions": actions_taken,
                    "metrics": {
                        "final_cost": analysis["analysis"]["total_cost"],
                        "final_time_ms": analysis["analysis"].get("execution_time_ms", 0),
                        "initial_cost": actions_taken[0].metrics.get("cost_before", 0) if actions_taken else analysis["analysis"]["total_cost"],
                    },
                    "iterations": iteration,
                    "reason": analysis["feedback"]["reason"]
                }

            # STEP 3: PLAN - Decide next action using Claude with extended thinking
            action = await self._plan_action(
                current_query, analysis, actions_taken, iteration
            )

            if action.type == ActionType.DONE:
                # Agent decided optimization is complete
                return {
                    "success": False,
                    "final_query": current_query,
                    "actions": actions_taken,
                    "metrics": {
                        "final_cost": analysis["analysis"]["total_cost"],
                    },
                    "iterations": iteration,
                    "reason": action.reasoning
                }

            if action.type == ActionType.FAILED:
                # Agent determined query cannot be optimized further
                return {
                    "success": False,
                    "final_query": current_query,
                    "actions": actions_taken,
                    "metrics": {},
                    "iterations": iteration,
                    "reason": action.reasoning
                }

            # Record metrics before action
            action.metrics = {
                "cost_before": analysis["analysis"]["total_cost"],
                "iteration": iteration,
            }

            # STEP 4: ACT - Execute the planned optimization
            execution_result = await self._execute_action(action, db_connection)

            if not execution_result["success"]:
                print(f"⚠️  Action failed: {execution_result['error']}")
                # Continue to next iteration
                continue

            # Update current query if it was rewritten
            if action.type == ActionType.REWRITE_QUERY and action.new_query:
                current_query = action.new_query
                print(f"→ Query rewritten")

            actions_taken.append(action)

        # Max iterations reached
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

    async def _analyze_query(
        self,
        sql: str,
        db_connection: str,
        constraints: Dict[str, Any],
        schema_info: Optional[str] = None,
    ) -> Dict[str, Any]:
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
    ) -> List[Dict]:
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

            print(f"  Estimated cost: {estimated_cost:,.2f}")

            # Phase 2: Run EXPLAIN ANALYZE only if cost is below threshold
            if estimated_cost < analyze_cost_threshold:
                print(f"  Running EXPLAIN ANALYZE (cost < {analyze_cost_threshold:,.0f})")

                # Wrap in transaction for safety (per PostgreSQL docs)
                cursor.execute("BEGIN")
                try:
                    cursor.execute(f"EXPLAIN (ANALYZE, FORMAT JSON) {sql}")
                    result = cursor.fetchone()[0]
                finally:
                    cursor.execute("ROLLBACK")  # Always rollback to prevent side effects
            else:
                print(f"  Skipping EXPLAIN ANALYZE (cost too high)")

            return result

        finally:
            cursor.close()
            conn.close()

    async def _plan_action(
        self,
        current_query: str,
        analysis: Dict[str, Any],
        previous_actions: List[Action],
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
            history = "\n\nPrevious actions taken:\n"
            for i, action in enumerate(previous_actions, 1):
                history += f"{i}. {action.type.value}: {action.reasoning}\n"

        prompt = f"""You are optimizing this SQL query:

```sql
{current_query}
```

Current performance analysis:
- Status: {feedback['status']}
- Reason: {feedback['reason']}
- Suggestion: {feedback['suggestion']}
- Priority: {feedback['priority']}

Detected bottlenecks:
{json.dumps(bottlenecks, indent=2)}

{history}

Based on this analysis, what action should be taken next?

Respond with JSON in this exact format:
{{
    "type": "CREATE_INDEX" | "REWRITE_QUERY" | "RUN_ANALYZE" | "DONE" | "FAILED",
    "reasoning": "Brief explanation of why this action",
    "ddl": "SQL DDL statement (for CREATE_INDEX or RUN_ANALYZE)",
    "new_query": "Rewritten query (for REWRITE_QUERY)"
}}

Choose DONE if the query cannot be optimized further.
Choose FAILED if you've tried everything and it's still not meeting constraints.
"""

        # Call Claude with extended thinking
        kwargs = {
            "model": self.model,
            "max_tokens": 4000,
            "temperature": 0,  # Deterministic for consistent suggestions
            "messages": [{"role": "user", "content": prompt}]
        }

        # Add extended thinking if enabled
        if self.use_extended_thinking:
            kwargs["thinking"] = {
                "type": "enabled",
                "budget_tokens": self.thinking_budget
            }

        try:
            response = self.client.messages.create(**kwargs)

            # Extract response content
            response_text = ""
            for block in response.content:
                if block.type == "text":
                    response_text += block.text

            # Parse action from response
            action = parse_action_from_llm_response(response_text)

            print(f"  Planned action: {action.type.value}")
            print(f"  Reasoning: {action.reasoning}")

            return action

        except Exception as e:
            print(f"  ⚠️  Planning failed: {e}")
            return Action(
                type=ActionType.FAILED,
                reasoning=f"Failed to plan action: {str(e)}"
            )

    async def _execute_action(
        self,
        action: Action,
        db_connection: str,
    ) -> Dict[str, Any]:
        """
        Execute an optimization action.

        Args:
            action: Action to execute
            db_connection: PostgreSQL connection string

        Returns:
            Execution result with success status
        """
        if action.type == ActionType.CREATE_INDEX:
            return await self._execute_ddl(action.ddl, db_connection)

        elif action.type == ActionType.RUN_ANALYZE:
            return await self._execute_ddl(action.ddl, db_connection)

        elif action.type == ActionType.REWRITE_QUERY:
            # Query rewrite doesn't execute anything
            return {"success": True, "message": "Query rewritten"}

        else:
            return {"success": True, "message": f"Action {action.type.value} completed"}

    async def _execute_ddl(
        self,
        ddl: str,
        db_connection: str,
    ) -> Dict[str, Any]:
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
            print(f"  → Skipping duplicate DDL")
            return {"success": True, "message": "DDL already executed"}

        conn = psycopg2.connect(db_connection)
        cursor = conn.cursor()

        try:
            cursor.execute(f"SET statement_timeout = {self.statement_timeout_ms}")
            cursor.execute(ddl)
            conn.commit()

            self.executed_ddls.add(ddl)
            print(f"  ✓ Executed: {ddl[:60]}...")

            return {"success": True, "message": "DDL executed successfully"}

        except Exception as e:
            conn.rollback()
            print(f"  ✗ DDL failed: {e}")
            return {"success": False, "error": str(e)}

        finally:
            cursor.close()
            conn.close()
