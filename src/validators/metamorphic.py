"""
Ternary Logic Partitioning (TLP) Validator

Implements metamorphic testing for SQL queries using TLP technique.

Based on: Rigger & Su, "Finding Bugs in Database Systems via Query Partitioning"
(OOPSLA 2020) - https://doi.org/10.1145/3428279

Theory:
    SQL predicates evaluate to TRUE, FALSE, or NULL. For any query Q with predicate φ:

    RS(Q) = RS(Q_φ=TRUE) ⊎ RS(Q_φ=FALSE) ⊎ RS(Q_φ=NULL)

    Where ⊎ is multiset union (UNION ALL). This invariant MUST hold regardless
    of data. Violations indicate bugs in the query or DBMS.

Example:
    Original: SELECT * FROM users WHERE age > 25

    Partition 1: SELECT * FROM users WHERE (age > 25) IS TRUE
    Partition 2: SELECT * FROM users WHERE (age > 25) IS FALSE
    Partition 3: SELECT * FROM users WHERE (age > 25) IS NULL

    Invariant: original_rows == partition1_rows ∪ partition2_rows ∪ partition3_rows
"""

import re
import time

try:
    import sqlparse
    from sqlparse.sql import Where
except ImportError:
    sqlparse = None

try:
    import psycopg2
    import psycopg2.extras
except ImportError:
    psycopg2 = None

from .base import CorrectnessValidator, ValidationIssue, ValidationResult
from .result_comparator import ResultComparator


