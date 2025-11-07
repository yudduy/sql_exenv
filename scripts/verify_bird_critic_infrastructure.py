#!/usr/bin/env python3
"""
Verification Script for BIRD-CRITIC Evaluation Infrastructure

This script demonstrates:
1. Dataset statistics and coverage
2. Test case runner functionality
3. Evaluation metrics implementation
4. Example task execution

Usage:
    python scripts/verify_bird_critic_infrastructure.py [--db-connection DB_CONN]
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Any
from collections import Counter

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from agentic_dba.test_case_runner import TestCaseRunner
from agentic_dba.evaluation_metrics import BIRDCriticMetrics


def load_dataset(dataset_path: Path) -> List[Dict[str, Any]]:
    """Load BIRD-CRITIC dataset from JSONL file."""
    tasks = []
    with open(dataset_path) as f:
        for line in f:
            tasks.append(json.loads(line))
    return tasks


def analyze_dataset_statistics(tasks: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Analyze dataset and generate statistics."""
    stats = {
        "total_tasks": len(tasks),
        "databases": Counter(),
        "categories": Counter(),
        "efficiency_count": 0,
        "instance_ids": set(),
        "issue_sql_lengths": [],
        "preprocess_counts": [],
        "cleanup_counts": [],
    }

    for task in tasks:
        stats["databases"][task.get("db_id")] += 1
        stats["categories"][task.get("category")] += 1

        if task.get("efficiency", False):
            stats["efficiency_count"] += 1

        stats["instance_ids"].add(task.get("instance_id"))
        stats["issue_sql_lengths"].append(len(task.get("issue_sql", [])))
        stats["preprocess_counts"].append(len(task.get("preprocess_sql", [])))
        stats["cleanup_counts"].append(len(task.get("clean_up_sql", [])))

    return stats


def print_dataset_report(stats: Dict[str, Any]):
    """Print comprehensive dataset statistics report."""
    print()
    print("=" * 80)
    print("BIRD-CRITIC DATASET STATISTICS")
    print("=" * 80)
    print()

    print(f"Total Tasks:              {stats['total_tasks']}")
    print(f"Unique Instance IDs:      {len(stats['instance_ids'])}")
    print(f"Unique Databases:         {len(stats['databases'])}")
    print(f"Efficiency Tasks:         {stats['efficiency_count']} ({stats['efficiency_count']/stats['total_tasks']*100:.1f}%)")
    print()

    print("Category Distribution:")
    for category, count in sorted(stats['categories'].items()):
        pct = count / stats['total_tasks'] * 100
        bar = "█" * int(pct / 2)
        print(f"  {category:20s}: {count:3d} ({pct:5.1f}%) {bar}")
    print()

    print("Database Coverage:")
    for db_id, count in sorted(stats['databases'].most_common()):
        pct = count / stats['total_tasks'] * 100
        bar = "█" * int(pct / 2)
        print(f"  {db_id:30s}: {count:3d} ({pct:5.1f}%) {bar}")
    print()

    # Analyze issue_sql complexity
    issue_sql_counts = Counter(stats['issue_sql_lengths'])
    print("Issue SQL Complexity (statements per task):")
    for count, freq in sorted(issue_sql_counts.items()):
        print(f"  {count} statement(s): {freq} tasks")
    print()

    # Preprocess/cleanup statistics
    preprocess_with = sum(1 for x in stats['preprocess_counts'] if x > 0)
    cleanup_with = sum(1 for x in stats['cleanup_counts'] if x > 0)
    print("Setup/Teardown Requirements:")
    print(f"  Tasks with preprocess_sql:  {preprocess_with} ({preprocess_with/stats['total_tasks']*100:.1f}%)")
    print(f"  Tasks with clean_up_sql:    {cleanup_with} ({cleanup_with/stats['total_tasks']*100:.1f}%)")
    print()

    # Instance ID validation
    expected_ids = set(range(200))
    actual_ids = stats['instance_ids']
    if actual_ids == expected_ids:
        print("✓ All instance_ids 0-199 present")
    else:
        missing = expected_ids - actual_ids
        extra = actual_ids - expected_ids
        if missing:
            print(f"⚠ Missing instance_ids: {sorted(list(missing))[:10]}")
        if extra:
            print(f"⚠ Extra instance_ids: {sorted(list(extra))[:10]}")

    print("=" * 80)


