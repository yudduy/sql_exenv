"""
Unit tests for BIRDCriticMetrics

Tests the official BIRD-CRITIC evaluation metrics:
- soft_ex (Soft Execution Match)
- tcv (Test Case Validation)
- qep (Query Execution Plan comparison)
"""

import pytest
from unittest.mock import Mock, MagicMock, patch, call
from typing import List, Tuple

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from agentic_dba.evaluation_metrics import (
    BIRDCriticMetrics,
    EvaluationResult,
    batch_evaluate,
)
from agentic_dba.test_case_runner import TestCaseResult


class TestEvaluationResult:
    """Test EvaluationResult dataclass."""

    def test_success_result(self):
        result = EvaluationResult(
            task_id="0",
            metric="soft_ex",
            passed=True,
            score=1.0,
            details={"rows": 5},
        )

        assert result.task_id == "0"
        assert result.metric == "soft_ex"
        assert result.passed is True
        assert result.score == 1.0
        assert result.error is None

    def test_failure_result(self):
        result = EvaluationResult(
            task_id="1",
            metric="tcv",
            passed=False,
            score=0.0,
            details={},
            error="SQL syntax error",
        )

        assert result.passed is False
        assert result.score == 0.0
        assert result.error == "SQL syntax error"


class TestBIRDCriticMetricsInit:
    """Test BIRDCriticMetrics initialization."""

    def test_init_with_defaults(self):
        metrics = BIRDCriticMetrics("postgresql://localhost/test")

        assert metrics.db_connection_string == "postgresql://localhost/test"
        assert metrics.soft_ex_tolerance == 0.0
        assert metrics.qep_cost_threshold == 0.9

    def test_init_with_custom_options(self):
        metrics = BIRDCriticMetrics(
            "postgresql://localhost/test",
            soft_ex_tolerance=0.001,
            qep_cost_threshold=0.8,
        )

        assert metrics.soft_ex_tolerance == 0.001
        assert metrics.qep_cost_threshold == 0.8


