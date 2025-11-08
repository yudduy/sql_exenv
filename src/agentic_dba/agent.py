"""
Autonomous SQL Optimization Agent

Implements a ReAct-style autonomous loop for iterative query optimization.
Follows Anthropic's best practices: simple, composable patterns without heavy frameworks.

Architecture:
    1. Analyze query with exev.py tool
    2. Plan action using Claude Sonnet 4.5 with extended thinking
    3. Execute action (CREATE INDEX, REWRITE, etc.)
    4. Validate optimization
    5. Repeat until PASS or max iterations
"""

import asyncio
import json
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Dict, Any, List, Set
import anthropic

from .actions import Action, ActionType, Solution, parse_action_from_llm_response
from .mcp_server import QueryOptimizationTool


@dataclass
class IterationState:
    """
    Tracks state of a single optimization iteration for history compression.

    This enables the agent to learn from previous actions and avoid repeating
    ineffective optimizations. Keeps only essential metrics (80 tokens vs 500).
    """
    iteration: int
    action_type: str  # "CREATE_INDEX" | "REWRITE_QUERY" | "RUN_ANALYZE"
    action_summary: str  # "idx_users_email" (not full DDL)

    # Performance metrics (compact)
    cost_before: float
    cost_after: float
    cost_delta_pct: float  # Precomputed percentage change

    # Outcome (1-word status)
    outcome: str  # "improved" | "regressed" | "unchanged"

    # Key insight (1 sentence max)
    insight: str  # "Index created but not used by planner"


class IterationController:
    """
    Controls adaptive iteration stopping for the optimization loop.

    Implements multi-criteria termination to avoid:
    - Premature stopping (query wrong but low cost)
    - Infinite loops (stuck repeating same action)
    - Wasted iterations (no progress)
    """

    def __init__(self, min_iterations: int = 3, max_iterations: int = 10):
        """
        Initialize controller.

        Args:
            min_iterations: Minimum iterations before considering early stop
            max_iterations: Hard maximum iterations (safety limit)
        """
        self.min_iterations = min_iterations
        self.max_iterations = max_iterations

    def should_continue(
        self,
        iteration: int,
        feedback: Dict[str, Any],
        actions: List[Action],
        correctness: Optional[Dict[str, Any]] = None,
        timeout_exceeded: bool = False,
        iteration_history: Optional[List[IterationState]] = None,
    ) -> tuple[bool, str]:
        """
        Decide if agent should continue iterating.
        
        Uses adaptive logic to detect:
        - Success (query optimized)
        - Stagnation (no cost improvement)
        - Repetition (same action repeated)
        - Ineffectiveness (actions not helping)

        Returns:
            (should_continue: bool, reason: str)
        """
        if iteration_history is None:
            iteration_history = []
            
        # Hard limits
        if timeout_exceeded:
            return False, "Timeout exceeded"

        if iteration >= self.max_iterations:
            return False, f"Max iterations ({self.max_iterations}) reached"

        # Success criteria - CORRECTNESS + PERFORMANCE
        fb = feedback.get("feedback", {})
        status = fb.get("status", "unknown")
        priority = fb.get("priority", "")

        if status == "pass" and correctness and correctness.get("matches"):
            return False, "Success: Query correct and optimized"

        # Early stopping - logic errors must be fixed first
        if priority == "CRITICAL" or "logic error" in fb.get("reason", "").lower():
            if iteration < self.max_iterations:
                return True, "Critical logic error needs fixing"

        # Early stopping - no progress detection (enhanced with iteration_history)
        if iteration >= self.min_iterations:
            # Check for cost stagnation using iteration_history
            if self._cost_stagnating(iteration_history, n=3):
                return False, "Cost stagnating: No meaningful improvement in last 3 iterations. Consider query rewrite."
            
            # Check for ineffective actions (actions taken but cost unchanged/increased)
            if self._ineffective_actions(iteration_history, n=2):
                return False, "Ineffective actions: Last 2 actions did not improve cost. Indexes may not be used by planner."
            
            # Check for terminal action repetition
            if self._no_improvement_in_n_iterations(actions, n=2):
                return False, "No progress in last 2 iterations"

            # Check for action type repetition
            if self._repeating_same_action(actions):
                return False, "Agent stuck repeating same action"

        # Continue if logic errors exist (even if performance is good)
        if correctness and not correctness.get("matches"):
            return True, "Logic error needs fixing"

        # Continue if performance issues exist
        if status == "fail":
            return True, "Performance optimization needed"

        # Continue if within iteration budget
        return True, "Continue optimization"

    def _no_improvement_in_n_iterations(self, actions: List[Action], n: int = 2) -> bool:
        """Check if last N actions were all DONE or FAILED without actual changes."""
        if len(actions) < n:
            return False

        last_n = actions[-n:]
        # If last N actions were all terminal states, we're stuck
        return all(a.type in [ActionType.DONE, ActionType.FAILED] for a in last_n)

    def _repeating_same_action(self, actions: List[Action]) -> bool:
        """Check if agent is stuck repeating the same action."""
        if len(actions) < 3:
            return False

        # Check last 3 actions
        last_3_types = [a.type for a in actions[-3:]]

        # If same action type repeated 3 times, we're stuck
        if len(set(last_3_types)) == 1:
            return True

        # Check for ping-pong pattern (A->B->A->B)
        if len(actions) >= 4:
            last_4_types = [a.type for a in actions[-4:]]
            if last_4_types[0] == last_4_types[2] and last_4_types[1] == last_4_types[3]:
                return True

        return False
    
    def _cost_stagnating(self, iteration_history: List[IterationState], n: int = 3) -> bool:
        """
        Check if cost has stagnated (no meaningful improvement) in last N iterations.
        
        Considers stagnation if:
        - All last N iterations show <1% cost improvement
        - Or mix of tiny improvements and regressions averaging to <0.5%
        """
        if len(iteration_history) < n:
            return False
        
        last_n = iteration_history[-n:]
        
        # Calculate total cost change over last N iterations
        total_delta_pct = sum([state.cost_delta_pct for state in last_n])
        
        # Stagnating if average change is less than 0.5% per iteration
        avg_delta = total_delta_pct / n
        
        # Also check if all deltas are tiny (< 1% each)
        all_tiny = all(abs(state.cost_delta_pct) < 1.0 for state in last_n)
        
        return avg_delta > -0.5 or all_tiny  # Negative delta means improvement
    
    def _ineffective_actions(self, iteration_history: List[IterationState], n: int = 2) -> bool:
        """
        Check if last N actions were ineffective (cost unchanged or regressed).
        
        An action is ineffective if:
        - outcome is 'regressed' (cost went up)
        - outcome is 'unchanged' (cost stayed the same)
        
        This catches cases where indexes are created but not used by planner.
        """
        if len(iteration_history) < n:
            return False
        
        last_n = iteration_history[-n:]
        
        # Check if all last N actions were ineffective
        ineffective_count = sum(
            1 for state in last_n 
            if state.outcome in ['regressed', 'unchanged']
        )
        
        return ineffective_count == n


@dataclass
class BIRDCriticTask:
    """
    Represents a single BIRD-CRITIC task.

    Attributes:
        task_id: Unique identifier
        db_id: Database name
        buggy_sql: Original query with performance issues (deprecated, use issue_sql)
        issue_sql: List of SQL statements to optimize (supports multi-query tasks)
        user_query: Natural language description
        solution_sql: Ground truth solution (for evaluation)
        efficiency: Whether this task requires optimization
        preprocess_sql: Setup queries to run before issue_sql (e.g., CREATE TABLE)
        clean_up_sql: Teardown queries to run after task completion
    """

    task_id: str
    db_id: str
    user_query: str
    buggy_sql: Optional[str] = None  # Kept for backward compatibility
    issue_sql: Optional[List[str]] = None  # Multi-statement support
    solution_sql: Optional[str] = None
    efficiency: bool = False
    preprocess_sql: Optional[List[str]] = None  # Setup queries
    clean_up_sql: Optional[List[str]] = None  # Teardown queries


