"""
BIRD-CRITIC Benchmark Evaluation Runner

Evaluates the autonomous SQL optimization agent against the BIRD-CRITIC benchmark.
Supports the flash-exp (200 tasks) and full PostgreSQL (530 tasks) datasets.

Usage:
    python -m agentic_dba.bird_critic_runner \\
        --dataset flash-exp \\
        --db-connection postgresql://localhost/bird_db \\
        --limit 10 \\
        --output results.json
"""

import argparse
import asyncio
import json
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Dict, Any, Optional
import psycopg2

from .agent import SQLOptimizationAgent, BIRDCriticTask, Solution


@dataclass
class TaskResult:
    """Result from evaluating a single BIRD-CRITIC task."""

    task_id: str
    db_id: str
    success: bool
    iterations: int
    time_seconds: float
    actions_taken: List[str]
    final_query: str
    reason: str
    qep_improvement: Optional[float] = None
    error: Optional[str] = None


class BIRDCriticEvaluator:
    """
    Evaluates autonomous agent against BIRD-CRITIC benchmark.

    Datasets available:
    - flash-exp: 200 PostgreSQL tasks (recommended for testing)
    - postgresql: 530 PostgreSQL tasks (full evaluation)
    - open: 570 tasks across 4 dialects (requires multi-DB setup)
    """

    def __init__(
        self,
        dataset_path: str,
        db_connection_string: str,
        max_concurrent: int = 1,  # Sequential by default for safety
    ):
        """
        Initialize the evaluator.

        Args:
            dataset_path: Path to BIRD-CRITIC dataset JSON file
            db_connection_string: PostgreSQL connection string
            max_concurrent: Max parallel task evaluations (use 1 for debugging)
        """
        self.dataset_path = Path(dataset_path)
        self.db_connection = db_connection_string
        self.max_concurrent = max_concurrent

    async def evaluate(
        self,
        limit: Optional[int] = None,
        output_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Run full benchmark evaluation.

        Args:
            limit: Limit to first N tasks (for testing)
            output_path: Path to save results JSON

        Returns:
            Evaluation results with aggregate metrics
        """
        print("=== BIRD-CRITIC Benchmark Evaluation ===")
        print(f"Dataset: {self.dataset_path}")
        print(f"Database: {self.db_connection}")
        print(f"Max Concurrent: {self.max_concurrent}")
        print()

        # Load tasks
        tasks = self._load_tasks(limit)
        print(f"Loaded {len(tasks)} tasks\n")

        # Initialize agent with adaptive iteration control
        agent = SQLOptimizationAgent(
            max_iterations=10,  # Adaptive stopping with 7-10 iterations
            min_iterations=3,  # Minimum before early stopping
            timeout_per_task_seconds=120,
            use_extended_thinking=True,  # Re-enabled with schema fixes
            extended_thinking_budget=8000,  # Higher budget for complex query rewrites
        )

        # Run evaluations
        start_time = time.time()
        results = await self._evaluate_tasks(agent, tasks)
        total_time = time.time() - start_time

        # Compute aggregate metrics
        aggregate = self._compute_aggregate_metrics(results, total_time)

        # Generate report
        full_results = {
            "dataset": str(self.dataset_path),
            "total_tasks": len(tasks),
            "total_time_seconds": total_time,
            "aggregate": aggregate,
            "results": [asdict(r) for r in results],
        }

        # Save results
        if output_path:
            with open(output_path, "w") as f:
                json.dump(full_results, f, indent=2)
            print(f"\n✓ Results saved to {output_path}")

        # Print summary
        self._print_summary(aggregate)

        return full_results

    def _load_tasks(self, limit: Optional[int] = None) -> List[BIRDCriticTask]:
        """
        Load BIRD-CRITIC tasks from dataset file.

        Expected format (Hugging Face datasets JSON):
        [
            {
                "task_id": "001",
                "db_id": "ecommerce",
                "user_query": "Find slow queries",
                "buggy_sql": "SELECT * FROM ...",
                "solution_sql": "SELECT id, name FROM ...",
                "efficiency": true
            },
            ...
        ]
        """
        with open(self.dataset_path) as f:
            data = json.load(f)

        tasks = []
        for item in data[:limit] if limit else data:
            task = BIRDCriticTask(
                task_id=item.get("task_id", item.get("id", str(len(tasks)))),
                db_id=item.get("db_id", "unknown"),
                buggy_sql=item.get("buggy_sql", item.get("SQL", "")),
                user_query=item.get("user_query", item.get("query", "")),
                solution_sql=item.get("solution_sql"),
                efficiency=item.get("efficiency", False),
            )
            tasks.append(task)

        return tasks

    async def _evaluate_tasks(
        self,
        agent: SQLOptimizationAgent,
        tasks: List[BIRDCriticTask],
    ) -> List[TaskResult]:
        """
        Evaluate all tasks with concurrent execution.

        Args:
            agent: SQLOptimizationAgent instance
            tasks: List of tasks to evaluate

        Returns:
            List of TaskResult objects
        """
        if self.max_concurrent == 1:
            # Sequential execution (easier to debug)
            results = []
            for i, task in enumerate(tasks, 1):
                print(f"\n[{i}/{len(tasks)}] Evaluating {task.task_id}...")
                result = await self._evaluate_single_task(agent, task, i, len(tasks))
                results.append(result)
            return results
        else:
            # Concurrent execution
            semaphore = asyncio.Semaphore(self.max_concurrent)

            async def eval_with_semaphore(task, idx):
                async with semaphore:
                    return await self._evaluate_single_task(agent, task, idx, len(tasks))

            tasks_with_idx = [(task, i + 1) for i, task in enumerate(tasks)]
            results = await asyncio.gather(
                *[eval_with_semaphore(task, idx) for task, idx in tasks_with_idx]
            )
            return results

    async def _evaluate_single_task(
        self,
        agent: SQLOptimizationAgent,
        task: BIRDCriticTask,
        task_num: int,
        total_tasks: int,
    ) -> TaskResult:
        """
        Evaluate a single task.

        Returns:
            TaskResult with outcome and metrics
        """
        start = time.time()

        try:
            # Run agent optimization
            solution = await agent.solve_task(
                task=task,
                db_connection_string=self.db_connection,
                constraints={
                    "max_cost": 50000.0,  # Reasonable for BIRD queries
                    "max_time_ms": 30000,
                    "analyze_cost_threshold": 5_000_000,
                },
            )

            elapsed = time.time() - start

            # Extract action types
            action_types = [a.type.value for a in solution.actions]

            # Compute QEP improvement if possible
            qep_improvement = None
            if solution.success and solution.metrics:
                # TODO: Compare before/after costs
                qep_improvement = solution.metrics.get("cost_improvement_pct")

            result = TaskResult(
                task_id=task.task_id,
                db_id=task.db_id,
                success=solution.success,
                iterations=solution.total_iterations(),
                time_seconds=elapsed,
                actions_taken=action_types,
                final_query=solution.final_query,
                reason=solution.reason,
                qep_improvement=qep_improvement,
            )

            status = "✓" if solution.success else "✗"
            print(f"  {status} {task.task_id}: {solution.reason} ({elapsed:.1f}s)")

            return result

        except Exception as e:
            elapsed = time.time() - start
            print(f"  ✗ {task.task_id}: ERROR - {e}")

            return TaskResult(
                task_id=task.task_id,
                db_id=task.db_id,
                success=False,
                iterations=0,
                time_seconds=elapsed,
                actions_taken=[],
                final_query=task.buggy_sql,
                reason="Exception during evaluation",
                error=str(e),
            )

    def _compute_aggregate_metrics(
        self,
        results: List[TaskResult],
        total_time: float,
    ) -> Dict[str, Any]:
        """Compute aggregate statistics across all results."""
        total = len(results)
        successful = sum(1 for r in results if r.success)
        failed = total - successful

        avg_time = sum(r.time_seconds for r in results) / total if total > 0 else 0
        avg_iterations = (
            sum(r.iterations for r in results) / total if total > 0 else 0
        )

        # Count action types
        action_counts = {}
        for result in results:
            for action in result.actions_taken:
                action_counts[action] = action_counts.get(action, 0) + 1

        return {
            "total_tasks": total,
            "successful": successful,
            "failed": failed,
            "success_rate": successful / total if total > 0 else 0,
            "avg_time_per_task": avg_time,
            "avg_iterations": avg_iterations,
            "total_time": total_time,
            "action_distribution": action_counts,
        }

    def _print_summary(self, aggregate: Dict[str, Any]):
        """Print human-readable summary."""
        print("\n" + "=" * 60)
        print("EVALUATION SUMMARY")
        print("=" * 60)
        print(f"Total Tasks:      {aggregate['total_tasks']}")
        print(f"Successful:       {aggregate['successful']} ({aggregate['success_rate']*100:.1f}%)")
        print(f"Failed:           {aggregate['failed']}")
        print(f"Avg Time/Task:    {aggregate['avg_time_per_task']:.1f}s")
        print(f"Avg Iterations:   {aggregate['avg_iterations']:.1f}")
        print(f"Total Time:       {aggregate['total_time']:.1f}s")
        print("\nAction Distribution:")
        for action, count in sorted(aggregate['action_distribution'].items()):
            print(f"  {action:20s}: {count}")
        print("=" * 60)


async def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Evaluate autonomous agent on BIRD-CRITIC benchmark"
    )
    parser.add_argument(
        "--dataset",
        required=True,
        help="Path to BIRD-CRITIC dataset JSON file",
    )
    parser.add_argument(
        "--db-connection",
        required=True,
        help="PostgreSQL connection string",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Limit to first N tasks (for testing)",
    )
    parser.add_argument(
        "--output",
        help="Output JSON file for results",
        default="bird_critic_results.json",
    )
    parser.add_argument(
        "--max-concurrent",
        type=int,
        default=1,
        help="Maximum concurrent task evaluations",
    )

    args = parser.parse_args()

    evaluator = BIRDCriticEvaluator(
        dataset_path=args.dataset,
        db_connection_string=args.db_connection,
        max_concurrent=args.max_concurrent,
    )

    await evaluator.evaluate(
        limit=args.limit,
        output_path=args.output,
    )


if __name__ == "__main__":
    asyncio.run(main())