class TestEvaluateTask:
    """Test evaluate_task method (metric selection)."""

    @patch("agentic_dba.evaluation_metrics.TestCaseRunner")
    def test_automatic_metric_selection_query(self, mock_runner_class):
        # Mock for Query category -> soft_ex
        mock_runner = MagicMock()
        mock_runner.__enter__.return_value = mock_runner
        mock_runner.__exit__.return_value = None
        mock_runner.execute_test_case.return_value = TestCaseResult(
            passed=True,
            details={"predicted_result": {"rows": [(1,)]}},
        )
        mock_runner_class.return_value = mock_runner

        task = {
            "instance_id": 0,
            "category": "Query",
            "efficiency": False,
            "issue_sql": ["SELECT 1"],
            "preprocess_sql": [],
            "clean_up_sql": [],
        }

        metrics = BIRDCriticMetrics("postgresql://localhost/test")
        result = metrics.evaluate_task(task, "SELECT 1")

        assert result.metric == "soft_ex"

    @patch("agentic_dba.evaluation_metrics.TestCaseRunner")
    def test_automatic_metric_selection_management(self, mock_runner_class):
        # Mock for Management category -> tcv
        mock_runner = MagicMock()
        mock_runner.__enter__.return_value = mock_runner
        mock_runner.__exit__.return_value = None
        mock_runner.execute_test_case.return_value = TestCaseResult(
            passed=True,
            details={},
        )
        mock_runner_class.return_value = mock_runner

        task = {
            "instance_id": 1,
            "category": "Management",
            "efficiency": False,
            "issue_sql": ["CREATE TABLE test (id INT)"],
            "preprocess_sql": [],
            "clean_up_sql": [],
        }

        metrics = BIRDCriticMetrics("postgresql://localhost/test")
        result = metrics.evaluate_task(task, "CREATE TABLE test (id INT)")

        assert result.metric == "tcv"

    @patch("agentic_dba.evaluation_metrics.TestCaseRunner")
    def test_automatic_metric_selection_efficiency(self, mock_runner_class):
        # Mock for Efficiency tasks -> qep
        mock_runner = MagicMock()
        mock_runner.__enter__.return_value = mock_runner
        mock_runner.__exit__.return_value = None
        mock_runner.execute_test_case.return_value = TestCaseResult(
            passed=True,
            details={},
        )
        mock_runner.execute_explain_analyze.return_value = {
            "success": True,
            "total_cost": 50.0,
            "execution_time": 10.0,
        }
        mock_runner_class.return_value = mock_runner

        task = {
            "instance_id": 2,
            "category": "Efficiency",
            "efficiency": True,
            "issue_sql": ["SELECT * FROM large_table"],
            "preprocess_sql": [],
            "clean_up_sql": [],
        }

        metrics = BIRDCriticMetrics("postgresql://localhost/test")
        result = metrics.evaluate_task(task, "SELECT id FROM large_table WHERE indexed = true")

        assert result.metric == "qep"

    @patch("agentic_dba.evaluation_metrics.TestCaseRunner")
    def test_manual_metric_override(self, mock_runner_class):
        # Override automatic selection
        mock_runner = MagicMock()
        mock_runner.__enter__.return_value = mock_runner
        mock_runner.__exit__.return_value = None
        mock_runner.execute_test_case.return_value = TestCaseResult(
            passed=True,
            details={},
        )
        mock_runner_class.return_value = mock_runner

        task = {
            "instance_id": 3,
            "category": "Query",
            "efficiency": False,
            "issue_sql": ["SELECT 1"],
            "preprocess_sql": [],
            "clean_up_sql": [],
        }

        metrics = BIRDCriticMetrics("postgresql://localhost/test")
        result = metrics.evaluate_task(task, "SELECT 1", metric_type="tcv")

        assert result.metric == "tcv"


class TestSoftEx:
    """Test soft_ex (Soft Execution Match) metric."""

    @patch("agentic_dba.evaluation_metrics.TestCaseRunner")
    def test_soft_ex_success(self, mock_runner_class):
        mock_runner = MagicMock()
        mock_runner.__enter__.return_value = mock_runner
        mock_runner.__exit__.return_value = None
        mock_runner.execute_test_case.return_value = TestCaseResult(
            passed=True,
            details={
                "predicted_result": {
                    "rows": [(1, "Alice"), (2, "Bob")],
                    "rowcount": 2,
                },
                "issue_sql_results": [],
            },
        )
        mock_runner_class.return_value = mock_runner

        task = {
            "instance_id": 0,
            "category": "Query",
            "query": "Get all users",
            "issue_sql": ["SELECT * FROM users"],
            "preprocess_sql": [],
            "clean_up_sql": [],
        }

        metrics = BIRDCriticMetrics("postgresql://localhost/test")
        result = metrics.soft_ex(task, "SELECT id, name FROM users")

        assert result.passed is True
        assert result.score == 1.0
        assert result.metric == "soft_ex"

    @patch("agentic_dba.evaluation_metrics.TestCaseRunner")
    def test_soft_ex_execution_failure(self, mock_runner_class):
        mock_runner = MagicMock()
        mock_runner.__enter__.return_value = mock_runner
        mock_runner.__exit__.return_value = None
        mock_runner.execute_test_case.return_value = TestCaseResult(
            passed=False,
            error="SQL syntax error",
            details={},
        )
        mock_runner_class.return_value = mock_runner

        task = {
            "instance_id": 1,
            "category": "Query",
            "query": "Invalid query",
            "issue_sql": ["INVALID SQL"],
            "preprocess_sql": [],
            "clean_up_sql": [],
        }

        metrics = BIRDCriticMetrics("postgresql://localhost/test")
        result = metrics.soft_ex(task, "INVALID SQL")

        assert result.passed is False
        assert result.score == 0.0
        assert "SQL syntax error" in result.error

    @patch("agentic_dba.evaluation_metrics.TestCaseRunner")
    def test_soft_ex_empty_result(self, mock_runner_class):
        mock_runner = MagicMock()
        mock_runner.__enter__.return_value = mock_runner
        mock_runner.__exit__.return_value = None
        mock_runner.execute_test_case.return_value = TestCaseResult(
            passed=True,
            details={
                "predicted_result": {
                    "rows": [],
                    "rowcount": 0,
                },
            },
        )
        mock_runner_class.return_value = mock_runner

        task = {
            "instance_id": 2,
            "category": "Query",
            "query": "Get filtered users",
            "issue_sql": ["SELECT * FROM users WHERE false"],
            "preprocess_sql": [],
            "clean_up_sql": [],
        }

        metrics = BIRDCriticMetrics("postgresql://localhost/test")
        result = metrics.soft_ex(task, "SELECT * FROM users WHERE false")

        assert result.passed is True  # Empty result is valid
        assert result.details["predicted_rowcount"] == 0