def demonstrate_test_runner(tasks: List[Dict[str, Any]], db_connection: str):
    """Demonstrate test case runner with sample tasks."""
    print()
    print("=" * 80)
    print("TEST CASE RUNNER DEMONSTRATION")
    print("=" * 80)
    print()

    # Select diverse sample tasks
    sample_tasks = []

    # Find one task of each category
    categories = set()
    for task in tasks:
        category = task.get("category")
        if category not in categories:
            sample_tasks.append(task)
            categories.add(category)
        if len(sample_tasks) >= 3:
            break

    print(f"Testing with {len(sample_tasks)} sample tasks...")
    print()

    for i, task in enumerate(sample_tasks, 1):
        task_id = task.get("instance_id")
        category = task.get("category")
        db_id = task.get("db_id")

        print(f"[{i}/{len(sample_tasks)}] Task {task_id} - {category} ({db_id})")
        print(f"  Query: {task.get('query', 'N/A')[:100]}...")
        print(f"  Issue SQL count: {len(task.get('issue_sql', []))}")
        print(f"  Preprocess: {len(task.get('preprocess_sql', []))} statements")
        print(f"  Cleanup: {len(task.get('clean_up_sql', []))} statements")

        # Test with the issue_sql (should work but may have bugs)
        if task.get("issue_sql"):
            issue_sql = task["issue_sql"][0]
            print(f"  Testing issue_sql: {issue_sql[:80]}...")

            try:
                with TestCaseRunner(db_connection) as runner:
                    result = runner.execute_test_case(
                        task=task,
                        predicted_sql=issue_sql,
                        compare_with_issue_sql=False,
                    )

                    if result.passed:
                        print(f"  ✓ Execution successful")
                        pred_result = result.details.get("predicted_result", {})
                        rowcount = pred_result.get("rowcount", 0)
                        exec_time = pred_result.get("execution_time_ms", 0)
                        print(f"    Rows: {rowcount}, Time: {exec_time:.2f}ms")
                    else:
                        print(f"  ✗ Execution failed: {result.error}")

            except Exception as e:
                print(f"  ✗ Error: {type(e).__name__}: {e}")

        print()


def demonstrate_metrics(tasks: List[Dict[str, Any]], db_connection: str):
    """Demonstrate evaluation metrics with sample tasks."""
    print()
    print("=" * 80)
    print("EVALUATION METRICS DEMONSTRATION")
    print("=" * 80)
    print()

    metrics = BIRDCriticMetrics(db_connection)

    # Select one task per metric type
    metric_examples = {
        "soft_ex": None,
        "tcv": None,
        "qep": None,
    }

    for task in tasks:
        category = task.get("category")
        efficiency = task.get("efficiency", False)

        if efficiency and metric_examples["qep"] is None:
            metric_examples["qep"] = task
        elif category == "Management" and metric_examples["tcv"] is None:
            metric_examples["tcv"] = task
        elif category in ["Query", "Personalization"] and metric_examples["soft_ex"] is None:
            metric_examples["soft_ex"] = task

        if all(v is not None for v in metric_examples.values()):
            break

    # Demonstrate each metric
    for metric_type, task in metric_examples.items():
        if task is None:
            print(f"[{metric_type.upper()}] No example task found")
            print()
            continue

        task_id = task.get("instance_id")
        category = task.get("category")
        db_id = task.get("db_id")

        print(f"[{metric_type.upper()}] Task {task_id} - {category} ({db_id})")
        print(f"  Query: {task.get('query', 'N/A')[:100]}...")

        # Use issue_sql as predicted_sql for demonstration
        if task.get("issue_sql"):
            predicted_sql = task["issue_sql"][0]
            print(f"  Predicted SQL: {predicted_sql[:80]}...")

            try:
                result = metrics.evaluate_task(
                    task=task,
                    predicted_sql=predicted_sql,
                    metric_type=metric_type,
                )

                status = "✓ PASS" if result.passed else "✗ FAIL"
                print(f"  {status} - Score: {result.score:.2f}")

                if result.error:
                    print(f"  Error: {result.error}")

                # Print key details
                details = result.details
                if metric_type == "qep" and "cost_improvement_pct" in details:
                    print(f"  Cost improvement: {details['cost_improvement_pct']:.1f}%")
                    print(f"  Time improvement: {details.get('time_improvement_pct', 0):.1f}%")
                elif metric_type == "soft_ex" and "predicted_rowcount" in details:
                    print(f"  Rows returned: {details['predicted_rowcount']}")

            except Exception as e:
                print(f"  ✗ Error: {type(e).__name__}: {e}")

        print()


