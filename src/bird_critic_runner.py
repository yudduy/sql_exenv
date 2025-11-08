"""
BIRD-CRITIC Benchmark Evaluation Runner

Evaluates the autonomous SQL optimization agent against the BIRD-CRITIC benchmark.
Supports the flash-exp (200 tasks) and full PostgreSQL (530 tasks) datasets.

Usage:
    # Smoke test (10 tasks)
    python -m agentic_dba.bird_critic_runner \\
        --dataset BIRD-CRITIC-1/baseline/data/flash_exp_200.jsonl \\
        --db-connection "dbname=bird_critic host=/tmp user=duynguy" \\
        --smoke-test \\
        --output smoke_test_results.json

    # Full evaluation (200 tasks)
    python -m agentic_dba.bird_critic_runner \\
        --dataset BIRD-CRITIC-1/baseline/data/flash_exp_200.jsonl \\
        --db-connection "dbname={db_id} host=/tmp user=duynguy" \\
        --parallel 5 \\
        --output flash_exp_200_results.json

    # Category-specific evaluation
    python -m agentic_dba.bird_critic_runner \\
        --dataset BIRD-CRITIC-1/baseline/data/flash_exp_200.jsonl \\
        --category Efficiency \\
        --output efficiency_results.json
"""

import argparse
import asyncio
import json
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Dict, Any, Optional
import logging

from agent import SQLOptimizationAgent, BIRDCriticTask, Solution
from evaluation_metrics import BIRDCriticMetrics, EvaluationResult

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@dataclass
class TaskResult:
    """Result from evaluating a single BIRD-CRITIC task."""

    task_id: str
    db_id: str
    success: bool
    metric_used: str
    score: float
    iterations: int
    time_seconds: float
    actions_taken: List[str]
    final_query: str
    reason: str
    category: Optional[str] = None
    efficiency: Optional[bool] = None
    error: Optional[str] = None
    details: Optional[Dict[str, Any]] = None