class TestTestCaseValidation:
    """Test tcv (Test Case Validation) metric."""

    @patch("agentic_dba.evaluation_metrics.TestCaseRunner")
    def test_tcv_success(self, mock_runner_class):
        mock_runner = MagicMock()
        mock_runner.__enter__.return_value = mock_runner
        mock_runner.__exit__.return_value = None
        mock_runner.execute_test_case.return_value = TestCaseResult(
            passed=True,
            details={
                "preprocess_success": True,
                "predicted_result": {"rowcount": 1},
                "cleanup_success": True,
            },
        )
        mock_runner_class.return_value = mock_runner

        task = {
            "instance_id": 0,
            "category": "Management",
            "query": "Create table",
            "issue_sql": ["CREATE TABLE test (id INT)"],
            "preprocess_sql": ["DROP TABLE IF EXISTS test"],
            "clean_up_sql": ["DROP TABLE test"],
        }

        metrics = BIRDCriticMetrics("postgresql://localhost/test")
        result = metrics.test_case_validation(task, "CREATE TABLE test (id INT)")

        assert result.passed is True
        assert result.score == 1.0
        assert result.metric == "tcv"
        assert result.details["workflow_complete"] is True

    @patch("agentic_dba.evaluation_metrics.TestCaseRunner")
    def test_tcv_failure(self, mock_runner_class):
        mock_runner = MagicMock()
        mock_runner.__enter__.return_value = mock_runner
        mock_runner.__exit__.return_value = None
        mock_runner.execute_test_case.return_value = TestCaseResult(
            passed=False,
            error="Table already exists",
            details={"preprocess_success": True},
        )
        mock_runner_class.return_value = mock_runner

        task = {
            "instance_id": 1,
            "category": "Management",
            "query": "Create duplicate table",
            "issue_sql": ["CREATE TABLE test (id INT)"],
            "preprocess_sql": [],
            "clean_up_sql": [],
        }

        metrics = BIRDCriticMetrics("postgresql://localhost/test")
        result = metrics.test_case_validation(task, "CREATE TABLE test (id INT)")

        assert result.passed is False
        assert result.score == 0.0
        assert "Table already exists" in result.error