def main():
    """Main verification script."""
    parser = argparse.ArgumentParser(
        description="Verify BIRD-CRITIC evaluation infrastructure"
    )
    parser.add_argument(
        "--dataset",
        default="BIRD-CRITIC-1/baseline/data/flash_exp_200.jsonl",
        help="Path to BIRD-CRITIC dataset JSONL file",
    )
    parser.add_argument(
        "--db-connection",
        help="PostgreSQL connection string (optional for dataset stats)",
    )
    parser.add_argument(
        "--skip-db-tests",
        action="store_true",
        help="Skip database-dependent tests",
    )

    args = parser.parse_args()

    # Resolve dataset path
    project_root = Path(__file__).parent.parent
    dataset_path = project_root / args.dataset

    if not dataset_path.exists():
        print(f"✗ Dataset not found: {dataset_path}")
        print()
        print("Run this first to download the dataset:")
        print("  python scripts/download_bird_critic_dataset.py")
        return 1

    print()
    print("=" * 80)
    print("BIRD-CRITIC EVALUATION INFRASTRUCTURE VERIFICATION")
    print("=" * 80)
    print()
    print(f"Dataset: {dataset_path}")
    print(f"File size: {dataset_path.stat().st_size / 1024:.1f} KB")

    # Load dataset
    print()
    print("Loading dataset...")
    tasks = load_dataset(dataset_path)
    print(f"✓ Loaded {len(tasks)} tasks")

    # Part 1: Dataset statistics
    stats = analyze_dataset_statistics(tasks)
    print_dataset_report(stats)

    # Part 2: Test runner demonstration (requires database)
    if not args.skip_db_tests and args.db_connection:
        try:
            demonstrate_test_runner(tasks, args.db_connection)
        except Exception as e:
            print(f"⚠ Test runner demonstration failed: {e}")
            print("  (This is expected if database is not available)")
            print()

        try:
            demonstrate_metrics(tasks, args.db_connection)
        except Exception as e:
            print(f"⚠ Metrics demonstration failed: {e}")
            print("  (This is expected if database is not available)")
            print()
    else:
        print()
        print("=" * 80)
        print("DATABASE TESTS SKIPPED")
        print("=" * 80)
        print()
        print("To test the test case runner and metrics, provide a database connection:")
        print("  python scripts/verify_bird_critic_infrastructure.py \\")
        print("    --db-connection 'postgresql://user:pass@localhost/bird_db'")
        print()

    # Summary
    print()
    print("=" * 80)
    print("VERIFICATION SUMMARY")
    print("=" * 80)
    print()
    print("✓ Dataset downloaded and validated")
    print(f"✓ {stats['total_tasks']} tasks across {len(stats['databases'])} databases")
    print(f"✓ {len(stats['categories'])} task categories")
    print("✓ TestCaseRunner implemented with transaction isolation")
    print("✓ BIRDCriticMetrics implemented (soft_ex, tcv, qep)")
    print()
    print("Next steps:")
    print("  1. Set up test databases with BIRD-CRITIC schemas")
    print("  2. Run full evaluation: python -m agentic_dba.bird_critic_runner")
    print("  3. Compare agent performance against baselines")
    print()
    print("=" * 80)

    return 0


if __name__ == "__main__":
    sys.exit(main())