class BIRDCriticEvaluator:
    """
    Evaluates autonomous agent against BIRD-CRITIC benchmark with official metrics.

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
        agent_config: Optional[Dict[str, Any]] = None,
    ):
        """
        Initialize the evaluator.

        Args:
            dataset_path: Path to BIRD-CRITIC dataset JSONL file
            db_connection_string: PostgreSQL connection string
            max_concurrent: Max parallel task evaluations (use 1 for debugging)
            agent_config: Optional agent configuration overrides
        """
        self.dataset_path = Path(dataset_path)
        self.db_connection = db_connection_string
        self.max_concurrent = max_concurrent
        self.agent_config = agent_config or {}

    async def evaluate(
        self,
        limit: Optional[int] = None,
        category_filter: Optional[str] = None,
        output_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Run full benchmark evaluation with official metrics.

        Args:
            limit: Limit to first N tasks (for testing)
            category_filter: Filter by category (Query, Management, Efficiency, Personalization)
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
        tasks = self._load_tasks(limit, category_filter)
        print(f"Loaded {len(tasks)} tasks")

        # Category breakdown
        category_counts = {}
        for task in tasks:
            cat = task.get("category", "Unknown")
            category_counts[cat] = category_counts.get(cat, 0) + 1
        print(f"Category breakdown: {category_counts}\n")

        # Estimate cost and time
        estimated_cost = len(tasks) * 0.10  # ~$0.10 per task
        estimated_time_mins = len(tasks) * 2  # ~2 minutes per task
        print(f"Estimated cost: ${estimated_cost:.2f}")
        print(f"Estimated time: ~{estimated_time_mins} minutes\n")

        # Initialize agent with adaptive iteration control
        agent = SQLOptimizationAgent(
            max_iterations=self.agent_config.get("max_iterations", 10),
            min_iterations=self.agent_config.get("min_iterations", 3),
            timeout_per_task_seconds=self.agent_config.get("timeout_per_task_seconds", 120),
            use_extended_thinking=self.agent_config.get("use_extended_thinking", True),
            extended_thinking_budget=self.agent_config.get("extended_thinking_budget", 8000),
        )

        # Run evaluations
        start_time = time.time()
        if self.max_concurrent > 1:
            results = await self._evaluate_tasks_parallel(agent, tasks)
        else:
            results = await self._evaluate_tasks_sequential(agent, tasks, output_path)
        total_time = time.time() - start_time

        # Compute aggregate metrics
        aggregate = self._analyze_results([asdict(r) for r in results])

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
        self._print_summary(aggregate, total_time)

        return full_results

    def _load_tasks(
        self,
        limit: Optional[int] = None,
        category_filter: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Load BIRD-CRITIC tasks from JSONL dataset file.

        Expected format (BIRD-CRITIC official format):
        {
            "instance_id": 0,
            "db_id": "financial",
            "query": "Natural language description",
            "issue_sql": ["SELECT ..."],
            "preprocess_sql": [],
            "clean_up_sql": [],
            "category": "Query",
            "efficiency": false
        }

        Also supports legacy format:
        {
            "task_id": "001",
            "db_id": "ecommerce",
            "user_query": "Find slow queries",
            "buggy_sql": "SELECT * FROM ...",
            "solution_sql": "SELECT id, name FROM ...",
            "efficiency": true
        }
        """
        tasks = []
        with open(self.dataset_path) as f:
            for line in f:
                if not line.strip():
                    continue
                item = json.loads(line)

                # Apply category filter
                if category_filter:
                    item_category = item.get("category", "Unknown")
                    if item_category != category_filter:
                        continue

                tasks.append(item)

        # Apply limit
        if limit:
            tasks = tasks[:limit]

        return tasks

    async def _evaluate_tasks_sequential(
        self,
        agent: SQLOptimizationAgent,
        tasks: List[Dict[str, Any]],
        output_path: Optional[str] = None,
    ) -> List[TaskResult]:
        """
        Evaluate all tasks sequentially (safer for debugging).

        Args:
            agent: SQLOptimizationAgent instance
            tasks: List of tasks to evaluate
            output_path: Optional path to save intermediate results

        Returns:
            List of TaskResult objects
        """
        results = []
        for i, task in enumerate(tasks, 1):
            task_id = str(task.get("instance_id", task.get("task_id", i)))
            db_id = task.get("db_id", "unknown")
            print(f"\n[{i}/{len(tasks)}] Evaluating Task {task_id} (DB: {db_id})...")

            result = await self._evaluate_single_task(agent, task, i, len(tasks))
            results.append(result)

            # Save intermediate results (append mode)
            if output_path:
                self._save_intermediate_result(output_path, result)

        return results

    async def _evaluate_tasks_parallel(
        self,
        agent: SQLOptimizationAgent,
        tasks: List[Dict[str, Any]],
    ) -> List[TaskResult]:
        """
        Evaluate tasks in parallel with progress tracking.

        Args:
            agent: SQLOptimizationAgent instance
            tasks: List of tasks to evaluate

        Returns:
            List of TaskResult objects
        """
        try:
            from tqdm import tqdm
        except ImportError:
            logger.warning("tqdm not installed, falling back to sequential evaluation")
            return await self._evaluate_tasks_sequential(agent, tasks)

        semaphore = asyncio.Semaphore(self.max_concurrent)
        results = []

        async def evaluate_with_semaphore(task, idx):
            async with semaphore:
                return await self._evaluate_single_task(agent, task, idx, len(tasks))

        # Create progress bar
        with tqdm(total=len(tasks), desc="Evaluating tasks") as pbar:
            tasks_with_idx = [(task, i + 1) for i, task in enumerate(tasks)]
            for coro in asyncio.as_completed([evaluate_with_semaphore(task, idx) for task, idx in tasks_with_idx]):
                result = await coro
                results.append(result)
                pbar.update(1)
                success_count = sum(1 for r in results if r.success)
                pbar.set_postfix(success=f"{success_count}/{len(results)}")

        return results

    async def _evaluate_single_task(
        self,
        agent: SQLOptimizationAgent,
        task_data: Dict[str, Any],
        task_num: int,
        total_tasks: int,
    ) -> TaskResult:
        """
        Evaluate a single task using official BIRD-CRITIC metrics.

        Returns:
            TaskResult with outcome and official metrics
        """
        task_id = str(task_data.get("instance_id", task_data.get("task_id", task_num)))
        db_id = task_data.get("db_id", "unknown")
        start = time.time()

        try:
            # Create BIRDCriticTask from task_data (support both formats)
            task = self._create_bird_critic_task(task_data)

            # Resolve database connection string (support {db_id} placeholder)
            db_connection = self.db_connection.replace("{db_id}", db_id)

            # Run agent optimization
            solution: Solution = await agent.solve_task(
                task=task,
                db_connection_string=db_connection,
                constraints={
                    "max_cost": 50000.0,  # Reasonable for BIRD queries
                    "max_time_ms": 30000,
                    "analyze_cost_threshold": 5_000_000,
                },
            )

            elapsed = time.time() - start

            # Extract action types
            action_types = [a.type.value for a in solution.actions]

            # Evaluate with official metrics
            metrics = BIRDCriticMetrics(db_connection)
            eval_result: EvaluationResult = metrics.evaluate_task(task_data, solution.final_query)

            result = TaskResult(
                task_id=task_id,
                db_id=db_id,
                success=eval_result.passed,
                metric_used=eval_result.metric,
                score=eval_result.score,
                iterations=solution.total_iterations(),
                time_seconds=elapsed,
                actions_taken=action_types,
                final_query=solution.final_query,
                reason=solution.reason,
                category=task_data.get("category"),
                efficiency=task_data.get("efficiency"),
                error=eval_result.error,
                details=eval_result.details,
            )

            status = "✓" if eval_result.passed else "✗"
            metric_display = f"{eval_result.metric}={eval_result.score:.2f}"
            print(f"  {status} {task_id}: {metric_display} - {solution.reason} ({elapsed:.1f}s)")

            return result

        except Exception as e:
            elapsed = time.time() - start
            logger.exception(f"Task {task_id} failed with exception")
            print(f"  ✗ {task_id}: ERROR - {e}")

            return TaskResult(
                task_id=task_id,
                db_id=db_id,
                success=False,
                metric_used="error",
                score=0.0,
                iterations=0,
                time_seconds=elapsed,
                actions_taken=[],
                final_query="",
                reason="Exception during evaluation",
                category=task_data.get("category"),
                efficiency=task_data.get("efficiency"),
                error=str(e),
            )

    def _create_bird_critic_task(self, task_data: Dict[str, Any]) -> BIRDCriticTask:
        """
        Create BIRDCriticTask from task data dictionary.

        Supports both official format (issue_sql) and legacy format (buggy_sql).

        Args:
            task_data: Task dictionary from JSONL file

        Returns:
            BIRDCriticTask instance
        """
        # Handle both instance_id and task_id
        task_id = str(task_data.get("instance_id", task_data.get("task_id", "unknown")))

        # Handle both query and user_query
        user_query = task_data.get("query", task_data.get("user_query", ""))

        # Handle both issue_sql (new) and buggy_sql (legacy)
        issue_sql = task_data.get("issue_sql")
        buggy_sql = task_data.get("buggy_sql")

        # Normalize to list format
        if issue_sql is None and buggy_sql:
            issue_sql = [buggy_sql]
        elif issue_sql and not isinstance(issue_sql, list):
            issue_sql = [issue_sql]

        return BIRDCriticTask(
            task_id=task_id,
            db_id=task_data.get("db_id", "unknown"),
            user_query=user_query,
            buggy_sql=buggy_sql,
            issue_sql=issue_sql,
            solution_sql=task_data.get("solution_sql"),
            efficiency=task_data.get("efficiency", False),
            preprocess_sql=task_data.get("preprocess_sql"),
            clean_up_sql=task_data.get("clean_up_sql"),
        )

    def _save_intermediate_result(self, output_path: str, result: TaskResult):
        """
        Save intermediate result to file (append mode for fault tolerance).

        Args:
            output_path: Path to output file
            result: TaskResult to save
        """
        try:
            intermediate_path = output_path.replace(".json", "_intermediate.jsonl")
            with open(intermediate_path, "a") as f:
                f.write(json.dumps(asdict(result)) + "\n")
        except Exception as e:
            logger.warning(f"Failed to save intermediate result: {e}")

    def _analyze_results(self, results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Generate comprehensive statistics.

        Returns:
            {
                "total_tasks": int,
                "successful": int,
                "failed": int,
                "success_rate": float,
                "avg_time": float,
                "avg_iterations": float,
                "avg_score": float,
                "by_category": {...},
                "by_database": {...},
                "by_metric": {...},
                "action_distribution": {...}
            }
        """
        total = len(results)
        if total == 0:
            return {
                "total_tasks": 0,
                "successful": 0,
                "failed": 0,
                "success_rate": 0.0,
            }

        successful = sum(1 for r in results if r["success"])
        failed = total - successful

        avg_time = sum(r["time_seconds"] for r in results) / total
        avg_iterations = sum(r["iterations"] for r in results) / total
        avg_score = sum(r["score"] for r in results) / total

        # Category breakdown
        by_category = {}
        for result in results:
            category = result.get("category", "Unknown")
            if category not in by_category:
                by_category[category] = {"total": 0, "success": 0, "scores": []}
            by_category[category]["total"] += 1
            by_category[category]["success"] += int(result["success"])
            by_category[category]["scores"].append(result["score"])

        # Add success rate and avg score per category
        for category, stats in by_category.items():
            stats["success_rate"] = stats["success"] / stats["total"] if stats["total"] > 0 else 0.0
            stats["avg_score"] = sum(stats["scores"]) / len(stats["scores"]) if stats["scores"] else 0.0
            del stats["scores"]  # Remove raw scores

        # Database breakdown
        by_database = {}
        for result in results:
            db_id = result.get("db_id", "Unknown")
            if db_id not in by_database:
                by_database[db_id] = {"total": 0, "success": 0}
            by_database[db_id]["total"] += 1
            by_database[db_id]["success"] += int(result["success"])

        # Metric usage breakdown
        by_metric = {}
        for result in results:
            metric = result.get("metric_used", "unknown")
            if metric not in by_metric:
                by_metric[metric] = {"total": 0, "success": 0, "scores": []}
            by_metric[metric]["total"] += 1
            by_metric[metric]["success"] += int(result["success"])
            by_metric[metric]["scores"].append(result["score"])

        # Add avg score per metric
        for metric, stats in by_metric.items():
            stats["avg_score"] = sum(stats["scores"]) / len(stats["scores"]) if stats["scores"] else 0.0
            del stats["scores"]

        # Action distribution
        action_counts = {}
        for result in results:
            for action in result.get("actions_taken", []):
                action_counts[action] = action_counts.get(action, 0) + 1

        return {
            "total_tasks": total,
            "successful": successful,
            "failed": failed,
            "success_rate": successful / total if total > 0 else 0.0,
            "avg_time_per_task": avg_time,
            "avg_iterations": avg_iterations,
            "avg_score": avg_score,
            "by_category": by_category,
            "by_database": by_database,
            "by_metric": by_metric,
            "action_distribution": action_counts,
        }

    def _print_summary(self, aggregate: Dict[str, Any], total_time: float):
        """Print human-readable summary."""
        print("\n" + "=" * 70)
        print("EVALUATION SUMMARY")
        print("=" * 70)
        print(f"Total Tasks:      {aggregate['total_tasks']}")
        print(f"Successful:       {aggregate['successful']} ({aggregate['success_rate']*100:.1f}%)")
        print(f"Failed:           {aggregate['failed']}")
        print(f"Avg Score:        {aggregate['avg_score']:.3f}")
        print(f"Avg Time/Task:    {aggregate['avg_time_per_task']:.1f}s")
        print(f"Avg Iterations:   {aggregate['avg_iterations']:.1f}")
        print(f"Total Time:       {total_time:.1f}s ({total_time/60:.1f} minutes)")

        print("\nBy Category:")
        for category, stats in sorted(aggregate['by_category'].items()):
            success_rate = stats['success_rate'] * 100
            avg_score = stats['avg_score']
            print(f"  {category:20s}: {stats['success']}/{stats['total']} ({success_rate:.1f}%) - Avg Score: {avg_score:.3f}")

        print("\nBy Metric:")
        for metric, stats in sorted(aggregate['by_metric'].items()):
            avg_score = stats['avg_score']
            print(f"  {metric:20s}: {stats['success']}/{stats['total']} - Avg Score: {avg_score:.3f}")

        print("\nAction Distribution:")
        for action, count in sorted(aggregate['action_distribution'].items(), key=lambda x: x[1], reverse=True):
            print(f"  {action:20s}: {count}")
        print("=" * 70)


async def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Evaluate autonomous agent on BIRD-CRITIC benchmark with official metrics"
    )
    parser.add_argument(
        "--dataset",
        required=True,
        help="Path to BIRD-CRITIC dataset JSONL file",
    )
    parser.add_argument(
        "--db-connection",
        required=True,
        help="PostgreSQL connection string (supports {db_id} placeholder)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Limit to first N tasks (for testing)",
    )
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help="Run smoke test on first 10 tasks (same as --limit 10)",
    )
    parser.add_argument(
        "--category",
        type=str,
        choices=["Query", "Management", "Efficiency", "Personalization"],
        help="Filter by category",
    )
    parser.add_argument(
        "--output",
        help="Output JSON file for results",
        default="bird_critic_results.json",
    )
    parser.add_argument(
        "--parallel",
        type=int,
        default=1,
        help="Number of parallel evaluations (default: 1 for sequential)",
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=10,
        help="Maximum optimization iterations per task (default: 10)",
    )
    parser.add_argument(
        "--min-iterations",
        type=int,
        default=3,
        help="Minimum iterations before early stopping (default: 3)",
    )

    args = parser.parse_args()

    # Handle smoke test
    limit = args.limit
    if args.smoke_test:
        limit = 10
        print("🧪 SMOKE TEST MODE - Evaluating first 10 tasks")
        print(f"Estimated cost: ~$1.00")
        print(f"Estimated time: ~10 minutes\n")

    evaluator = BIRDCriticEvaluator(
        dataset_path=args.dataset,
        db_connection_string=args.db_connection,
        max_concurrent=args.parallel,
        agent_config={
            "max_iterations": args.max_iterations,
            "min_iterations": args.min_iterations,
            "timeout_per_task_seconds": 120,
            "use_extended_thinking": True,
            "extended_thinking_budget": 8000,
        },
    )

    await evaluator.evaluate(
        limit=limit,
        category_filter=args.category,
        output_path=args.output,
    )


if __name__ == "__main__":
    asyncio.run(main())