class TestQEPComparison:
    """Test qep (Query Execution Plan) comparison metric."""

    @patch("agentic_dba.evaluation_metrics.TestCaseRunner")
    def test_qep_improvement(self, mock_runner_class):
        mock_runner = MagicMock()
        mock_runner.__enter__.return_value = mock_runner
        mock_runner.__exit__.return_value = None

        # Mock test case execution
        mock_runner.execute_test_case.return_value = TestCaseResult(
            passed=True,
            details={},
        )

        # Mock EXPLAIN ANALYZE results
        # Predicted SQL has lower cost (improvement)
        mock_runner.execute_explain_analyze.side_effect = [
            {  # Predicted SQL
                "success": True,
                "total_cost": 50.0,
                "execution_time": 10.0,
                "planning_time": 0.5,
            },
            {  # Issue SQL
                "success": True,
                "total_cost": 100.0,
                "execution_time": 25.0,
                "planning_time": 0.5,
            },
        ]

        mock_runner_class.return_value = mock_runner

        task = {
            "instance_id": 0,
            "category": "Efficiency",
            "efficiency": True,
            "query": "Optimize query",
            "issue_sql": ["SELECT * FROM large_table"],
            "preprocess_sql": [],
            "clean_up_sql": [],
        }

        metrics = BIRDCriticMetrics("postgresql://localhost/test")
        result = metrics.qep_comparison(
            task,
            "SELECT id FROM large_table WHERE indexed = true"
        )

        assert result.passed is True  # 50/100 = 0.5 < 0.9 threshold
        assert result.score > 0.0
        assert result.details["cost_improvement_pct"] == 50.0
        assert result.details["cost_ratio"] == 0.5

    @patch("agentic_dba.evaluation_metrics.TestCaseRunner")
    def test_qep_no_improvement(self, mock_runner_class):
        mock_runner = MagicMock()
        mock_runner.__enter__.return_value = mock_runner
        mock_runner.__exit__.return_value = None

        mock_runner.execute_test_case.return_value = TestCaseResult(
            passed=True,
            details={},
        )

        # Predicted SQL has higher cost (no improvement)
        mock_runner.execute_explain_analyze.side_effect = [
            {  # Predicted SQL
                "success": True,
                "total_cost": 100.0,
                "execution_time": 25.0,
            },
            {  # Issue SQL
                "success": True,
                "total_cost": 50.0,
                "execution_time": 10.0,
            },
        ]

        mock_runner_class.return_value = mock_runner

        task = {
            "instance_id": 1,
            "category": "Efficiency",
            "efficiency": True,
            "query": "Worse query",
            "issue_sql": ["SELECT id FROM indexed_table"],
            "preprocess_sql": [],
            "clean_up_sql": [],
        }

        metrics = BIRDCriticMetrics("postgresql://localhost/test")
        result = metrics.qep_comparison(
            task,
            "SELECT * FROM indexed_table"
        )

        assert result.passed is False  # 100/50 = 2.0 > 0.9 threshold
        assert result.score == 0.0
        assert result.details["cost_ratio"] == 2.0

    @patch("agentic_dba.evaluation_metrics.TestCaseRunner")
    def test_qep_issue_sql_fails(self, mock_runner_class):
        # If issue_sql fails but predicted succeeds, that's an improvement
        mock_runner = MagicMock()
        mock_runner.__enter__.return_value = mock_runner
        mock_runner.__exit__.return_value = None

        mock_runner.execute_test_case.return_value = TestCaseResult(
            passed=True,
            details={},
        )

        mock_runner.execute_explain_analyze.side_effect = [
            {  # Predicted SQL
                "success": True,
                "total_cost": 50.0,
                "execution_time": 10.0,
            },
            {  # Issue SQL fails
                "success": False,
                "error": "Syntax error",
            },
        ]

        mock_runner_class.return_value = mock_runner

        task = {
            "instance_id": 2,
            "category": "Efficiency",
            "efficiency": True,
            "query": "Fix broken query",
            "issue_sql": ["INVALID SQL"],
            "preprocess_sql": [],
            "clean_up_sql": [],
        }

        metrics = BIRDCriticMetrics("postgresql://localhost/test")
        result = metrics.qep_comparison(task, "SELECT id FROM table")

        assert result.passed is True
        assert result.score == 1.0
        assert result.details["issue_sql_failed"] is True