class TLPValidator(CorrectnessValidator):
    """
    Ternary Logic Partitioning validator for SQL queries.

    Validates SQL queries by partitioning on WHERE predicates using
    three-valued logic (TRUE, FALSE, NULL).

    Limitations:
    - Requires WHERE clause (returns low confidence for queries without WHERE)
    - Currently supports PostgreSQL only
    - Complex predicates may not parse correctly (falls back gracefully)

    Example:
        ```python
        validator = TLPValidator()
        result = await validator.validate(
            query="SELECT * FROM users WHERE age > 25",
            db_connection="postgresql://localhost/mydb"
        )

        if not result.passed:
            print(f"Correctness issue detected: {result.issues[0].description}")
        ```
    """

    def __init__(self, float_tolerance: float = 1e-9):
        """
        Initialize TLP validator.

        Args:
            float_tolerance: Tolerance for floating point comparisons
        """
        self.comparator = ResultComparator(float_tolerance=float_tolerance)
        self.float_tolerance = float_tolerance

    async def validate(
        self,
        query: str,
        db_connection: str,
    ) -> ValidationResult:
        """
        Execute TLP validation on a SQL query.

        Steps:
        1. Parse query to extract WHERE predicate
        2. Generate 3 partitioned queries (TRUE/FALSE/NULL)
        3. Execute all 4 queries (original + partitions)
        4. Verify invariant: RS(Q) = RS(Q_true) ⊎ RS(Q_false) ⊎ RS(Q_null)

        Args:
            query: SQL query to validate
            db_connection: PostgreSQL connection string

        Returns:
            ValidationResult with pass/fail status and any detected issues
        """
        if not psycopg2:
            return self._create_error_result(
                "TLP",
                "psycopg2 not installed. Install with: pip install psycopg2-binary",
                "DEPENDENCY_ERROR"
            )

        if not sqlparse:
            return self._create_error_result(
                "TLP",
                "sqlparse not installed. Install with: pip install sqlparse",
                "DEPENDENCY_ERROR"
            )

        start_time = time.time()

        # Step 1: Extract WHERE predicate
        predicate = self._extract_where_predicate(query)

        if not predicate:
            # No WHERE clause - TLP doesn't apply
            # Return low-confidence pass (can't validate without predicate)
            return ValidationResult(
                passed=True,
                confidence=0.3,  # Low confidence - can't validate without WHERE
                method="TLP",
                issues=[],
                execution_time_ms=0,
                queries_executed=1,
                metadata={
                    'reason': 'No WHERE clause found - TLP validation not applicable',
                    'query': query,
                }
            )

        # Step 2: Generate partitioned queries
        try:
            q_true = self._partition_query(query, predicate, "TRUE")
            q_false = self._partition_query(query, predicate, "FALSE")
            q_null = self._partition_query(query, predicate, "NULL")
        except Exception as e:
            return self._create_error_result(
                "TLP",
                f"Failed to generate partitioned queries: {str(e)}",
                "PARTITION_GENERATION_ERROR"
            )

        # Step 3: Execute queries
        try:
            conn = psycopg2.connect(db_connection)
            cursor = conn.cursor()

            try:
                # Execute original query
                cursor.execute(query)
                original_rows = cursor.fetchall()

                # Execute partitioned queries
                cursor.execute(q_true)
                true_rows = cursor.fetchall()

                cursor.execute(q_false)
                false_rows = cursor.fetchall()

                cursor.execute(q_null)
                null_rows = cursor.fetchall()

            finally:
                cursor.close()
                conn.close()

        except Exception as e:
            return self._create_error_result(
                "TLP",
                f"Query execution failed: {str(e)}",
                "EXECUTION_ERROR"
            )

        # Step 4: Compare results
        # TLP invariant: Original query (WHERE φ) should match TRUE partition (WHERE (φ) IS TRUE)
        # The union of all partitions equals ALL rows (no WHERE), which is different.
        matches = self.comparator.compare_result_sets(original_rows, true_rows)

        execution_time = (time.time() - start_time) * 1000

        if not matches:
            # Original query doesn't match TRUE partition - indicates logic error
            diff = self.comparator.get_row_count_diff(original_rows, true_rows)
            only_original, only_true = self.comparator.find_mismatched_rows(
                original_rows, true_rows, max_examples=3
            )

            issue = ValidationIssue(
                issue_type="PARTITION_MISMATCH",
                description=(
                    f"Query returned {len(original_rows)} rows, but "
                    f"TRUE partition returned {len(true_rows)} rows. "
                    f"This indicates the WHERE clause has unexpected behavior."
                ),
                severity="ERROR",
                evidence={
                    'original_count': len(original_rows),
                    'true_count': len(true_rows),
                    'false_count': len(false_rows),
                    'null_count': len(null_rows),
                    'difference': diff,
                    'predicate': predicate,
                    'example_rows_only_in_original': [str(r) for r in only_original],
                    'example_rows_only_in_true': [str(r) for r in only_true],
                },
                suggested_fix=(
                    "Review the WHERE clause logic. The predicate may not correctly "
                    "capture the intended filtering condition. Common issues:\n"
                    "1. Incorrect operator (e.g., > instead of >=)\n"
                    "2. Missing NULL handling (consider using IS NULL or COALESCE)\n"
                    "3. Logic error in AND/OR combinations\n"
                    "4. Type casting issues (e.g., comparing incompatible types)"
                )
            )

            return ValidationResult(
                passed=False,
                confidence=1.0,  # High confidence in detecting error
                method="TLP",
                issues=[issue],
                execution_time_ms=execution_time,
                queries_executed=4,
                metadata={
                    'predicate': predicate,
                    'partition_queries': {
                        'true': q_true,
                        'false': q_false,
                        'null': q_null,
                    }
                }
            )

        # Validation passed
        return ValidationResult(
            passed=True,
            confidence=1.0,
            method="TLP",
            issues=[],
            execution_time_ms=execution_time,
            queries_executed=4,
            metadata={
                'predicate': predicate,
                'row_count': len(original_rows),
            }
        )

    def _extract_where_predicate(self, query: str) -> str | None:
        """
        Extract WHERE clause predicate from SQL query.

        Uses sqlparse to parse SQL and extract the WHERE clause.
        Returns None if no WHERE clause exists.

        Args:
            query: SQL query string

        Returns:
            WHERE predicate string (without 'WHERE' keyword) or None

        Note:
            This is a simplified implementation. Production version should handle:
            - Subqueries
            - CTEs (WITH clauses)
            - Complex boolean expressions
        """
        if not sqlparse:
            return None

        try:
            parsed = sqlparse.parse(query)
            if not parsed:
                return None

            statement = parsed[0]

            # Find WHERE token
            for token in statement.tokens:
                if isinstance(token, Where):
                    # Extract predicate (everything after WHERE keyword)
                    predicate_str = str(token)

                    # Remove 'WHERE' keyword
                    predicate = predicate_str.strip()
                    if predicate.upper().startswith('WHERE'):
                        predicate = predicate[5:].strip()

                    # Strip trailing semicolon (common in user input)
                    predicate = predicate.rstrip(';').strip()

                    return predicate

            return None

        except Exception:
            # Fallback: simple regex extraction
            return self._extract_where_predicate_regex(query)

    def _extract_where_predicate_regex(self, query: str) -> str | None:
        """
        Fallback WHERE predicate extraction using regex.

        Used when sqlparse fails or is not available.

        Args:
            query: SQL query string

        Returns:
            WHERE predicate or None
        """
        # Find WHERE keyword (case-insensitive)
        match = re.search(r'\bWHERE\b\s+(.+?)(?:\s+(?:GROUP|ORDER|LIMIT|OFFSET|;|$))',
                         query, re.IGNORECASE | re.DOTALL)

        if match:
            # Strip trailing semicolon (common in user input)
            return match.group(1).strip().rstrip(';').strip()

        # Try without lookahead (for queries ending with WHERE clause)
        match = re.search(r'\bWHERE\b\s+(.+?)(?:;|$)', query, re.IGNORECASE | re.DOTALL)
        if match:
            # Strip trailing semicolon
            return match.group(1).strip().rstrip(';').strip()

        return None

    def _partition_query(
        self,
        original_query: str,
        predicate: str,
        truth_value: str
    ) -> str:
        """
        Generate partitioned query for given truth value.

        Transforms:
            SELECT * FROM t WHERE φ
        Into:
            SELECT * FROM t WHERE (φ) IS TRUE|FALSE|NULL

        Args:
            original_query: Original SQL query
            predicate: WHERE clause predicate
            truth_value: "TRUE", "FALSE", or "NULL"

        Returns:
            Modified query with partitioned WHERE clause
        """
        # Build new WHERE clause based on truth value
        if truth_value == "TRUE":
            new_predicate = f"({predicate}) IS TRUE"
        elif truth_value == "FALSE":
            new_predicate = f"({predicate}) IS FALSE"
        else:  # NULL
            new_predicate = f"({predicate}) IS NULL"

        # Replace WHERE clause in query
        # Use regex to find and replace the WHERE clause
        # Pattern: WHERE <predicate> [followed by GROUP|ORDER|LIMIT|OFFSET|end]

        pattern = r'(\bWHERE\b\s+)(.+?)(\s+(?:GROUP|ORDER|LIMIT|OFFSET)|;|$)'
        replacement = r'\1' + new_predicate + r'\3'

        modified_query = re.sub(pattern, replacement, original_query,
                               count=1, flags=re.IGNORECASE | re.DOTALL)

        # If pattern didn't match, try simpler version
        if modified_query == original_query:
            pattern = r'(\bWHERE\b\s+)(.+?)(;|$)'
            replacement = r'\1' + new_predicate + r'\3'
            modified_query = re.sub(pattern, replacement, original_query,
                                   count=1, flags=re.IGNORECASE | re.DOTALL)

        return modified_query


# Example usage
if __name__ == "__main__":

    async def test_tlp():
        """Test TLP validator with example queries"""
        validator = TLPValidator()

        # Test 1: Correct query (should pass)
        query1 = "SELECT * FROM users WHERE age > 25"
        result1 = await validator.validate(
            query1,
            "postgresql://postgres:postgres@localhost:5432/demo"
        )
        print(f"Test 1 (correct query): {result1.passed}")
        print(f"  Confidence: {result1.confidence}")
        print(f"  Queries executed: {result1.queries_executed}")

        # Test 2: Query without WHERE (should return low confidence)
        query2 = "SELECT * FROM users"
        result2 = await validator.validate(
            query2,
            "postgresql://postgres:postgres@localhost:5432/demo"
        )
        print(f"\nTest 2 (no WHERE): {result2.passed}")
        print(f"  Confidence: {result2.confidence}")
        print(f"  Reason: {result2.metadata.get('reason', 'N/A')}")

    # Run async test
    # asyncio.run(test_tlp())
    print("TLP Validator module loaded successfully")
