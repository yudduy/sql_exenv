"""
BIRD-CRITIC Test Case Runner

Executes BIRD-CRITIC test cases with proper isolation using PostgreSQL transactions.
Supports preprocess/execute/cleanup workflow with rollback for safe testing.
"""

import logging
from dataclasses import dataclass
from typing import Dict, List, Any, Optional, Tuple
import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_READ_COMMITTED


logger = logging.getLogger(__name__)


@dataclass
class ExecutionResult:
    """Result from executing a SQL statement."""

    success: bool
    rows: Optional[List[Tuple]] = None
    rowcount: int = 0
    error: Optional[str] = None
    error_type: Optional[str] = None
    execution_time_ms: Optional[float] = None


@dataclass
class TestCaseResult:
    """Result from executing a complete test case."""

    passed: bool
    error: Optional[str] = None
    details: Dict[str, Any] = None

    def __post_init__(self):
        if self.details is None:
            self.details = {}


class TestCaseRunner:
    """
    Execute BIRD-CRITIC test cases with proper isolation.

    Uses PostgreSQL transactions to ensure each test case:
    1. Runs in isolation (ROLLBACK after completion)
    2. Can execute multiple SQL statements (issue_sql array)
    3. Handles preprocess/cleanup properly
    4. Captures detailed error information for debugging

    Example:
        runner = TestCaseRunner("postgresql://localhost/bird_db")
        task = {
            "instance_id": 0,
            "db_id": "financial",
            "query": "Find accounts with order variance > 12000",
            "issue_sql": ["SELECT account_id FROM loan WHERE ..."],
            "preprocess_sql": [],
            "clean_up_sql": []
        }
        result = runner.execute_test_case(task, predicted_sql)
        if result.passed:
            print("Test passed!")
    """

    def __init__(
        self,
        db_connection_string: str,
        auto_rollback: bool = True,
        enable_explain: bool = False,
    ):
        """
        Initialize the test case runner.

        Args:
            db_connection_string: PostgreSQL connection string
            auto_rollback: If True, automatically rollback after each test (default: True)
            enable_explain: If True, capture EXPLAIN ANALYZE for queries (default: False)
        """
        self.db_connection_string = db_connection_string
        self.auto_rollback = auto_rollback
        self.enable_explain = enable_explain
        self._conn = None
        self._cursor = None

    def __enter__(self):
        """Context manager entry - establish connection."""
        self._conn = psycopg2.connect(self.db_connection_string)
        self._conn.set_isolation_level(ISOLATION_LEVEL_READ_COMMITTED)
        self._cursor = self._conn.cursor()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - cleanup connection."""
        if self._cursor:
            self._cursor.close()
        if self._conn:
            self._conn.close()

    def execute_test_case(
        self,
        task: Dict[str, Any],
        predicted_sql: str,
        compare_with_issue_sql: bool = True,
    ) -> TestCaseResult:
        """
        Execute a BIRD-CRITIC test case with full isolation.

        Execution flow:
        1. BEGIN transaction
        2. Execute preprocess_sql (setup)
        3. Execute predicted_sql (agent's solution)
        4. If compare_with_issue_sql, execute issue_sql for comparison
        5. Execute clean_up_sql (teardown)
        6. ROLLBACK transaction (isolation)

        Args:
            task: BIRD-CRITIC task dictionary with:
                - instance_id: Task identifier
                - db_id: Database name
                - query: Natural language description
                - issue_sql: List of buggy SQL statements
                - preprocess_sql: List of setup queries
                - clean_up_sql: List of teardown queries
            predicted_sql: The SQL statement to test (agent's solution)
            compare_with_issue_sql: If True, execute issue_sql and compare results

        Returns:
            TestCaseResult with pass/fail status and details
        """
        # Ensure we have a connection
        if not self._conn or not self._cursor:
            return TestCaseResult(
                passed=False,
                error="No database connection. Use as context manager: with TestCaseRunner(...) as runner:",
            )

        details = {
            "instance_id": task.get("instance_id"),
            "db_id": task.get("db_id"),
            "category": task.get("category"),
            "preprocess_count": len(task.get("preprocess_sql", [])),
            "cleanup_count": len(task.get("clean_up_sql", [])),
            "issue_sql_count": len(task.get("issue_sql", [])),
        }

        try:
            # Step 1: Begin transaction
            self._cursor.execute("BEGIN")
            logger.debug(f"[Task {task.get('instance_id')}] Transaction started")

            # Step 2: Execute preprocess SQL (setup)
            preprocess_sql = task.get("preprocess_sql", [])
            if preprocess_sql:
                logger.debug(f"Executing {len(preprocess_sql)} preprocess statements")
                for i, sql in enumerate(preprocess_sql):
                    result = self._execute_sql(sql, f"preprocess[{i}]")
                    if not result.success:
                        return self._rollback_and_fail(
                            f"Preprocess SQL [{i}] failed: {result.error}",
                            details,
                        )
                details["preprocess_success"] = True

            # Step 3: Execute predicted SQL (agent's solution)
            logger.debug(f"Executing predicted SQL: {predicted_sql[:100]}...")
            predicted_result = self._execute_sql(predicted_sql, "predicted")

            if not predicted_result.success:
                return self._rollback_and_fail(
                    f"Predicted SQL failed: {predicted_result.error}",
                    details,
                    error_type=predicted_result.error_type,
                )

            details["predicted_result"] = {
                "rowcount": predicted_result.rowcount,
                "rows": predicted_result.rows[:10] if predicted_result.rows else None,  # First 10 rows
                "execution_time_ms": predicted_result.execution_time_ms,
            }

            # Step 4: Execute issue SQL (buggy queries) for comparison
            if compare_with_issue_sql:
                issue_sql_list = task.get("issue_sql", [])
                issue_results = []

                for i, issue_sql in enumerate(issue_sql_list):
                    logger.debug(f"Executing issue_sql[{i}]: {issue_sql[:100]}...")
                    issue_result = self._execute_sql(issue_sql, f"issue[{i}]")
                    issue_results.append({
                        "success": issue_result.success,
                        "rowcount": issue_result.rowcount,
                        "rows": issue_result.rows[:10] if issue_result.rows else None,
                        "error": issue_result.error,
                    })

                details["issue_sql_results"] = issue_results

            # Step 5: Execute cleanup SQL (teardown)
            clean_up_sql = task.get("clean_up_sql", [])
            if clean_up_sql:
                logger.debug(f"Executing {len(clean_up_sql)} cleanup statements")
                for i, sql in enumerate(clean_up_sql):
                    result = self._execute_sql(sql, f"cleanup[{i}]")
                    # Note: We don't fail on cleanup errors, just log them
                    if not result.success:
                        logger.warning(f"Cleanup SQL [{i}] failed: {result.error}")
                details["cleanup_success"] = True

            # Step 6: Rollback transaction (isolation)
            if self.auto_rollback:
                self._cursor.execute("ROLLBACK")
                logger.debug(f"[Task {task.get('instance_id')}] Transaction rolled back")
            else:
                self._cursor.execute("COMMIT")
                logger.debug(f"[Task {task.get('instance_id')}] Transaction committed")

            # Success!
            return TestCaseResult(
                passed=True,
                details=details,
            )

        except Exception as e:
            logger.exception(f"Unexpected error executing test case: {e}")
            return self._rollback_and_fail(
                f"Unexpected error: {type(e).__name__}: {e}",
                details,
            )

    def _execute_sql(
        self,
        sql: str,
        label: str = "query",
    ) -> ExecutionResult:
        """
        Execute a single SQL statement and capture results.

        Args:
            sql: SQL statement to execute
            label: Label for logging (e.g., "predicted", "issue[0]")

        Returns:
            ExecutionResult with success status and data
        """
        import time

        try:
            start_time = time.time()
            self._cursor.execute(sql)
            execution_time_ms = (time.time() - start_time) * 1000

            # Try to fetch results (for SELECT queries)
            rows = None
            rowcount = self._cursor.rowcount

            if self._cursor.description:  # Query returns data
                try:
                    rows = self._cursor.fetchall()
                    rowcount = len(rows)
                except psycopg2.ProgrammingError:
                    # Not a SELECT query, or already consumed
                    pass

            logger.debug(f"[{label}] Success - {rowcount} rows affected/returned")

            return ExecutionResult(
                success=True,
                rows=rows,
                rowcount=rowcount,
                execution_time_ms=execution_time_ms,
            )

        except psycopg2.Error as e:
            error_type = type(e).__name__
            error_msg = str(e).strip()

            logger.debug(f"[{label}] Failed - {error_type}: {error_msg}")

            return ExecutionResult(
                success=False,
                error=error_msg,
                error_type=error_type,
            )

        except Exception as e:
            error_type = type(e).__name__
            error_msg = str(e).strip()

            logger.error(f"[{label}] Unexpected error - {error_type}: {error_msg}")

            return ExecutionResult(
                success=False,
                error=error_msg,
                error_type=error_type,
            )

    def _rollback_and_fail(
        self,
        error_msg: str,
        details: Dict[str, Any],
        error_type: Optional[str] = None,
    ) -> TestCaseResult:
        """
        Rollback transaction and return failure result.

        Args:
            error_msg: Error message describing the failure
            details: Details dictionary to include in result
            error_type: Optional error type (e.g., "SyntaxError")

        Returns:
            TestCaseResult with passed=False
        """
        try:
            self._cursor.execute("ROLLBACK")
            logger.debug("Transaction rolled back after failure")
        except Exception as rollback_error:
            logger.error(f"Failed to rollback transaction: {rollback_error}")

        if error_type:
            details["error_type"] = error_type

        return TestCaseResult(
            passed=False,
            error=error_msg,
            details=details,
        )

    def validate_results(
        self,
        actual_rows: List[Tuple],
        expected_rows: List[Tuple],
        order_sensitive: bool = False,
    ) -> bool:
        """
        Compare query results for correctness.

        Args:
            actual_rows: Rows returned by the query being tested
            expected_rows: Expected rows (ground truth)
            order_sensitive: If True, compare rows in order (default: False)

        Returns:
            True if results match, False otherwise
        """
        # Handle None/empty cases
        if actual_rows is None:
            actual_rows = []
        if expected_rows is None:
            expected_rows = []

        # Check row count
        if len(actual_rows) != len(expected_rows):
            logger.debug(
                f"Row count mismatch: actual={len(actual_rows)}, expected={len(expected_rows)}"
            )
            return False

        # Compare contents
        if order_sensitive:
            # Direct comparison preserving order
            return actual_rows == expected_rows
        else:
            # Set-based comparison (ignore order)
            actual_set = set(actual_rows)
            expected_set = set(expected_rows)
            return actual_set == expected_set

    def execute_explain_analyze(self, sql: str) -> Dict[str, Any]:
        """
        Execute EXPLAIN ANALYZE for a query and return execution plan.

        Args:
            sql: SQL query to analyze

        Returns:
            Dictionary with execution plan details
        """
        if not self._conn or not self._cursor:
            return {"error": "No database connection"}

        try:
            explain_sql = f"EXPLAIN (ANALYZE, FORMAT JSON) {sql}"
            self._cursor.execute(explain_sql)
            plan = self._cursor.fetchone()[0][0]

            return {
                "success": True,
                "plan": plan,
                "total_cost": plan.get("Plan", {}).get("Total Cost"),
                "execution_time": plan.get("Execution Time"),
                "planning_time": plan.get("Planning Time"),
            }

        except Exception as e:
            logger.error(f"EXPLAIN ANALYZE failed: {e}")
            return {
                "success": False,
                "error": str(e),
            }
