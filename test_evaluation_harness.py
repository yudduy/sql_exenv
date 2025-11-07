#!/usr/bin/env python3
"""
Quick validation test for Phase 5 evaluation harness.

Tests:
1. Import all modules successfully
2. TaskResult dataclass structure
3. Task loading from JSONL
4. BIRDCriticTask creation (both formats)
5. Metrics integration availability
"""

import sys
import json
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

def test_imports():
    """Test that all required modules can be imported."""
    print("Testing imports...")
    try:
        from agentic_dba.bird_critic_runner import (
            BIRDCriticEvaluator,
            TaskResult,
        )
        from agentic_dba.evaluation_metrics import (
            BIRDCriticMetrics,
            EvaluationResult,
        )
        from agentic_dba.test_case_runner import (
            TestCaseRunner,
            TestCaseResult,
        )
        from agentic_dba.agent import (
            SQLOptimizationAgent,
            BIRDCriticTask,
            Solution,
        )
        print("  ✓ All imports successful")
        return True
    except ImportError as e:
        print(f"  ✗ Import failed: {e}")
        return False


def test_task_result_structure():
    """Test TaskResult dataclass structure."""
    print("\nTesting TaskResult structure...")
    from agentic_dba.bird_critic_runner import TaskResult

    try:
        result = TaskResult(
            task_id="test_001",
            db_id="test_db",
            success=True,
            metric_used="soft_ex",
            score=0.95,
            iterations=3,
            time_seconds=45.2,
            actions_taken=["CREATE_INDEX", "DONE"],
            final_query="SELECT * FROM test",
            reason="Test passed",
            category="Query",
            efficiency=False,
        )

        # Verify fields
        assert result.task_id == "test_001"
        assert result.success is True
        assert result.metric_used == "soft_ex"
        assert result.score == 0.95
        assert len(result.actions_taken) == 2

        print("  ✓ TaskResult structure valid")
        return True
    except Exception as e:
        print(f"  ✗ TaskResult test failed: {e}")
        return False


def test_task_loading():
    """Test loading tasks from JSONL file."""
    print("\nTesting task loading...")
    from agentic_dba.bird_critic_runner import BIRDCriticEvaluator

    dataset_path = Path("BIRD-CRITIC-1/baseline/data/flash_exp_200.jsonl")
    if not dataset_path.exists():
        print(f"  ⚠ Dataset not found: {dataset_path}")
        print("  Skipping task loading test")
        return True

    try:
        evaluator = BIRDCriticEvaluator(
            dataset_path=str(dataset_path),
            db_connection_string="test_connection",
        )

        # Load first 5 tasks
        tasks = evaluator._load_tasks(limit=5)

        assert len(tasks) <= 5, f"Expected <= 5 tasks, got {len(tasks)}"

        # Verify task structure
        if tasks:
            task = tasks[0]
            assert "instance_id" in task or "task_id" in task
            assert "db_id" in task
            assert "issue_sql" in task or "buggy_sql" in task
            print(f"  ✓ Loaded {len(tasks)} tasks successfully")

        # Test category filtering
        query_tasks = evaluator._load_tasks(limit=100, category_filter="Query")
        if query_tasks:
            assert all(t.get("category") == "Query" for t in query_tasks)
            print(f"  ✓ Category filtering works ({len(query_tasks)} Query tasks)")

        return True
    except Exception as e:
        print(f"  ✗ Task loading failed: {e}")
        return False


def test_bird_critic_task_creation():
    """Test BIRDCriticTask creation from both formats."""
    print("\nTesting BIRDCriticTask creation...")
    from agentic_dba.bird_critic_runner import BIRDCriticEvaluator

    try:
        evaluator = BIRDCriticEvaluator(
            dataset_path="dummy.jsonl",
            db_connection_string="test_connection",
        )

        # Test new format (issue_sql)
        new_format = {
            "instance_id": 0,
            "db_id": "financial",
            "query": "Find accounts with high variance",
            "issue_sql": ["SELECT * FROM accounts WHERE amount > 1000"],
            "preprocess_sql": [],
            "clean_up_sql": [],
            "category": "Query",
            "efficiency": False,
        }

        task1 = evaluator._create_bird_critic_task(new_format)
        assert task1.task_id == "0"
        assert task1.db_id == "financial"
        assert task1.issue_sql is not None
        assert len(task1.issue_sql) == 1
        print("  ✓ New format (issue_sql) conversion works")

        # Test legacy format (buggy_sql)
        legacy_format = {
            "task_id": "legacy_001",
            "db_id": "test_db",
            "user_query": "Legacy query",
            "buggy_sql": "SELECT * FROM legacy",
            "solution_sql": "SELECT id FROM legacy",
            "efficiency": True,
        }

        task2 = evaluator._create_bird_critic_task(legacy_format)
        assert task2.task_id == "legacy_001"
        assert task2.buggy_sql == "SELECT * FROM legacy"
        assert task2.issue_sql is not None
        assert task2.issue_sql[0] == "SELECT * FROM legacy"
        print("  ✓ Legacy format (buggy_sql) conversion works")

        return True
    except Exception as e:
        print(f"  ✗ BIRDCriticTask creation failed: {e}")
        return False


def test_metrics_availability():
    """Test that evaluation metrics are available."""
    print("\nTesting metrics availability...")
    from agentic_dba.evaluation_metrics import BIRDCriticMetrics

    try:
        # Create metrics instance (no DB connection needed for this test)
        metrics = BIRDCriticMetrics(
            db_connection_string="test_connection",
            soft_ex_tolerance=0.0,
            qep_cost_threshold=0.9,
        )

        # Verify methods exist
        assert hasattr(metrics, "evaluate_task")
        assert hasattr(metrics, "soft_ex")
        assert hasattr(metrics, "test_case_validation")
        assert hasattr(metrics, "qep_comparison")

        print("  ✓ All metrics methods available")
        return True
    except Exception as e:
        print(f"  ✗ Metrics test failed: {e}")
        return False


def main():
    """Run all tests."""
    print("=" * 70)
    print("Phase 5 Evaluation Harness Validation")
    print("=" * 70)

    tests = [
        test_imports,
        test_task_result_structure,
        test_task_loading,
        test_bird_critic_task_creation,
        test_metrics_availability,
    ]

    results = []
    for test in tests:
        try:
            results.append(test())
        except Exception as e:
            print(f"\n✗ Test crashed: {e}")
            results.append(False)

    print("\n" + "=" * 70)
    print("VALIDATION SUMMARY")
    print("=" * 70)
    passed = sum(results)
    total = len(results)
    print(f"Tests Passed: {passed}/{total} ({passed/total*100:.1f}%)")

    if passed == total:
        print("\n✓ All tests passed! Evaluation harness is ready.")
        return 0
    else:
        print(f"\n✗ {total - passed} test(s) failed. Review errors above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