class SQLOptimizationAgent:
    """
    Autonomous agent for SQL query optimization.

    Uses a ReAct-style loop:
    - Reason: Analyze current query performance
    - Act: Take optimization action
    - Observe: Validate improvement
    - Repeat: Until optimized or max iterations
    """

    def __init__(
        self,
        max_iterations: int = 10,  # Increased from 5 to 10 for complex rewrites
        timeout_per_task_seconds: int = 120,
        use_extended_thinking: bool = True,
        extended_thinking_budget: int = 8000,
        min_iterations: int = 3,  # Minimum before considering early stop
    ):
        """
        Initialize the autonomous agent.

        Args:
            max_iterations: Maximum optimization attempts per task (7-10 recommended)
            timeout_per_task_seconds: Total timeout for one task
            use_extended_thinking: Enable Claude's extended thinking mode
            extended_thinking_budget: Token budget for thinking (1024-64000)
            min_iterations: Minimum iterations before early stopping
        """
        self.max_iterations = max_iterations
        self.timeout_seconds = timeout_per_task_seconds
        self.use_extended_thinking = use_extended_thinking
        self.thinking_budget = extended_thinking_budget

        # Initialize adaptive iteration controller
        self.iteration_controller = IterationController(
            min_iterations=min_iterations,
            max_iterations=max_iterations
        )

        # Initialize tools
        self.optimization_tool = QueryOptimizationTool(use_mock_translator=False)
        self.anthropic_client = anthropic.Anthropic(
            api_key=os.environ.get("ANTHROPIC_API_KEY")
        )

        # Model configuration
        self.planner_model = "claude-sonnet-4-5-20250929"  # Latest Sonnet 4.5

        # Cache for loaded schemas
        self._schema_cache: Dict[str, str] = {}

    def _load_schema_from_jsonl(self, db_id: str, schema_file_paths: Optional[List[Path]] = None) -> Optional[str]:
        """
        Load database schema from BIRD-CRITIC JSONL schema files.

        Args:
            db_id: Database identifier (e.g., 'student_club', 'financial')
            schema_file_paths: Optional paths to schema JSONL files.
                             Defaults to checking BIRD-CRITIC-1/baseline/data/*.jsonl

        Returns:
            Full schema string with CREATE TABLE statements and sample data, or None if not found
        """
        # Check cache first
        if db_id in self._schema_cache:
            return self._schema_cache[db_id]

        # Default schema file paths
        if schema_file_paths is None:
            base_path = Path(__file__).parent.parent.parent / "BIRD-CRITIC-1" / "baseline" / "data"
            schema_file_paths = [
                base_path / "flash_schema.jsonl",
                base_path / "post_schema.jsonl",
                base_path / "open_schema.jsonl",
            ]

        # CRITICAL FIX: Schema JSONL files use instance_id, NOT db_id
        # Load mapping from instance_to_db_mapping.json
        mapping_path = Path(__file__).parent.parent.parent / "BIRD-CRITIC-1" / "baseline" / "data" / "instance_to_db_mapping.json"
        instance_id = None

        if mapping_path.exists():
            try:
                with open(mapping_path, 'r') as f:
                    # Mapping is {instance_id: db_id}, need reverse lookup
                    mapping = json.load(f)
                    # Find instance_id where db_id matches
                    for inst_id, mapped_db_id in mapping.items():
                        if mapped_db_id == db_id:
                            instance_id = int(inst_id)
                            break
            except (json.JSONDecodeError, IOError) as e:
                print(f"Warning: Failed to load instance mapping: {e}")

        if instance_id is None:
            # Fallback: try numeric db_id as instance_id (silently)
            try:
                instance_id = int(db_id)
            except ValueError:
                pass

        # Search through schema files
        for schema_file in schema_file_paths:
            if not schema_file.exists():
                continue

            try:
                with open(schema_file, 'r') as f:
                    for line in f:
                        if not line.strip():
                            continue

                        entry = json.loads(line)
                        # FIXED: Match by instance_id only (schema files don't have db_id field)
                        if instance_id is not None and entry.get('instance_id') == instance_id:
                            # Prefer preprocess_schema (has sample data), fallback to original_schema
                            schema = entry.get('preprocess_schema') or entry.get('original_schema')
                            if schema:
                                self._schema_cache[db_id] = schema
                                return schema
            except (json.JSONDecodeError, IOError) as e:
                print(f"Warning: Failed to load schema from {schema_file}: {e}")
                continue

        # Schema not found in JSONL files (expected for user databases)
        return None

    async def solve_task(
        self,
        task: BIRDCriticTask,
        db_connection_string: str,
        constraints: Optional[Dict[str, Any]] = None,
    ) -> Solution:
        """
        Autonomously optimize SQL query(ies).

        Supports both single-query and multi-query tasks:
        - Single query: Uses task.buggy_sql (backward compatible)
        - Multi-query: Uses task.issue_sql array (multiple statements)

        Args:
            task: BIRD-CRITIC task to solve
            db_connection_string: PostgreSQL connection string
            constraints: Performance constraints (max_cost, max_time_ms)

        Returns:
            Solution with final query and actions taken
        """
        if constraints is None:
            constraints = {
                "max_cost": 10000.0,
                "max_time_ms": 30000,
                "analyze_cost_threshold": 5_000_000,
            }

        # Handle both single query and multi-query tasks
        if task.issue_sql:
            # Multi-query task: optimize all queries in sequence
            current_queries = task.issue_sql.copy()
            is_multi_query = len(current_queries) > 1
        else:
            # Single query task (backward compatibility)
            current_queries = [task.buggy_sql] if task.buggy_sql else []
            is_multi_query = False

        if not current_queries:
            return Solution(
                final_query="",
                actions=[],
                success=False,
                reason="No queries provided in task"
            )

        # Track ENUM types created during preprocess for name resolution
        created_enums = {}  # Maps: expected_name -> actual_name

        # Run preprocess_sql setup queries if provided
        if task.preprocess_sql:
            print(f"\n=== Running {len(task.preprocess_sql)} setup queries ===")
            for idx, setup_query in enumerate(task.preprocess_sql, 1):
                try:
                    await self._execute_ddl(setup_query, db_connection_string)
                    print(f"  ✓ Setup query {idx}/{len(task.preprocess_sql)}")

                    # Track ENUM type creation (extract type name)
                    if "CREATE TYPE" in setup_query.upper() and "ENUM" in setup_query.upper():
                        # Pattern: CREATE TYPE typename AS ENUM
                        match = re.search(r'CREATE TYPE\s+(\w+)\s+AS ENUM', setup_query, re.IGNORECASE)
                        if match:
                            actual_type_name = match.group(1)
                            # If it ends with _enum, the issue_sql might expect the base name
                            if actual_type_name.endswith('_enum'):
                                expected_name = actual_type_name[:-5]  # Remove _enum suffix
                                created_enums[expected_name] = actual_type_name
                                print(f"  → Tracked ENUM: {expected_name} -> {actual_type_name}")
                except Exception as e:
                    print(f"  ⚠️  Setup query {idx} failed: {e}")
                    # Continue anyway - some setup may be idempotent

        # FIX 3: Check if this is a multi-statement Management task that needs batch execution
        # Management tasks are typically DDL operations that don't require performance optimization
        if len(current_queries) > 1 and not task.efficiency:
            print(f"\n🔧 Detected multi-statement DDL sequence ({len(current_queries)} statements)")
            print("Executing as atomic batch to maintain dependencies...")

            # Try batch execution, but handle syntax errors gracefully
            try:
                # If we have ENUM name mappings, adjust the queries
                adjusted_queries = []
                for stmt in current_queries:
                    adjusted_stmt = stmt
                    # Replace ENUM type names in ALTER TYPE statements
                    if "ALTER TYPE" in stmt.upper() and created_enums:
                        for expected_name, actual_name in created_enums.items():
                            if expected_name in stmt and expected_name != actual_name:
                                print(f"  → Adjusting ENUM reference: {expected_name} -> {actual_name}")
                                adjusted_stmt = adjusted_stmt.replace(expected_name, actual_name)
                    adjusted_queries.append(adjusted_stmt)

                all_success = True
                executed_count = 0
                first_syntax_error = None

                for idx, stmt in enumerate(adjusted_queries, 1):
                    try:
                        print(f"\n  → Executing statement {idx}/{len(adjusted_queries)}")
                        await self._execute_ddl(stmt, db_connection_string)
                        print(f"  ✓ Statement {idx} succeeded")
                        executed_count += 1
                    except Exception as e:
                        error_msg = str(e)
                        print(f"  ✗ Statement {idx} failed: {error_msg}")

                        # Check if it's a syntax error (debugging task with broken SQL)
                        if "syntax error" in error_msg.lower():
                            if not first_syntax_error:
                                first_syntax_error = (idx, error_msg)
                            print(f"  → Syntax error detected in debugging task")
                            print(f"  → Stopping batch execution, will analyze query instead")
                            break

                        # Check if it's a benign "already exists" error
                        elif "already exists" in error_msg.lower():
                            print(f"  → Skipping (object already exists)")
                            executed_count += 1
                            continue
                        else:
                            all_success = False
                            print(f"  ⚠️  Critical error in statement {idx}, stopping batch execution")
                            break

                # If we hit a syntax error, this is a debugging task
                # Fall through to normal analysis instead of returning failure
                if first_syntax_error:
                    print(f"\n⚠️  Syntax error in statement {first_syntax_error[0]}")
                    print(f"  → This appears to be a debugging task with intentionally broken SQL")
                    print(f"  → Skipping batch execution, proceeding with normal analysis")
                    # Don't return - fall through to normal analysis loop below
                elif all_success or executed_count == len(adjusted_queries):
                    print(f"\n✅ Batch execution complete: {executed_count}/{len(adjusted_queries)} statements")
                    solution = Solution(
                        final_query="\n".join(adjusted_queries),
                        actions=[],
                        success=True,
                        reason=f"Multi-statement DDL batch executed successfully ({executed_count} statements)"
                    )
                    await self._run_cleanup_queries(task, db_connection_string)
                    return solution
                else:
                    print(f"\n❌ Batch execution failed: {executed_count}/{len(adjusted_queries)} statements succeeded")
                    solution = Solution(
                        final_query="\n".join(adjusted_queries),
                        actions=[],
                        success=False,
                        reason=f"Multi-statement DDL batch failed at statement {executed_count + 1}"
                    )
                    await self._run_cleanup_queries(task, db_connection_string)
                    return solution
            except Exception as outer_e:
                print(f"\n❌ Batch execution error: {outer_e}")
                # Fall through to normal analysis

        current_query = current_queries[0]  # Start with first query
        actions_taken: List[Action] = []
        executed_ddls: Set[str] = set()  # Track successful DDL to prevent re-attempts
        start_time = asyncio.get_event_loop().time()

        # Initialize iteration history for stateful feedback (Tier 1 enhancement)
        iteration_history: List[IterationState] = []
        previous_cost: Optional[float] = None

        for iteration in range(self.max_iterations):
            # Check timeout
            elapsed = asyncio.get_event_loop().time() - start_time
            if elapsed > self.timeout_seconds:
                solution = Solution(
                    final_query=current_query,
                    actions=actions_taken,
                    success=False,
                    reason=f"Timeout after {elapsed:.1f}s",
                )
                await self._run_cleanup_queries(task, db_connection_string)
                return solution

            # STEP 1: ANALYZE current query state
            feedback = await self._analyze_query(
                current_query, db_connection_string, constraints, task=task
            )

            if not feedback.get("success", False):
                # Query execution failed
                solution = Solution(
                    final_query=current_query,
                    actions=actions_taken,
                    success=False,
                    reason=f"Query analysis failed: {feedback.get('error', 'Unknown error')}",
                )
                await self._run_cleanup_queries(task, db_connection_string)
                return solution

            # STEP 1.5: Detect stagnation/ineffective actions BEFORE planning
            # This gives the LLM explicit signals to help it decide to exit
            stagnation_warning = None
            if iteration >= 2:  # Need at least 2 iterations to detect patterns
                if self.iteration_controller._cost_stagnating(iteration_history, n=min(3, len(iteration_history))):
                    stagnation_warning = "⚠️ STAGNATION DETECTED: Cost has not improved meaningfully in the last 2-3 iterations (<1% average improvement). Consider choosing DONE if you've exhausted optimization ideas."
                elif self.iteration_controller._ineffective_actions(iteration_history, n=min(2, len(iteration_history))):
                    stagnation_warning = "⚠️ INEFFECTIVE ACTIONS: Last 2 actions did not improve performance (cost unchanged or regressed). Consider choosing DONE or trying a fundamentally different approach."

            # STEP 2: PLAN next action using LLM (with iteration history and stagnation warning)
            action = await self._plan_action(
                task=task,
                current_query=current_query,
                feedback=feedback,
                iteration=iteration,
                db_connection_string=db_connection_string,
                executed_ddls=executed_ddls,
                iteration_history=iteration_history,  # Pass stateful context
                constraints=constraints,  # Pass constraints for context
                stagnation_warning=stagnation_warning,  # Pass stagnation detection signal
            )

            actions_taken.append(action)
            print(f"Action: {action.type.value}")
            print(f"Reasoning: {action.reasoning}")

            # STEP 3: Check if optimization is complete
            if action.type == ActionType.DONE:
                solution = Solution(
                    final_query=current_query,
                    actions=actions_taken,
                    success=True,
                    reason="Query optimized successfully",
                    metrics=self._extract_metrics(feedback),
                )
                await self._run_cleanup_queries(task, db_connection_string)
                return solution

            if action.type == ActionType.FAILED:
                solution = Solution(
                    final_query=current_query,
                    actions=actions_taken,
                    success=False,
                    reason=action.reasoning,
                )
                await self._run_cleanup_queries(task, db_connection_string)
                return solution

            # STEP 4: EXECUTE action
            print(f"Executing {action.type.value}...")
            try:
                if action.type == ActionType.CREATE_INDEX:
                    await self._execute_ddl(action.ddl, db_connection_string)
                    executed_ddls.add(self._normalize_ddl(action.ddl))
                elif action.type == ActionType.RUN_ANALYZE:
                    await self._execute_ddl(action.ddl, db_connection_string)
                    executed_ddls.add(self._normalize_ddl(action.ddl))
                elif action.type == ActionType.REWRITE_QUERY:
                    current_query = action.new_query
            except Exception as e:
                error_msg = str(e)
                print(f"Action execution failed: {error_msg}")

                # If DDL already exists, mark it as executed to prevent re-attempts
                if "already exists" in error_msg.lower():
                    if action.type in [ActionType.CREATE_INDEX, ActionType.RUN_ANALYZE]:
                        executed_ddls.add(self._normalize_ddl(action.ddl))
                        print(f"  → Marked as already executed to prevent re-attempts")

                # Continue to next iteration with current state

            # STEP 4.5: TRACK iteration state (Tier 1 enhancement)
            # Track cost delta and outcome to build iteration history
            current_cost = feedback.get("technical_analysis", {}).get("total_cost", 0)

            if previous_cost is not None and action.type not in [ActionType.DONE, ActionType.FAILED]:
                # Compute cost delta
                cost_delta = current_cost - previous_cost
                cost_delta_pct = (cost_delta / previous_cost * 100) if previous_cost > 0 else 0

                # Determine outcome
                if cost_delta < 0:
                    outcome = "improved"
                elif cost_delta > 0:
                    outcome = "regressed"
                else:
                    outcome = "unchanged"

                # Extract insight from feedback
                insight = self._extract_insight(feedback, action, outcome)

                # Record iteration state
                iteration_history.append(IterationState(
                    iteration=iteration + 1,
                    action_type=action.type.value,
                    action_summary=self._summarize_action(action),
                    cost_before=previous_cost,
                    cost_after=current_cost,
                    cost_delta_pct=cost_delta_pct,
                    outcome=outcome,
                    insight=insight
                ))

                print(f"  → Cost delta: {cost_delta_pct:+.1f}% ({outcome})")

            # Update previous cost for next iteration
            previous_cost = current_cost

            # STEP 5: Adaptive stopping - check if we should continue
            timeout_exceeded = (asyncio.get_event_loop().time() - start_time) > self.timeout_seconds
            correctness = feedback.get("correctness")

            should_continue, reason = self.iteration_controller.should_continue(
                iteration=iteration + 1,  # Next iteration number
                feedback=feedback,
                actions=actions_taken,
                correctness=correctness,
                timeout_exceeded=timeout_exceeded,
                iteration_history=iteration_history,  # Pass cost tracking history
            )

            if not should_continue:
                print(f"⏹️  Stopping: {reason}")
                # Determine success based on reason
                success = "Success" in reason
                solution = Solution(
                    final_query=current_query,
                    actions=actions_taken,
                    success=success,
                    reason=reason,
                    metrics=self._extract_metrics(feedback) if success else None,
                )
                # Run cleanup queries before returning
                await self._run_cleanup_queries(task, db_connection_string)
                return solution

        # Should not reach here due to controller, but safety fallback
        solution = Solution(
            final_query=current_query,
            actions=actions_taken,
            success=False,
            reason=f"Max iterations ({self.max_iterations}) reached",
        )
        # Run cleanup queries before returning
        await self._run_cleanup_queries(task, db_connection_string)
        return solution

    async def _run_cleanup_queries(self, task: BIRDCriticTask, db_connection_string: str):
        """
        Run cleanup queries after task completion.

        Args:
            task: BIRD-CRITIC task with potential clean_up_sql
            db_connection_string: PostgreSQL connection string
        """
        if not task.clean_up_sql:
            return

        print(f"\n=== Running {len(task.clean_up_sql)} cleanup queries ===")
        for idx, cleanup_query in enumerate(task.clean_up_sql, 1):
            try:
                await self._execute_ddl(cleanup_query, db_connection_string)
                print(f"  ✓ Cleanup query {idx}/{len(task.clean_up_sql)}")
            except Exception as e:
                print(f"  ⚠️  Cleanup query {idx} failed: {e}")
                # Continue with remaining cleanup

    async def _analyze_query(
        self,
        query: str,
        db_connection_string: str,
        constraints: Dict[str, Any],
        task: Optional[BIRDCriticTask] = None,
    ) -> Dict[str, Any]:
        """
        Analyze query using the exev.py optimization tool.
        Also validates correctness against solution SQL if provided.

        Returns:
            Feedback dictionary with status, reason, suggestion, etc.
        """
        # CRITICAL: Check correctness FIRST (before performance analysis)
        # This prevents agent from accepting low-cost queries that return wrong results
        correctness_check = None
        if task and task.solution_sql:
            correctness_check = self._check_correctness(query, task.solution_sql, db_connection_string)

            # If query is logically wrong, return IMMEDIATE failure (skip performance analysis)
            if not correctness_check["matches"]:
                print(f"⚠️  CORRECTNESS FAILURE: {correctness_check['reason']}")

                return {
                    "success": True,  # Query executed, but results wrong
                    "correctness": correctness_check,
                    "feedback": {
                        "status": "fail",
                        "reason": f"CRITICAL: Query logic error - {correctness_check['reason']}",
                        "suggestion": "REWRITE the query to fix logic error. Check table joins, column references, and WHERE conditions.",
                        "priority": "CRITICAL"
                    },
                    "technical_analysis": {
                        "total_cost": 0,  # Irrelevant when query is wrong
                        "bottlenecks": [],
                        "note": "Performance analysis skipped due to logic error"
                    }
                }

        # Get schema info for semanticizer context
        schema_info = None
        if task:
            combined_query = query
            if task.solution_sql:
                combined_query = query + " " + task.solution_sql
            schema_info = self._get_schema_info(db_connection_string, combined_query, db_id=task.db_id)

        # Perform performance analysis (query is correct or no ground truth available)
        try:
            result = await self.optimization_tool.optimize_query(
                sql_query=query,
                db_connection_string=db_connection_string,
                constraints=constraints,
                schema_info=schema_info,
            )
        except Exception as opt_error:
            error_msg = str(opt_error)

            # Detect aggregate function in WHERE clause error
            if "aggregate functions are not allowed in where" in error_msg.lower():
                print(f"⚠️  AGGREGATE IN WHERE ERROR: {error_msg}")
                return {
                    "success": True,  # Query analyzed (error detected)
                    "feedback": {
                        "status": "fail",
                        "reason": "CRITICAL: Aggregate function error in WHERE clause. This often means: (1) Non-existent column that matches an aggregate function name (e.g., 'count', 'sum'), or (2) Actual aggregate function misplaced in WHERE instead of HAVING.",
                        "suggestion": "REWRITE query: (1) Check if column exists in schema (e.g., budget.count), (2) Use correct column name, or (3) Move aggregate to HAVING clause if actually using aggregation.",
                        "priority": "CRITICAL",
                        "technical_details": error_msg,
                        "bottlenecks": "Column reference error or aggregate misuse",
                        "cost_info": "N/A - query has error"
                    },
                    "technical_analysis": {
                        "total_cost": 0,
                        "bottlenecks": ["SQL syntax/semantic error"],
                        "note": "Performance analysis skipped due to error"
                    }
                }

            # Detect other common errors
            elif "does not exist" in error_msg.lower():
                print(f"⚠️  OBJECT NOT FOUND ERROR: {error_msg}")
                return {
                    "success": True,
                    "feedback": {
                        "status": "fail",
                        "reason": f"CRITICAL: Referenced object does not exist - {error_msg}",
                        "suggestion": "REWRITE query: Check table names, column names, and type names in schema.",
                        "priority": "CRITICAL"
                    },
                    "technical_analysis": {
                        "total_cost": 0,
                        "bottlenecks": ["SQL syntax/semantic error"],
                        "note": "Performance analysis skipped due to error"
                    }
                }

            # Re-raise other errors
            else:
                print(f"⚠️  OPTIMIZATION TOOL ERROR: {error_msg}")
                raise

        # Attach correctness info if available
        if correctness_check:
            result["correctness"] = correctness_check
            print(f"✓ CORRECTNESS: Query returns expected results")

        return result

    def _get_schema_info(self, db_connection_string: str, query: str, db_id: Optional[str] = None) -> str:
        """
        Get database schema information with multiple fallback strategies.

        Priority order:
        1. Load from BIRD-CRITIC JSONL (if db_id provided) - includes CREATE TABLE + sample data
        2. Load from database_description.csv (if available) - BIRD text-to-SQL format
        3. Fallback to information_schema query (basic column names/types)

        Returns formatted schema string for prompt.
        """
        import psycopg2
        import re

        # Strategy 1: Try loading from BIRD-CRITIC JSONL (preferred)
        if db_id:
            schema_from_jsonl = self._load_schema_from_jsonl(db_id)
            if schema_from_jsonl:
                return schema_from_jsonl

            # Strategy 2: Try loading from database_description.csv
            schema_from_csv = self._load_schema_from_csv(db_id, db_connection_string)
            if schema_from_csv:
                return schema_from_csv

        # Strategy 3: Enhanced fallback using pg_catalog for rich schema information
        # Extract table names from query (improved regex)
        table_pattern = r'(?:FROM|JOIN)\s+(\w+)(?:\s+(?:AS\s+)?(\w+))?'
        matches = re.findall(table_pattern, query, re.IGNORECASE)
        tables = set()
        for match in matches:
            # match[0] is the table name, match[1] is the alias (if any)
            if match[0]:
                tables.add(match[0].lower())

        if not tables:
            return "No tables detected in query."

        return self._introspect_live_schema(db_connection_string, tables)

    def _introspect_live_schema(self, db_connection_string: str, tables: set) -> str:
        """
        Introspect live PostgreSQL database schema using pg_catalog.
        
        Provides comprehensive schema information including:
        - Table columns with data types and constraints
        - Primary keys and foreign keys
        - Existing indexes
        - Sample data (3 rows per table)
        - Table statistics (row count estimates)
        
        This follows PostgreSQL best practices using pg_catalog over information_schema
        for richer metadata access.
        
        Args:
            db_connection_string: PostgreSQL connection string
            tables: Set of table names to introspect
        
        Returns:
            Formatted schema string for LLM prompt
        """
        import psycopg2
        from psycopg2.extras import RealDictCursor
        
        schema_sections = []
        
        try:
            with psycopg2.connect(db_connection_string) as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                    for table in sorted(tables):
                        table_info = []
                        table_info.append(f"\nTABLE: {table}")
                        table_info.append("=" * 60)
                        
                        # 1. Get columns with types and constraints
                        cursor.execute("""
                            SELECT 
                                a.attname as column_name,
                                format_type(a.atttypid, a.atttypmod) as data_type,
                                a.attnotnull as not_null,
                                COALESCE(pg_get_expr(d.adbin, d.adrelid), '') as default_value
                            FROM pg_attribute a
                            LEFT JOIN pg_attrdef d ON (a.attrelid, a.attnum) = (d.adrelid, d.adnum)
                            WHERE a.attrelid = %s::regclass
                              AND a.attnum > 0
                              AND NOT a.attisdropped
                            ORDER BY a.attnum
                        """, (table,))
                        
                        columns = cursor.fetchall()
                        if not columns:
                            continue  # Table doesn't exist, skip
                        
                        table_info.append("\nColumns:")
                        for col in columns:
                            constraint = " NOT NULL" if col['not_null'] else ""
                            default = f" DEFAULT {col['default_value']}" if col['default_value'] else ""
                            table_info.append(f"  - {col['column_name']}: {col['data_type']}{constraint}{default}")
                        
                        # 2. Get primary key
                        cursor.execute("""
                            SELECT a.attname
                            FROM pg_index i
                            JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
                            WHERE i.indrelid = %s::regclass AND i.indisprimary
                            ORDER BY array_position(i.indkey, a.attnum)
                        """, (table,))
                        
                        pk_cols = [row['attname'] for row in cursor.fetchall()]
                        if pk_cols:
                            table_info.append(f"\nPrimary Key: ({', '.join(pk_cols)})")
                        
                        # 3. Get foreign keys
                        cursor.execute("""
                            SELECT
                                conname as constraint_name,
                                pg_get_constraintdef(c.oid) as definition
                            FROM pg_constraint c
                            WHERE c.conrelid = %s::regclass
                              AND c.contype = 'f'
                        """, (table,))
                        
                        fks = cursor.fetchall()
                        if fks:
                            table_info.append("\nForeign Keys:")
                            for fk in fks:
                                table_info.append(f"  - {fk['constraint_name']}: {fk['definition']}")
                        
                        # 4. Get indexes
                        cursor.execute("""
                            SELECT
                                i.relname as index_name,
                                pg_get_indexdef(idx.indexrelid) as definition
                            FROM pg_index idx
                            JOIN pg_class i ON i.oid = idx.indexrelid
                            WHERE idx.indrelid = %s::regclass
                              AND NOT idx.indisprimary  -- Exclude PK index
                            ORDER BY i.relname
                        """, (table,))
                        
                        indexes = cursor.fetchall()
                        if indexes:
                            table_info.append("\nIndexes:")
                            for idx in indexes:
                                table_info.append(f"  - {idx['index_name']}: {idx['definition']}")
                        
                        # 5. Get table statistics
                        cursor.execute("""
                            SELECT
                                n_live_tup as row_estimate,
                                last_analyze
                            FROM pg_stat_user_tables
                            WHERE relname = %s
                        """, (table,))
                        
                        stats = cursor.fetchone()
                        if stats and stats['row_estimate']:
                            table_info.append(f"\nEstimated Rows: ~{stats['row_estimate']:,}")
                            if stats['last_analyze']:
                                table_info.append(f"Last ANALYZE: {stats['last_analyze']}")
                        
                        # 6. Get sample data (3 rows)
                        try:
                            cursor.execute(f"SELECT * FROM {table} LIMIT 3")
                            sample_rows = cursor.fetchall()
                            if sample_rows:
                                table_info.append("\nSample Data (first 3 rows):")
                                for i, row in enumerate(sample_rows, 1):
                                    # Format as key-value pairs
                                    row_str = ", ".join([f"{k}={v}" for k, v in row.items()])
                                    table_info.append(f"  Row {i}: {row_str}")
                        except Exception as e:
                            table_info.append(f"  (Sample data unavailable: {e})")
                        
                        schema_sections.append("\n".join(table_info))
                
                return "\n\n".join(schema_sections) if schema_sections else "No schema info available."
        
        except Exception as e:
            return f"Schema introspection error: {e}\n\nFalling back to basic information_schema...\n\n{self._basic_schema_fallback(db_connection_string, tables)}"
    
    def _basic_schema_fallback(self, db_connection_string: str, tables: set) -> str:
        """
        Basic fallback using information_schema if pg_catalog introspection fails.
        """
        import psycopg2
        
        schema_info = []
        try:
            with psycopg2.connect(db_connection_string) as conn:
                with conn.cursor() as cursor:
                    for table in tables:
                        cursor.execute(
                            "SELECT column_name, data_type FROM information_schema.columns "
                            "WHERE table_name = %s ORDER BY ordinal_position",
                            (table,)
                        )
                        columns = cursor.fetchall()
                        if columns:
                            col_list = ", ".join([f"{col[0]} ({col[1]})" for col in columns])
                            schema_info.append(f"{table}: {col_list}")
        except Exception as e:
            return f"Schema fetch error: {e}"
        
        return "\n".join(schema_info) if schema_info else "No schema info available."

    def _load_schema_from_csv(self, db_id: str, db_connection_string: str) -> Optional[str]:
        """
        Load schema from database_description.csv (BIRD text-to-SQL format).

        Format:
        table_name,column_name,data_type,column_description

        Returns formatted schema string with descriptions.
        """
        import csv

        # Try to find database_description.csv
        possible_paths = [
            Path(__file__).parent.parent.parent / "mini_dev" / "database_description" / f"{db_id}.csv",
            Path(__file__).parent.parent.parent / "BIRD-CRITIC-1" / "data" / f"{db_id}_description.csv",
            Path(db_connection_string.split('/')[-1]) / "database_description.csv",  # Database name from connection string
        ]

        for csv_path in possible_paths:
            if not csv_path.exists():
                continue

            try:
                schema_dict = {}
                with open(csv_path, 'r') as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        table_name = row.get('table_name', '')
                        column_name = row.get('column_name', row.get('column', ''))
                        data_type = row.get('data_type', row.get('type', ''))
                        description = row.get('column_description', row.get('description', ''))

                        if table_name not in schema_dict:
                            schema_dict[table_name] = []

                        col_info = f"{column_name} ({data_type})"
                        if description:
                            col_info += f" -- {description}"
                        schema_dict[table_name].append(col_info)

                if schema_dict:
                    # Format as CREATE TABLE style
                    schema_lines = []
                    for table_name, columns in schema_dict.items():
                        schema_lines.append(f"TABLE {table_name}:")
                        for col in columns:
                            schema_lines.append(f"  {col}")
                        schema_lines.append("")

                    return "\n".join(schema_lines)

            except (csv.Error, IOError) as e:
                print(f"Warning: Failed to load CSV schema from {csv_path}: {e}")
                continue

        return None
    
    def _check_correctness(self, query: str, solution_query: str, db_connection_string: str) -> Dict[str, Any]:
        """
        Check if query results match solution query results.
        Returns dict with 'matches' boolean and 'reason' string.
        """
        import psycopg2

        try:
            # Use context manager for automatic cleanup
            with psycopg2.connect(db_connection_string) as conn:
                with conn.cursor() as cursor:
                    # Execute current query
                    try:
                        cursor.execute(query)
                        current_results = cursor.fetchall()
                    except Exception as e:
                        error_msg = str(e)

                        # FIX 1: Detect aggregate function in WHERE clause error
                        # This error occurs during query execution, before feedback analysis
                        if "aggregate functions are not allowed in where" in error_msg.lower():
                            return {
                                "matches": False,
                                "reason": "CRITICAL: Aggregate function used in WHERE clause. SQL requires HAVING for aggregate filters, or correct CTE/subquery column references. Move aggregate condition to HAVING clause, or if comparing columns from CTE/subquery, ensure table.column references are correct (not using aggregate functions directly in WHERE). Technical details: " + error_msg
                            }

                        return {"matches": False, "reason": f"Query execution error: {error_msg}"}

                    # Execute solution query
                    try:
                        cursor.execute(solution_query)
                        expected_results = cursor.fetchall()
                    except Exception as e:
                        return {"matches": False, "reason": f"Solution query error: {e}"}

                    # Compare results
                    if len(current_results) != len(expected_results):
                        return {
                            "matches": False,
                            "reason": f"Row count mismatch: got {len(current_results)}, expected {len(expected_results)}"
                        }

                    # Sort and compare (simple approach)
                    current_sorted = sorted([tuple(row) for row in current_results])
                    expected_sorted = sorted([tuple(row) for row in expected_results])

                    if current_sorted != expected_sorted:
                        return {
                            "matches": False,
                            "reason": "Result values don't match expected output"
                        }

                    return {"matches": True, "reason": "Results match expected output"}

        except Exception as e:
            return {"matches": False, "reason": f"Validation error: {e}"}

    async def _plan_action(
        self,
        task: BIRDCriticTask,
        current_query: str,
        feedback: Dict[str, Any],
        iteration: int,
        db_connection_string: str = None,
        executed_ddls: Set[str] = None,
        iteration_history: Optional[List[IterationState]] = None,
        constraints: Optional[Dict[str, Any]] = None,
        stagnation_warning: Optional[str] = None,
    ) -> Action:
        """
        Use Claude to decide the next optimization action.

        Uses extended thinking mode for complex reasoning.

        Returns:
            Action to take next
        """
        if executed_ddls is None:
            executed_ddls = set()
        if iteration_history is None:
            iteration_history = []
        if constraints is None:
            constraints = {}
        prompt = self._build_planning_prompt(task, current_query, feedback, iteration, db_connection_string, executed_ddls, iteration_history, constraints, stagnation_warning)

        # Configure extended thinking if enabled
        extra_params = {}
        if self.use_extended_thinking:
            extra_params["thinking"] = {
                "type": "enabled",
                "budget_tokens": self.thinking_budget,
            }

        try:
            response = self.anthropic_client.messages.create(
                model=self.planner_model,
                max_tokens=8192,  # Must be greater than thinking budget
                temperature=1.0 if self.use_extended_thinking else 0.0,  # Temperature must be 1 when thinking is enabled
                system=self._get_system_prompt(),
                messages=[{"role": "user", "content": prompt}],
                **extra_params,
            )

            # Extract text response: join only text blocks, ignore thinking/tool blocks
            text_parts: List[str] = []
            for block in getattr(response, "content", []) or []:
                # SDK may return objects with attributes or dicts
                btype = getattr(block, "type", None)
                if btype is None and isinstance(block, dict):
                    btype = block.get("type")
                if btype == "text":
                    btext = getattr(block, "text", None)
                    if btext is None and isinstance(block, dict):
                        btext = block.get("text")
                    if btext:
                        text_parts.append(btext)

            response_text = "\n".join(text_parts).strip()
            if not response_text:
                raise ValueError("No text blocks in LLM response (thinking blocks present?)")

            # Parse into Action object
            action = parse_action_from_llm_response(response_text)
            return action

        except Exception as e:
            err = str(e)
            # Provide friendly, actionable error messages
            if ("Error code: 401" in err) and ("authentication_error" in err or "invalid x-api-key" in err.lower()):
                friendly = "Authentication Error: Invalid API key. Please check your ANTHROPIC_API_KEY environment variable and ensure the key is valid and active."
                print(f"Planning failed: {friendly}")
                return Action(
                    type=ActionType.FAILED,
                    reasoning=friendly,
                )
            elif ("Error code: 429" in err) or ("rate limit" in err.lower()):
                friendly = "Rate Limit Error: Too many requests to Anthropic. Please wait a moment and try again."
                print(f"Planning failed: {friendly}")
                return Action(
                    type=ActionType.FAILED,
                    reasoning=friendly,
                )
            elif "Error code: 500" in err:
                friendly = "Service Error: Anthropic API issue. Please try again in a few minutes."
                print(f"Planning failed: {friendly}")
                return Action(
                    type=ActionType.FAILED,
                    reasoning=friendly,
                )
            else:
                print(f"Planning failed: {e}")
                # Fallback: terminate on error
                return Action(
                    type=ActionType.FAILED,
                    reasoning=f"Planning error: {str(e)}",
                )

    def _build_planning_prompt(
        self,
        task: BIRDCriticTask,
        current_query: str,
        feedback: Dict[str, Any],
        iteration: int,
        db_connection_string: str = None,
        executed_ddls: Set[str] = None,
        iteration_history: Optional[List[IterationState]] = None,
        constraints: Optional[Dict[str, Any]] = None,
        stagnation_warning: Optional[str] = None,
    ) -> str:
        """
        Build the planning prompt for Claude.

        Provides context about the task, current state, and feedback.
        """
        if executed_ddls is None:
            executed_ddls = set()
        if iteration_history is None:
            iteration_history = []
        if constraints is None:
            constraints = {}
        fb = feedback.get("feedback", {})
        tech = feedback.get("technical_analysis", {})

        # Get schema information for query rewriting (with BIRD JSONL priority)
        schema_info = ""
        if db_connection_string:
            # Include tables from both current and solution queries
            combined_query = current_query
            if task.solution_sql:
                combined_query = current_query + " " + task.solution_sql
            # Pass db_id to enable JSONL schema loading
            schema_info = self._get_schema_info(db_connection_string, combined_query, db_id=task.db_id)

        # Format iteration history (Tier 1 enhancement)
        history_section = self._format_iteration_history(iteration_history)

        return f"""You are an autonomous database optimizer analyzing query performance.

TASK CONTEXT:
- Task ID: {task.task_id}
- Database: {task.db_id}
- User Query: {task.user_query}
- Efficiency Optimization Required: {task.efficiency}

CURRENT QUERY:
```sql
{current_query}
```

DATABASE SCHEMA (with sample data and constraints):
{schema_info}

CRITICAL: The schema above shows:
- Exact table and column names (use these EXACTLY as shown)
- Data types and constraints
- Sample rows with actual values (verify your logic against these)
- Foreign key relationships (use for correct joins)

PERFORMANCE FEEDBACK (Iteration {iteration + 1}):
Status: {fb.get('status', 'unknown')}
Reason: {fb.get('reason', 'N/A')}
Suggestion: {fb.get('suggestion', 'N/A')}
Priority: {fb.get('priority', 'N/A')}

TECHNICAL DETAILS:
Total Cost: {tech.get('total_cost', 'N/A')}
Bottlenecks Found: {len(tech.get('bottlenecks', []))}
{self._format_bottlenecks(tech.get('bottlenecks', []))}

{self._format_cost_analysis(tech.get('total_cost', 0), constraints.get('max_cost', 0), iteration_history)}

{history_section}

{self._format_action_summary(iteration_history)}

ALREADY EXECUTED DDL STATEMENTS:
{self._format_executed_ddls(executed_ddls)}

{stagnation_warning if stagnation_warning else ''}

YOUR TASK:
Decide the next action to optimize this query. You have the following options:

1. CREATE_INDEX - Execute index creation DDL
   Use when: Feedback suggests an index, and it's likely to help

2. REWRITE_QUERY - Modify the query structure
   Use when: Query logic can be improved (avoid SELECT *, better joins, etc.)
   CRITICAL: Only use column names from the SCHEMA INFORMATION above. Do not invent columns.

3. RUN_ANALYZE - Update table statistics
   Use when: Planner estimates are severely wrong

4. DONE - Optimization complete
   Use when ANY of these conditions are met:
   - Status is "pass" (performance meets constraints)
   - Cost has plateaued (<1% improvement in last 2-3 iterations) AND you've tried obvious optimizations
   - Query is "good enough" (cost within 2x of max_cost AND no more optimization ideas)
   - Cannot optimize further (tried all reasonable indexes/rewrites/analyze)

5. FAILED - Cannot optimize further (with explanation)
   Use when:
   - Task is fundamentally unsolvable (query logic cannot be improved)
   - Errors prevent progress (syntax errors, permission issues)
   - Cost is extremely high (>10x max_cost) with no viable optimization path
   Note: Prefer DONE over FAILED when optimization has plateaued but made some progress

RESPONSE FORMAT (JSON only):
{{
    "action": "CREATE_INDEX" | "REWRITE_QUERY" | "RUN_ANALYZE" | "DONE" | "FAILED",
    "reasoning": "Clear explanation of why this action is chosen",
    "ddl": "CREATE INDEX idx_name ON table(col);" // if CREATE_INDEX or RUN_ANALYZE
    "new_query": "SELECT ..." // if REWRITE_QUERY
    "confidence": 0.95 // 0.0-1.0
}}

POSTGRESQL UPDATE...RETURNING LIMITATIONS:
- CRITICAL: Cannot use explicit JOIN in FROM clause when RETURNING references the joined table
- This will cause: "invalid reference to FROM-clause entry"
- Solutions:
  1. Use CTE pattern:
     WITH updated AS (
         UPDATE table SET col = val
         WHERE condition
         RETURNING col1, col2, ...
     )
     SELECT u.col1, other.col2
     FROM updated u
     JOIN other_table other ON u.id = other.id;

  2. Use subquery in RETURNING (for single column):
     UPDATE table SET col = val
     WHERE condition
     RETURNING col1, (SELECT other_col FROM other_table WHERE id = table.id);

CRITICAL DECISION RULES (Priority Order):
1. **CORRECTNESS FIRST**: If priority="CRITICAL" or reason mentions "logic error" or "incorrect results":
   → ALWAYS choose REWRITE_QUERY to fix logic before optimizing performance
   → Never create indexes when the query is logically wrong!

2. **Know when to stop**: Choose DONE when:
   - Status is "pass" (performance meets constraints) AND query is correct
   - OR cost has plateaued (<1% improvement in 2-3 iterations) AND you've tried obvious optimizations
   - OR query is "good enough" (reasonable performance, no more ideas)
   - Don't wait indefinitely for "pass" status if you've made meaningful progress but hit optimization limits

3. **Prefer indexes over rewrites** (when logic is correct):
   - If feedback suggests CREATE INDEX, try that first
   - Only rewrite for performance if indexes don't help

4. **Don't repeat executed DDL**:
   - Check "ALREADY EXECUTED DDL STATEMENTS" section above
   - If an index/analyze has already been executed, choose a different action
   - If feedback suggests creating an index that already exists, consider DONE or try a different optimization

5. **Detect when indexes aren't being used**:
   - If you created indexes but still see sequential scans on the same table:
     → Indexes may not be selective enough (too many matching rows)
     → PostgreSQL planner is choosing seq scan because it's actually faster
     → REWRITE the query to reduce selectivity (add more filters, use LIMIT, etc.)
     → Or choose FAILED with explanation: "Indexes created but not used by planner. Query needs rewrite or selectivity improvement."
   - If ANALYZE has been run multiple times but cost unchanged:
     → Statistics are up-to-date, problem is elsewhere
     → Try REWRITE_QUERY instead

6. **Avoid infinite loops**:
   - If you've tried the same action 2+ times without cost improvement, choose FAILED or REWRITE
   - If iteration > 3 and cost delta is <1% per iteration, choose FAILED with helpful message
   - Example FAILED reasoning: "Created indexes on customer_id, order_date, status but planner still chooses seq scan. This indicates the query matches too many rows (low selectivity). Recommend adding additional WHERE filters or using LIMIT to reduce result set size."

7. **Schema validation**:
   - ONLY use table/column names from the schema above
   - Verify all joins use correct foreign keys from schema

8. **Output format**:
   - Respond with ONLY valid JSON, no other text

Analyze the feedback and decide the best next action:"""

    def _get_system_prompt(self) -> str:
        """System prompt defining the agent's role and constraints."""
        return """You are an expert PostgreSQL database optimizer agent. Your goal is to autonomously optimize SQL queries through iterative analysis and action.

You have access to detailed performance feedback from EXPLAIN ANALYZE and must make strategic decisions about:
- When to create indexes
- When to rewrite queries
- When optimization is complete
- When a task is unsolvable

You must respond with valid JSON only. Your decisions should be conservative, evidence-based, and prioritize correctness over aggressive optimization.

Key principles:
1. Trust the performance feedback metrics
2. Prefer simple solutions (indexes) over complex rewrites
3. Validate that each action addresses the identified bottleneck
4. Know when to stop (diminishing returns, constraints met)
5. Be honest about limitations (FAILED is acceptable)"""

    def _format_action_summary(self, iteration_history: List[IterationState]) -> str:
        """
        Format summary of actions tried so far to help detect exhaustion.

        Shows:
        - Which action types have been attempted
        - How many times each type was used
        - Whether we've tried all major optimization categories
        """
        if not iteration_history:
            return ""

        # Count action types
        action_counts = {}
        for state in iteration_history:
            action_type = state.action_type
            action_counts[action_type] = action_counts.get(action_type, 0) + 1

        # Format summary
        lines = []
        lines.append("OPTIMIZATION ATTEMPTS SO FAR:")
        for action_type, count in sorted(action_counts.items()):
            plural = "s" if count > 1 else ""
            lines.append(f"  • {action_type}: {count} time{plural}")

        # Check for exhaustion signals
        has_index = "CREATE_INDEX" in action_counts
        has_rewrite = "REWRITE_QUERY" in action_counts
        has_analyze = "RUN_ANALYZE" in action_counts

        exhaustion_note = ""
        if has_index and has_rewrite and has_analyze:
            exhaustion_note = "\n  💡 NOTE: You've tried all major optimization types (indexes, rewrites, ANALYZE). If cost is still not improving, consider choosing DONE."
        elif len(action_counts) >= 2 and len(iteration_history) >= 4:
            exhaustion_note = "\n  💡 NOTE: Multiple optimization attempts have been made. If cost plateaus, consider choosing DONE."

        return "\n".join(lines) + exhaustion_note

    def _format_cost_analysis(self, current_cost: float, max_cost: float, iteration_history: List[IterationState]) -> str:
        """
        Format cost analysis showing constraints, progress, and stopping guidance.

        Returns formatted string with:
        - Max cost threshold
        - Current vs target ratio
        - Total improvement from start
        - "Good enough" assessment
        """
        if not current_cost or not max_cost:
            return "Cost constraints: Not available"

        # Calculate cost ratio
        cost_ratio = current_cost / max_cost

        # Determine cost status
        if cost_ratio <= 1.0:
            status_emoji = "✅"
            status_msg = "MEETS constraints (status='pass')"
        elif cost_ratio <= 2.0:
            status_emoji = "⚠️"
            status_msg = "CLOSE to target (within 2x)"
        else:
            status_emoji = "❌"
            status_msg = f"EXCEEDS target ({cost_ratio:.1f}x over)"

        # Calculate total improvement from start
        improvement_msg = ""
        if iteration_history and len(iteration_history) > 0:
            first_cost = iteration_history[0].cost_before
            total_improvement = ((first_cost - current_cost) / first_cost * 100) if first_cost > 0 else 0
            improvement_msg = f"\nTotal Improvement from Start: {total_improvement:+.1f}%"

        # "Good enough" assessment
        good_enough_msg = ""
        if cost_ratio <= 2.0 and iteration_history and len(iteration_history) >= 2:
            # Check if plateaued
            recent_improvements = [state.cost_delta_pct for state in iteration_history[-2:]]
            avg_recent = sum(recent_improvements) / len(recent_improvements) if recent_improvements else 0
            if abs(avg_recent) < 1.0:
                good_enough_msg = "\n\n💡 OPTIMIZATION TIP: Cost is plateauing and within 2x of target. Consider choosing DONE."

        return f"""PERFORMANCE CONSTRAINTS:
Max Acceptable Cost: {max_cost:.2f}
Current Cost: {current_cost:.2f} ({cost_ratio:.2f}x of max)
Status: {status_emoji} {status_msg}{improvement_msg}{good_enough_msg}"""

    def _format_bottlenecks(self, bottlenecks: List[Dict]) -> str:
        """Format bottleneck information for the prompt."""
        if not bottlenecks:
            return "No bottlenecks detected."

        lines = []
        for i, bn in enumerate(bottlenecks[:3], 1):  # Top 3 bottlenecks
            node_type = bn.get("node_type", "Unknown")
            table = bn.get("table", "N/A")
            rows = bn.get("rows", "N/A")
            severity = bn.get("severity", "N/A")
            lines.append(f"  {i}. {node_type} on '{table}' ({rows} rows, {severity})")

        return "\n".join(lines)

    def _normalize_ddl(self, ddl: str) -> str:
        """
        Normalize DDL to detect duplicates.
        Extracts index name or table name for comparison.
        """
        # Extract index name from CREATE INDEX statements
        idx_match = re.search(r'CREATE\s+INDEX\s+(\w+)', ddl, re.IGNORECASE)
        if idx_match:
            return f"INDEX:{idx_match.group(1).lower()}"

        # Extract table name from ANALYZE statements
        analyze_match = re.search(r'ANALYZE\s+(\w+)', ddl, re.IGNORECASE)
        if analyze_match:
            return f"ANALYZE:{analyze_match.group(1).lower()}"

        # Fallback: use first 100 chars of lowercased DDL
        return ddl[:100].lower()

    def _format_executed_ddls(self, executed_ddls: Set[str]) -> str:
        """Format executed DDL list for the prompt."""
        if not executed_ddls:
            return "None - this is the first action"

        lines = []
        for ddl in sorted(executed_ddls):
            lines.append(f"  - {ddl}")

        return "\n".join(lines) + "\n\n⚠️ DO NOT repeat any of the above DDL operations!"

    async def _execute_ddl(self, ddl: str, db_connection_string: str):
        """
        Execute DDL statement (CREATE INDEX, ANALYZE, etc.).

        Runs in a thread pool to avoid blocking.
        """
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._execute_ddl_sync, ddl, db_connection_string)

    def _execute_ddl_sync(self, ddl: str, db_connection_string: str):
        """Synchronous DDL execution."""
        import psycopg2

        # Use context manager for automatic cleanup
        with psycopg2.connect(db_connection_string) as conn:
            conn.autocommit = True
            with conn.cursor() as cursor:
                cursor.execute(ddl)
                print(f"✓ Executed: {ddl[:60]}...")

    def _extract_metrics(self, feedback: Dict[str, Any]) -> Dict[str, Any]:
        """Extract key performance metrics from feedback."""
        tech = feedback.get("technical_analysis", {})
        return {
            "total_cost": tech.get("total_cost"),
            "execution_time_ms": tech.get("execution_time_ms"),
            "bottlenecks_found": len(tech.get("bottlenecks", [])),
        }

    def _format_iteration_history(self, history: List[IterationState], keep_last_n: int = 2) -> str:
        """
        Format iteration history in a compact, token-efficient way.

        Uses Strategy 1 from stateful design: Keep last N iterations with symbols.
        Token overhead: ~50-100 tokens vs 500+ for full context.

        Args:
            history: List of iteration states
            keep_last_n: Number of recent iterations to include

        Returns:
            Formatted history string or empty section if no history
        """
        if not history:
            return ""

        # Keep only recent iterations
        recent = history[-keep_last_n:] if len(history) > keep_last_n else history

        lines = ["ITERATION HISTORY (Last {} actions):".format(len(recent))]

        for state in recent:
            # Choose symbol based on outcome
            if state.outcome == "improved":
                symbol = "✓"
            elif state.outcome == "regressed":
                symbol = "✗"
            else:
                symbol = "→"

            # One-line summary
            line = (
                f"{symbol} Iter {state.iteration}: {state.action_type} "
                f"({state.action_summary}) → "
                f"Cost {state.cost_delta_pct:+.1f}%"
            )

            # Add insight if critical (regression or no improvement)
            if state.outcome in ["regressed", "unchanged"] and state.insight:
                line += f"\n  ⚠ {state.insight}"

            lines.append(line)

        # Add learning instructions
        lines.append("")
        lines.append("CRITICAL LEARNING FROM HISTORY:")
        lines.append("- If previous action REGRESSED (✗), DO NOT repeat similar action")
        lines.append("- If previous action improved but status still FAIL, try different approach")
        lines.append("- If index was created but not used, suggest ANALYZE or query rewrite")
        lines.append("- Learn from patterns: What worked? What didn't?")

        return "\n".join(lines)

    def _summarize_action(self, action: Action) -> str:
        """
        Extract compact action summary for iteration history.

        Examples:
        - CREATE INDEX idx_users_email... → "idx_users_email"
        - REWRITE_QUERY → "query"
        - ANALYZE users; → "users"

        Args:
            action: The action taken

        Returns:
            Short summary string (1-3 words)
        """
        if action.type == ActionType.CREATE_INDEX:
            # Extract index name from DDL
            if action.ddl:
                match = re.search(r'CREATE INDEX (\w+)', action.ddl, re.IGNORECASE)
                return match.group(1) if match else "index"
            return "index"

        elif action.type == ActionType.REWRITE_QUERY:
            return "query"

        elif action.type == ActionType.RUN_ANALYZE:
            # Extract table name from DDL
            if action.ddl:
                match = re.search(r'ANALYZE (\w+)', action.ddl, re.IGNORECASE)
                return match.group(1) if match else "table"
            return "table"

        return action.type.value

    def _extract_insight(self, feedback: Dict[str, Any], action: Action, outcome: str) -> str:
        """
        Extract 1-sentence insight from feedback about why action succeeded/failed.

        Args:
            feedback: Feedback from analyze_query
            action: The action that was taken
            outcome: "improved" | "regressed" | "unchanged"

        Returns:
            Short insight string (1 sentence)
        """
        if outcome == "regressed":
            # Check if index exists but unused
            bottlenecks = feedback.get("technical_analysis", {}).get("bottlenecks", [])
            for bn in bottlenecks:
                node_type = bn.get("node_type", "")
                if "Seq Scan" in node_type and action.type == ActionType.CREATE_INDEX:
                    return "Index created but not used by planner"

            return "Action increased query cost"

        elif outcome == "unchanged":
            return "No measurable performance change"

        # Improved - no special insight needed
        return ""


# Example usage
async def demo_agent():
    """
    Demo: Autonomous optimization of a sample query.
    """
    task = BIRDCriticTask(
        task_id="demo_001",
        db_id="test_db",
        buggy_sql="SELECT * FROM users WHERE email = 'alice@example.com'",
        user_query="Find user by email",
        efficiency=True,
    )

    agent = SQLOptimizationAgent(
        max_iterations=3,
        timeout_per_task_seconds=60,
        use_extended_thinking=True,
    )

    db_conn = os.environ.get("DB_CONNECTION", "postgresql://localhost/testdb")

    print("=== Autonomous SQL Optimization Demo ===\n")
    solution = await agent.solve_task(task, db_conn)

    print("\n=== FINAL SOLUTION ===")
    print(f"Success: {solution.success}")
    print(f"Reason: {solution.reason}")
    print(f"Iterations: {solution.total_iterations()}")
    print(f"Final Query: {solution.final_query}")
    print(f"\nActions Taken:")
    for i, action in enumerate(solution.actions, 1):
        print(f"  {i}. {action.type.value}: {action.reasoning}")


if __name__ == "__main__":
    asyncio.run(demo_agent())
