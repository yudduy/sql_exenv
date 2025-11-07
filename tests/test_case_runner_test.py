"""
Unit tests for TestCaseRunner

Tests the test case execution framework with:
- Transaction isolation
- Multi-statement execution
- Preprocess/cleanup workflow
- Error handling
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
from psycopg2 import Error as Psycopg2Error, ProgrammingError

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from agentic_dba.test_case_runner import (
    TestCaseRunner,
    TestCaseResult,
    ExecutionResult,
)


class TestExecutionResult:
    """Test ExecutionResult dataclass."""

    def test_success_result(self):
        result = ExecutionResult(
            success=True,
            rows=[("data",)],
            rowcount=1,
            execution_time_ms=10.5,
        )

        assert result.success is True
        assert result.rows == [("data",)]
        assert result.rowcount == 1
        assert result.execution_time_ms == 10.5
        assert result.error is None

    def test_error_result(self):
        result = ExecutionResult(
            success=False,
            error="Syntax error",
            error_type="SyntaxError",
        )

        assert result.success is False
        assert result.error == "Syntax error"
        assert result.error_type == "SyntaxError"
        assert result.rows is None


class TestTestCaseResult:
    """Test TestCaseResult dataclass."""

    def test_passed_result(self):
        result = TestCaseResult(
            passed=True,
            details={"rowcount": 5},
        )

        assert result.passed is True
        assert result.error is None
        assert result.details == {"rowcount": 5}

    def test_failed_result(self):
        result = TestCaseResult(
            passed=False,
            error="SQL execution failed",
            details={"error_type": "SyntaxError"},
        )

        assert result.passed is False
        assert result.error == "SQL execution failed"
        assert result.details == {"error_type": "SyntaxError"}


class TestTestCaseRunnerInit:
    """Test TestCaseRunner initialization."""

    def test_init_with_defaults(self):
        runner = TestCaseRunner("postgresql://localhost/test")

        assert runner.db_connection_string == "postgresql://localhost/test"
        assert runner.auto_rollback is True
        assert runner.enable_explain is False

    def test_init_with_custom_options(self):
        runner = TestCaseRunner(
            "postgresql://localhost/test",
            auto_rollback=False,
            enable_explain=True,
        )

        assert runner.auto_rollback is False
        assert runner.enable_explain is True


class TestTestCaseRunnerContextManager:
    """Test TestCaseRunner as context manager."""

    @patch("agentic_dba.test_case_runner.psycopg2.connect")
    def test_context_manager_enter_exit(self, mock_connect):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_connect.return_value = mock_conn

        with TestCaseRunner("postgresql://localhost/test") as runner:
            assert runner._conn == mock_conn
            assert runner._cursor == mock_cursor

        mock_cursor.close.assert_called_once()
        mock_conn.close.assert_called_once()

    @patch("agentic_dba.test_case_runner.psycopg2.connect")
    def test_context_manager_sets_isolation_level(self, mock_connect):
        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn

        with TestCaseRunner("postgresql://localhost/test"):
            mock_conn.set_isolation_level.assert_called_once()


class TestExecuteSQL:
    """Test _execute_sql method."""

    @patch("agentic_dba.test_case_runner.psycopg2.connect")
    def test_execute_select_query(self, mock_connect):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_connect.return_value = mock_conn

        # Mock SELECT query response
        mock_cursor.description = [("id",), ("name",)]
        mock_cursor.fetchall.return_value = [(1, "Alice"), (2, "Bob")]
        mock_cursor.rowcount = 2

        with TestCaseRunner("postgresql://localhost/test") as runner:
            result = runner._execute_sql("SELECT * FROM users")

        assert result.success is True
        assert result.rows == [(1, "Alice"), (2, "Bob")]
        assert result.rowcount == 2
        assert result.execution_time_ms is not None

    @patch("agentic_dba.test_case_runner.psycopg2.connect")
    def test_execute_dml_query(self, mock_connect):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_connect.return_value = mock_conn

        # Mock INSERT/UPDATE/DELETE response
        mock_cursor.description = None  # No result set
        mock_cursor.rowcount = 3

        with TestCaseRunner("postgresql://localhost/test") as runner:
            result = runner._execute_sql("DELETE FROM users WHERE active = false")

        assert result.success is True
        assert result.rows is None
        assert result.rowcount == 3

    @patch("agentic_dba.test_case_runner.psycopg2.connect")
    def test_execute_sql_with_error(self, mock_connect):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_connect.return_value = mock_conn

        # Mock SQL error
        mock_cursor.execute.side_effect = Psycopg2Error("relation does not exist")

        with TestCaseRunner("postgresql://localhost/test") as runner:
            result = runner._execute_sql("SELECT * FROM nonexistent")

        assert result.success is False
        assert "relation does not exist" in result.error
        assert result.error_type == "Error"


class TestExecuteTestCase:
    """Test execute_test_case method."""

    @patch("agentic_dba.test_case_runner.psycopg2.connect")
    def test_simple_successful_execution(self, mock_connect):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_connect.return_value = mock_conn

        # Mock successful query execution
        mock_cursor.description = [("count",)]
        mock_cursor.fetchall.return_value = [(5,)]
        mock_cursor.rowcount = 1

        task = {
            "instance_id": 0,
            "db_id": "test_db",
            "query": "Count users",
            "issue_sql": ["SELECT COUNT(*) FROM users"],
            "preprocess_sql": [],
            "clean_up_sql": [],
        }

        with TestCaseRunner("postgresql://localhost/test") as runner:
            result = runner.execute_test_case(
                task=task,
                predicted_sql="SELECT COUNT(*) FROM users",
                compare_with_issue_sql=False,
            )

        assert result.passed is True
        assert result.error is None
        assert result.details["instance_id"] == 0
        assert result.details["db_id"] == "test_db"

    @patch("agentic_dba.test_case_runner.psycopg2.connect")
    def test_execution_with_preprocess(self, mock_connect):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_connect.return_value = mock_conn

        # Mock successful execution
        mock_cursor.description = [("result",)]
        mock_cursor.fetchall.return_value = [(1,)]

        task = {
            "instance_id": 1,
            "db_id": "test_db",
            "query": "Test with setup",
            "issue_sql": ["SELECT 1"],
            "preprocess_sql": [
                "CREATE TEMP TABLE temp_data AS SELECT 1",
                "INSERT INTO temp_data VALUES (2)",
            ],
            "clean_up_sql": ["DROP TABLE IF EXISTS temp_data"],
        }

        with TestCaseRunner("postgresql://localhost/test") as runner:
            result = runner.execute_test_case(
                task=task,
                predicted_sql="SELECT * FROM temp_data",
                compare_with_issue_sql=False,
            )

        assert result.passed is True
        assert result.details["preprocess_count"] == 2
        assert result.details["cleanup_count"] == 1

    @patch("agentic_dba.test_case_runner.psycopg2.connect")
    def test_execution_with_preprocess_failure(self, mock_connect):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_connect.return_value = mock_conn

        # First execute (BEGIN) succeeds, second (preprocess) fails
        mock_cursor.execute.side_effect = [
            None,  # BEGIN
            Psycopg2Error("syntax error"),  # preprocess[0]
        ]

        task = {
            "instance_id": 2,
            "db_id": "test_db",
            "query": "Test with failing setup",
            "issue_sql": ["SELECT 1"],
            "preprocess_sql": ["INVALID SQL"],
            "clean_up_sql": [],
        }

        with TestCaseRunner("postgresql://localhost/test") as runner:
            result = runner.execute_test_case(
                task=task,
                predicted_sql="SELECT 1",
                compare_with_issue_sql=False,
            )

        assert result.passed is False
        assert "Preprocess SQL [0] failed" in result.error

    @patch("agentic_dba.test_case_runner.psycopg2.connect")
    def test_execution_with_predicted_sql_failure(self, mock_connect):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_connect.return_value = mock_conn

        # BEGIN succeeds, predicted SQL fails
        mock_cursor.execute.side_effect = [
            None,  # BEGIN
            Psycopg2Error("column does not exist"),  # predicted SQL
        ]

        task = {
            "instance_id": 3,
            "db_id": "test_db",
            "query": "Test with invalid query",
            "issue_sql": ["SELECT invalid_column FROM users"],
            "preprocess_sql": [],
            "clean_up_sql": [],
        }

        with TestCaseRunner("postgresql://localhost/test") as runner:
            result = runner.execute_test_case(
                task=task,
                predicted_sql="SELECT invalid_column FROM users",
                compare_with_issue_sql=False,
            )

        assert result.passed is False
        assert "Predicted SQL failed" in result.error

    @patch("agentic_dba.test_case_runner.psycopg2.connect")
    def test_execution_with_issue_sql_comparison(self, mock_connect):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_connect.return_value = mock_conn

        # Mock both predicted and issue_sql execution
        mock_cursor.description = [("count",)]
        mock_cursor.fetchall.return_value = [(5,)]
        mock_cursor.rowcount = 1

        task = {
            "instance_id": 4,
            "db_id": "test_db",
            "query": "Compare predictions",
            "issue_sql": ["SELECT COUNT(*) FROM users WHERE active = true"],
            "preprocess_sql": [],
            "clean_up_sql": [],
        }

        with TestCaseRunner("postgresql://localhost/test") as runner:
            result = runner.execute_test_case(
                task=task,
                predicted_sql="SELECT COUNT(*) FROM users",
                compare_with_issue_sql=True,
            )

        assert result.passed is True
        assert "issue_sql_results" in result.details
        assert len(result.details["issue_sql_results"]) == 1

    @patch("agentic_dba.test_case_runner.psycopg2.connect")
    def test_transaction_rollback(self, mock_connect):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_connect.return_value = mock_conn

        mock_cursor.description = [("result",)]
        mock_cursor.fetchall.return_value = [(1,)]

        task = {
            "instance_id": 5,
            "db_id": "test_db",
            "query": "Test rollback",
            "issue_sql": ["SELECT 1"],
            "preprocess_sql": [],
            "clean_up_sql": [],
        }

        with TestCaseRunner(
            "postgresql://localhost/test",
            auto_rollback=True,
        ) as runner:
            result = runner.execute_test_case(
                task=task,
                predicted_sql="SELECT 1",
                compare_with_issue_sql=False,
            )

        # Verify ROLLBACK was called
        rollback_calls = [
            call for call in mock_cursor.execute.call_args_list
            if "ROLLBACK" in str(call)
        ]
        assert len(rollback_calls) > 0

    @patch("agentic_dba.test_case_runner.psycopg2.connect")
    def test_transaction_commit(self, mock_connect):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_connect.return_value = mock_conn

        mock_cursor.description = [("result",)]
        mock_cursor.fetchall.return_value = [(1,)]

        task = {
            "instance_id": 6,
            "db_id": "test_db",
            "query": "Test commit",
            "issue_sql": ["SELECT 1"],
            "preprocess_sql": [],
            "clean_up_sql": [],
        }

        with TestCaseRunner(
            "postgresql://localhost/test",
            auto_rollback=False,  # Commit instead
        ) as runner:
            result = runner.execute_test_case(
                task=task,
                predicted_sql="SELECT 1",
                compare_with_issue_sql=False,
            )

        # Verify COMMIT was called
        commit_calls = [
            call for call in mock_cursor.execute.call_args_list
            if "COMMIT" in str(call)
        ]
        assert len(commit_calls) > 0


class TestValidateResults:
    """Test validate_results method."""

    @patch("agentic_dba.test_case_runner.psycopg2.connect")
    def test_validate_identical_results(self, mock_connect):
        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn

        with TestCaseRunner("postgresql://localhost/test") as runner:
            actual = [(1, "Alice"), (2, "Bob")]
            expected = [(1, "Alice"), (2, "Bob")]

            assert runner.validate_results(actual, expected, order_sensitive=True)

    @patch("agentic_dba.test_case_runner.psycopg2.connect")
    def test_validate_unordered_results(self, mock_connect):
        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn

        with TestCaseRunner("postgresql://localhost/test") as runner:
            actual = [(2, "Bob"), (1, "Alice")]
            expected = [(1, "Alice"), (2, "Bob")]

            # Should pass with order_sensitive=False
            assert runner.validate_results(actual, expected, order_sensitive=False)

            # Should fail with order_sensitive=True
            assert not runner.validate_results(actual, expected, order_sensitive=True)

    @patch("agentic_dba.test_case_runner.psycopg2.connect")
    def test_validate_different_row_counts(self, mock_connect):
        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn

        with TestCaseRunner("postgresql://localhost/test") as runner:
            actual = [(1, "Alice")]
            expected = [(1, "Alice"), (2, "Bob")]

            assert not runner.validate_results(actual, expected)

    @patch("agentic_dba.test_case_runner.psycopg2.connect")
    def test_validate_empty_results(self, mock_connect):
        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn

        with TestCaseRunner("postgresql://localhost/test") as runner:
            assert runner.validate_results([], [])
            assert runner.validate_results(None, None)
            assert not runner.validate_results([(1,)], [])


class TestExplainAnalyze:
    """Test execute_explain_analyze method."""

    @patch("agentic_dba.test_case_runner.psycopg2.connect")
    def test_explain_analyze_success(self, mock_connect):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_connect.return_value = mock_conn

        # Mock EXPLAIN ANALYZE output
        mock_cursor.fetchone.return_value = (
            [
                {
                    "Plan": {
                        "Total Cost": 100.50,
                        "Node Type": "Seq Scan",
                    },
                    "Execution Time": 15.234,
                    "Planning Time": 0.123,
                }
            ],
        )

        with TestCaseRunner("postgresql://localhost/test") as runner:
            result = runner.execute_explain_analyze("SELECT * FROM users")

        assert result["success"] is True
        assert result["total_cost"] == 100.50
        assert result["execution_time"] == 15.234
        assert result["planning_time"] == 0.123

    @patch("agentic_dba.test_case_runner.psycopg2.connect")
    def test_explain_analyze_failure(self, mock_connect):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_connect.return_value = mock_conn

        # Mock error
        mock_cursor.execute.side_effect = Psycopg2Error("invalid query")

        with TestCaseRunner("postgresql://localhost/test") as runner:
            result = runner.execute_explain_analyze("INVALID SQL")

        assert result["success"] is False
        assert "invalid query" in result["error"]
