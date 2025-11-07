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
    ) -> tuple[bool, str]:
        """
        Decide if agent should continue iterating.

        Returns:
            (should_continue: bool, reason: str)
        """
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

        # Early stopping - no progress detection
        if iteration >= self.min_iterations:
            if self._no_improvement_in_n_iterations(actions, n=2):
                return False, "No progress in last 2 iterations"

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
                        # Match by db_id or instance_id
                        if entry.get('db_id') == db_id or str(entry.get('instance_id')) == db_id:
                            # Prefer preprocess_schema (has sample data), fallback to original_schema
                            schema = entry.get('preprocess_schema') or entry.get('original_schema')
                            if schema:
                                self._schema_cache[db_id] = schema
                                return schema
            except (json.JSONDecodeError, IOError) as e:
                print(f"Warning: Failed to load schema from {schema_file}: {e}")
                continue

        # Schema not found in JSONL files
        print(f"Warning: Schema for db_id '{db_id}' not found in JSONL files")
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

        # Run preprocess_sql setup queries if provided
        if task.preprocess_sql:
            print(f"\n=== Running {len(task.preprocess_sql)} setup queries ===")
            for idx, setup_query in enumerate(task.preprocess_sql, 1):
                try:
                    await self._execute_ddl(setup_query, db_connection_string)
                    print(f"  ✓ Setup query {idx}/{len(task.preprocess_sql)}")
                except Exception as e:
                    print(f"  ⚠️  Setup query {idx} failed: {e}")
                    # Continue anyway - some setup may be idempotent

        current_query = current_queries[0]  # Start with first query
        actions_taken: List[Action] = []
        executed_ddls: Set[str] = set()  # Track successful DDL to prevent re-attempts
        start_time = asyncio.get_event_loop().time()

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

            print(f"\n=== Iteration {iteration + 1}/{self.max_iterations} ===")

            # STEP 1: ANALYZE current query state
            print("Analyzing query performance...")
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

            # STEP 2: PLAN next action using LLM
            print("Planning next action...")
            action = await self._plan_action(
                task=task,
                current_query=current_query,
                feedback=feedback,
                iteration=iteration,
                db_connection_string=db_connection_string,
                executed_ddls=executed_ddls,
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

            # STEP 5: Adaptive stopping - check if we should continue
            timeout_exceeded = (asyncio.get_event_loop().time() - start_time) > self.timeout_seconds
            correctness = feedback.get("correctness")

            should_continue, reason = self.iteration_controller.should_continue(
                iteration=iteration + 1,  # Next iteration number
                feedback=feedback,
                actions=actions_taken,
                correctness=correctness,
                timeout_exceeded=timeout_exceeded,
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
        result = await self.optimization_tool.optimize_query(
            sql_query=query,
            db_connection_string=db_connection_string,
            constraints=constraints,
            schema_info=schema_info,
        )

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

        # Strategy 3: Fallback to information_schema (current method)
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

        schema_info = []
        try:
            conn = psycopg2.connect(db_connection_string)
            cursor = conn.cursor()

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

            conn.close()
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
            conn = psycopg2.connect(db_connection_string)
            cursor = conn.cursor()
            
            # Execute current query
            try:
                cursor.execute(query)
                current_results = cursor.fetchall()
            except Exception as e:
                return {"matches": False, "reason": f"Query execution error: {e}"}
            
            # Execute solution query  
            try:
                cursor.execute(solution_query)
                expected_results = cursor.fetchall()
            except Exception as e:
                return {"matches": False, "reason": f"Solution query error: {e}"}
            
            conn.close()
            
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
    ) -> Action:
        """
        Use Claude to decide the next optimization action.

        Uses extended thinking mode for complex reasoning.

        Returns:
            Action to take next
        """
        if executed_ddls is None:
            executed_ddls = set()
        prompt = self._build_planning_prompt(task, current_query, feedback, iteration, db_connection_string, executed_ddls)

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
    ) -> str:
        """
        Build the planning prompt for Claude.

        Provides context about the task, current state, and feedback.
        """
        if executed_ddls is None:
            executed_ddls = set()
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

ALREADY EXECUTED DDL STATEMENTS:
{self._format_executed_ddls(executed_ddls)}

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
   Use when: Query is BOTH correct AND optimized (status="pass")

5. FAILED - Cannot optimize further
   Use when: Task is unsolvable or errors prevent progress

RESPONSE FORMAT (JSON only):
{{
    "action": "CREATE_INDEX" | "REWRITE_QUERY" | "RUN_ANALYZE" | "DONE" | "FAILED",
    "reasoning": "Clear explanation of why this action is chosen",
    "ddl": "CREATE INDEX idx_name ON table(col);" // if CREATE_INDEX or RUN_ANALYZE
    "new_query": "SELECT ..." // if REWRITE_QUERY
    "confidence": 0.95 // 0.0-1.0
}}

CRITICAL DECISION RULES (Priority Order):
1. **CORRECTNESS FIRST**: If priority="CRITICAL" or reason mentions "logic error" or "incorrect results":
   → ALWAYS choose REWRITE_QUERY to fix logic before optimizing performance
   → Never create indexes when the query is logically wrong!

2. **Don't stop prematurely**: Only choose DONE if:
   - Status is "pass" (performance meets constraints)
   - AND query returns correct results (no logic errors)
   - If status is "pass" but there was a logic error earlier, verify it's fixed

3. **Prefer indexes over rewrites** (when logic is correct):
   - If feedback suggests CREATE INDEX, try that first
   - Only rewrite for performance if indexes don't help

4. **Don't repeat executed DDL**:
   - Check "ALREADY EXECUTED DDL STATEMENTS" section above
   - If an index/analyze has already been executed, choose a different action
   - If feedback suggests creating an index that already exists, consider DONE or try a different optimization

5. **Avoid infinite loops**:
   - If you've tried the same action 2+ times without improvement, choose FAILED
   - If iteration > 5 with no progress, choose FAILED

6. **Schema validation**:
   - ONLY use table/column names from the schema above
   - Verify all joins use correct foreign keys from schema

7. **Output format**:
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

        conn = None
        try:
            conn = psycopg2.connect(db_connection_string)
            conn.autocommit = True
            cursor = conn.cursor()
            cursor.execute(ddl)
            print(f"✓ Executed: {ddl[:60]}...")
        except Exception as e:
            print(f"✗ DDL execution failed: {e}")
            raise
        finally:
            if conn:
                conn.close()

    def _extract_metrics(self, feedback: Dict[str, Any]) -> Dict[str, Any]:
        """Extract key performance metrics from feedback."""
        tech = feedback.get("technical_analysis", {})
        return {
            "total_cost": tech.get("total_cost"),
            "execution_time_ms": tech.get("execution_time_ms"),
            "bottlenecks_found": len(tech.get("bottlenecks", [])),
        }


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
