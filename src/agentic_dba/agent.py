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
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Dict, Any, List
import anthropic

from .actions import Action, ActionType, Solution, parse_action_from_llm_response
from .mcp_server import QueryOptimizationTool


@dataclass
class BIRDCriticTask:
    """
    Represents a single BIRD-CRITIC task.

    Attributes:
        task_id: Unique identifier
        db_id: Database name
        buggy_sql: Original query with performance issues
        user_query: Natural language description
        solution_sql: Ground truth solution (for evaluation)
        efficiency: Whether this task requires optimization
    """

    task_id: str
    db_id: str
    buggy_sql: str
    user_query: str
    solution_sql: Optional[str] = None
    efficiency: bool = False


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
        max_iterations: int = 5,
        timeout_per_task_seconds: int = 120,
        use_extended_thinking: bool = True,
        extended_thinking_budget: int = 8000,
    ):
        """
        Initialize the autonomous agent.

        Args:
            max_iterations: Maximum optimization attempts per task
            timeout_per_task_seconds: Total timeout for one task
            use_extended_thinking: Enable Claude's extended thinking mode
            extended_thinking_budget: Token budget for thinking (1024-64000)
        """
        self.max_iterations = max_iterations
        self.timeout_seconds = timeout_per_task_seconds
        self.use_extended_thinking = use_extended_thinking
        self.thinking_budget = extended_thinking_budget

        # Initialize tools
        self.optimization_tool = QueryOptimizationTool(use_mock_translator=False)
        self.anthropic_client = anthropic.Anthropic(
            api_key=os.environ.get("ANTHROPIC_API_KEY")
        )

        # Model configuration
        self.planner_model = "claude-sonnet-4-5-20250929"  # Latest Sonnet 4.5

    async def solve_task(
        self,
        task: BIRDCriticTask,
        db_connection_string: str,
        constraints: Optional[Dict[str, Any]] = None,
    ) -> Solution:
        """
        Autonomously optimize a SQL query.

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

        current_query = task.buggy_sql
        actions_taken: List[Action] = []
        start_time = asyncio.get_event_loop().time()

        for iteration in range(self.max_iterations):
            # Check timeout
            elapsed = asyncio.get_event_loop().time() - start_time
            if elapsed > self.timeout_seconds:
                return Solution(
                    final_query=current_query,
                    actions=actions_taken,
                    success=False,
                    reason=f"Timeout after {elapsed:.1f}s",
                )

            print(f"\n=== Iteration {iteration + 1}/{self.max_iterations} ===")

            # STEP 1: ANALYZE current query state
            print("Analyzing query performance...")
            feedback = await self._analyze_query(
                current_query, db_connection_string, constraints
            )

            if not feedback.get("success", False):
                # Query execution failed
                return Solution(
                    final_query=current_query,
                    actions=actions_taken,
                    success=False,
                    reason=f"Query analysis failed: {feedback.get('error', 'Unknown error')}",
                )

            # STEP 2: PLAN next action using LLM
            print("Planning next action...")
            action = await self._plan_action(
                task=task,
                current_query=current_query,
                feedback=feedback,
                iteration=iteration,
            )

            actions_taken.append(action)
            print(f"Action: {action.type.value}")
            print(f"Reasoning: {action.reasoning}")

            # STEP 3: Check if optimization is complete
            if action.type == ActionType.DONE:
                return Solution(
                    final_query=current_query,
                    actions=actions_taken,
                    success=True,
                    reason="Query optimized successfully",
                    metrics=self._extract_metrics(feedback),
                )

            if action.type == ActionType.FAILED:
                return Solution(
                    final_query=current_query,
                    actions=actions_taken,
                    success=False,
                    reason=action.reasoning,
                )

            # STEP 4: EXECUTE action
            print(f"Executing {action.type.value}...")
            try:
                if action.type == ActionType.CREATE_INDEX:
                    await self._execute_ddl(action.ddl, db_connection_string)
                elif action.type == ActionType.RUN_ANALYZE:
                    await self._execute_ddl(action.ddl, db_connection_string)
                elif action.type == ActionType.REWRITE_QUERY:
                    current_query = action.new_query
            except Exception as e:
                print(f"Action execution failed: {e}")
                # Continue to next iteration with current state

        # Max iterations reached without success
        return Solution(
            final_query=current_query,
            actions=actions_taken,
            success=False,
            reason=f"Max iterations ({self.max_iterations}) reached",
        )

    async def _analyze_query(
        self,
        query: str,
        db_connection_string: str,
        constraints: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Analyze query using the exev.py optimization tool.

        Returns:
            Feedback dictionary with status, reason, suggestion, etc.
        """
        result = await self.optimization_tool.optimize_query(
            sql_query=query,
            db_connection_string=db_connection_string,
            constraints=constraints,
        )
        return result

    async def _plan_action(
        self,
        task: BIRDCriticTask,
        current_query: str,
        feedback: Dict[str, Any],
        iteration: int,
    ) -> Action:
        """
        Use Claude to decide the next optimization action.

        Uses extended thinking mode for complex reasoning.

        Returns:
            Action to take next
        """
        prompt = self._build_planning_prompt(task, current_query, feedback, iteration)

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
                max_tokens=4096,
                temperature=0.0,  # Deterministic for consistency
                system=self._get_system_prompt(),
                messages=[{"role": "user", "content": prompt}],
                **extra_params,
            )

            # Extract text response
            response_text = response.content[0].text

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
    ) -> str:
        """
        Build the planning prompt for Claude.

        Provides context about the task, current state, and feedback.
        """
        fb = feedback.get("feedback", {})
        tech = feedback.get("technical_analysis", {})

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

PERFORMANCE FEEDBACK (Iteration {iteration + 1}):
Status: {fb.get('status', 'unknown')}
Reason: {fb.get('reason', 'N/A')}
Suggestion: {fb.get('suggestion', 'N/A')}
Priority: {fb.get('priority', 'N/A')}

TECHNICAL DETAILS:
Total Cost: {tech.get('total_cost', 'N/A')}
Bottlenecks Found: {len(tech.get('bottlenecks', []))}
{self._format_bottlenecks(tech.get('bottlenecks', []))}

YOUR TASK:
Decide the next action to optimize this query. You have the following options:

1. CREATE_INDEX - Execute index creation DDL
   Use when: Feedback suggests an index, and it's likely to help

2. REWRITE_QUERY - Modify the query structure
   Use when: Query logic can be improved (avoid SELECT *, better joins, etc.)

3. RUN_ANALYZE - Update table statistics
   Use when: Planner estimates are severely wrong

4. DONE - Optimization complete
   Use when: Feedback status is "pass" OR no more improvements possible

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

IMPORTANT RULES:
1. If status is "pass", respond with action "DONE"
2. Prefer CREATE_INDEX over REWRITE_QUERY when suggested
3. Only rewrite queries if you're confident it improves performance
4. If stuck after 3 iterations without improvement, choose FAILED
5. Always provide clear reasoning
6. Respond with ONLY valid JSON, no other text

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