class TestCompareResultSets:
    """Test compare_result_sets static method."""

    def test_identical_results(self):
        actual = [(1, "Alice"), (2, "Bob")]
        expected = [(1, "Alice"), (2, "Bob")]

        assert BIRDCriticMetrics.compare_result_sets(actual, expected)

    def test_unordered_results(self):
        actual = [(2, "Bob"), (1, "Alice")]
        expected = [(1, "Alice"), (2, "Bob")]

        # Should pass without order sensitivity
        assert BIRDCriticMetrics.compare_result_sets(
            actual, expected, order_sensitive=False
        )

        # Should fail with order sensitivity
        assert not BIRDCriticMetrics.compare_result_sets(
            actual, expected, order_sensitive=True
        )

    def test_different_row_counts(self):
        actual = [(1, "Alice")]
        expected = [(1, "Alice"), (2, "Bob")]

        assert not BIRDCriticMetrics.compare_result_sets(actual, expected)

    def test_floating_point_tolerance(self):
        actual = [(1, 3.14159)]
        expected = [(1, 3.14160)]

        # Should fail with zero tolerance
        assert not BIRDCriticMetrics.compare_result_sets(
            actual, expected, tolerance=0.0
        )

        # Should pass with tolerance
        assert BIRDCriticMetrics.compare_result_sets(
            actual, expected, tolerance=0.001
        )

    def test_null_handling(self):
        actual = [(1, None), (2, "Bob")]
        expected = [(1, None), (2, "Bob")]

        assert BIRDCriticMetrics.compare_result_sets(actual, expected)

        # Different null patterns
        actual = [(1, None)]
        expected = [(1, "Alice")]

        assert not BIRDCriticMetrics.compare_result_sets(actual, expected)

    def test_empty_results(self):
        assert BIRDCriticMetrics.compare_result_sets([], [])
        assert BIRDCriticMetrics.compare_result_sets(None, None)
        assert not BIRDCriticMetrics.compare_result_sets([(1,)], [])


class TestBatchEvaluate:
    """Test batch_evaluate function."""

    @patch("agentic_dba.evaluation_metrics.TestCaseRunner")
    def test_batch_evaluate_multiple_tasks(self, mock_runner_class):
        mock_runner = MagicMock()
        mock_runner.__enter__.return_value = mock_runner
        mock_runner.__exit__.return_value = None
        mock_runner.execute_test_case.return_value = TestCaseResult(
            passed=True,
            details={"predicted_result": {"rows": [(1,)]}},
        )
        mock_runner_class.return_value = mock_runner

        tasks = [
            {
                "instance_id": 0,
                "category": "Query",
                "issue_sql": ["SELECT 1"],
                "preprocess_sql": [],
                "clean_up_sql": [],
            },
            {
                "instance_id": 1,
                "category": "Query",
                "issue_sql": ["SELECT 2"],
                "preprocess_sql": [],
                "clean_up_sql": [],
            },
        ]

        predicted_sql_map = {
            "0": "SELECT 1",
            "1": "SELECT 2",
        }

        results = batch_evaluate(
            tasks=tasks,
            predicted_sql_map=predicted_sql_map,
            db_connection_string="postgresql://localhost/test",
        )

        assert len(results) == 2
        assert all(r.passed for r in results)

    @patch("agentic_dba.evaluation_metrics.TestCaseRunner")
    def test_batch_evaluate_missing_prediction(self, mock_runner_class):
        tasks = [
            {
                "instance_id": 0,
                "category": "Query",
                "issue_sql": ["SELECT 1"],
                "preprocess_sql": [],
                "clean_up_sql": [],
            },
        ]

        predicted_sql_map = {}  # Missing prediction for task 0

        results = batch_evaluate(
            tasks=tasks,
            predicted_sql_map=predicted_sql_map,
            db_connection_string="postgresql://localhost/test",
        )

        assert len(results) == 1
        assert results[0].passed is False
        assert "No predicted SQL" in results[0].error
