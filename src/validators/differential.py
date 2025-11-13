"""
Non-optimizing Reference Engine Construction (NoREC) Validator

Implements differential testing for SQL query optimization.

Based on: Rigger & Su, "Detecting Optimization Bugs in Database Engines via
Non-optimizing Reference Engine Construction" (ESEC/FSE 2020)

Theory:
    Validates query optimization by comparing optimized execution against
    a non-optimizable variant that forces table scans. If results differ,
    the query planner has introduced an optimization bug.

Example:
    Original (optimized):
        SELECT * FROM users WHERE age > 25

    Non-optimizable variant (forces table scan):
        SELECT * FROM users WHERE (SELECT age > 25) = TRUE

    Invariant: Both queries must return the same row count.
    Violations indicate optimization bugs in the DBMS query planner.
"""

import time
import re
from typing import Optional

try:
    import psycopg2
    import psycopg2.extras
except ImportError:
    psycopg2 = None

from .base import CorrectnessValidator, ValidationResult, ValidationIssue
from .result_comparator import ResultComparator


class NoRECValidator(CorrectnessValidator):
    """
    Non-optimizing Reference Engine Construction validator.

    Validates query optimization by comparing optimized vs. non-optimized
    execution. Catches bugs where the query planner incorrectly uses
    indexes or join methods.

    Limitations:
    - Currently supports simple queries (single WHERE predicate)
    - May not work with complex subqueries or CTEs
    - PostgreSQL-specific syntax

    Example:
        ```python
        validator = NoRECValidator()
        result = await validator.validate(
            query="SELECT * FROM users WHERE age > 25",
            db_connection="postgresql://localhost/mydb"
        )

        if not result.passed:
            print(f"Optimization bug detected: {result.issues[0].description}")
        ```
    """

    def __init__(self):
        """Initialize NoREC validator"""
        self.comparator = ResultComparator()

    async def validate(
        self,
        query: str,
        db_connection: str,
    ) -> ValidationResult:
        """
        Execute NoREC validation on a SQL query.

        Steps:
        1. Execute original query (optimized)
        2. Generate non-optimizable variant
        3. Execute variant (forces table scan)
        4. Compare row counts

        Args:
            query: SQL query to validate
            db_connection: PostgreSQL connection string

        Returns:
            ValidationResult with pass/fail status and any detected issues
        """
        if not psycopg2:
            return self._create_error_result(
                "NoREC",
                "psycopg2 not installed. Install with: pip install psycopg2-binary",
                "DEPENDENCY_ERROR"
            )

        start_time = time.time()

        # Step 1: Generate non-optimizable variant
        try:
            non_opt_query = self._generate_non_optimizable(query)
        except Exception as e:
            return self._create_error_result(
                "NoREC",
                f"Failed to generate non-optimizable query: {str(e)}",
                "QUERY_GENERATION_ERROR"
            )

        # If we couldn't generate a variant, skip validation
        if non_opt_query == query:
            return ValidationResult(
                passed=True,
                confidence=0.3,  # Low confidence - couldn't transform query
                method="NoREC",
                issues=[],
                execution_time_ms=0,
                queries_executed=0,
                metadata={
                    'reason': 'Could not generate non-optimizable variant - validation skipped',
                    'query': query,
                }
            )

        # Step 2: Execute both queries and compare
        try:
            conn = psycopg2.connect(db_connection)
            cursor = conn.cursor()

            try:
                # Execute optimized query
                cursor.execute(query)
                optimized_rows = cursor.fetchall()
                optimized_count = len(optimized_rows)

                # Execute non-optimized query
                cursor.execute(non_opt_query)
                non_opt_rows = cursor.fetchall()
                non_opt_count = len(non_opt_rows)

            finally:
                cursor.close()
                conn.close()

        except Exception as e:
            return self._create_error_result(
                "NoREC",
                f"Query execution failed: {str(e)}",
                "EXECUTION_ERROR"
            )

        execution_time = (time.time() - start_time) * 1000

        # Step 3: Compare row counts
        if optimized_count != non_opt_count:
            # Row count mismatch - optimization bug detected
            issue = ValidationIssue(
                issue_type="OPTIMIZATION_BUG",
                description=(
                    f"Optimized query returned {optimized_count} rows, "
                    f"but non-optimized variant returned {non_opt_count} rows. "
                    f"This indicates an optimization bug in the query planner."
                ),
                severity="ERROR",
                evidence={
                    'optimized_count': optimized_count,
                    'non_optimized_count': non_opt_count,
                    'difference': abs(optimized_count - non_opt_count),
                    'original_query': query,
                    'non_optimized_query': non_opt_query,
                },
                suggested_fix=(
                    "Review execution plan with EXPLAIN. The optimizer may be "
                    "incorrectly using an index or join method. Consider:\n"
                    "1. Adding query hints to disable specific optimizations\n"
                    "2. Rewriting query to avoid problematic optimization\n"
                    "3. Running ANALYZE on involved tables to update statistics\n"
                    "4. Reporting this as a potential DBMS bug if query is correct"
                )
            )

            return ValidationResult(
                passed=False,
                confidence=0.9,  # High confidence in detecting optimization bugs
                method="NoREC",
                issues=[issue],
                execution_time_ms=execution_time,
                queries_executed=2,
                metadata={
                    'non_optimized_query': non_opt_query,
                }
            )

        # Validation passed
        return ValidationResult(
            passed=True,
            confidence=0.9,  # High confidence when counts match
            method="NoREC",
            issues=[],
            execution_time_ms=execution_time,
            queries_executed=2,
            metadata={
                'row_count': optimized_count,
                'non_optimized_query': non_opt_query,
            }
        )

    def _generate_non_optimizable(self, query: str) -> str:
        """
        Generate non-optimizable query variant.

        Strategy: Wrap predicates in subqueries to prevent index usage.

        Transformations:
            FROM: SELECT * FROM users WHERE age > 25
            TO:   SELECT * FROM users WHERE (SELECT age > 25) = TRUE

        This forces table scan because predicate is not directly
        accessible for index optimization.

        Args:
            query: Original SQL query

        Returns:
            Non-optimizable variant of the query

        Note:
            This is a simplified implementation that handles basic WHERE clauses.
            Production implementation should handle:
            - Multiple predicates (AND/OR)
            - Subqueries
            - CTEs
            - JOIN conditions
        """
        # Extract WHERE clause
        where_match = re.search(
            r'\bWHERE\b\s+(.+?)(?:\s+(?:GROUP|ORDER|LIMIT|OFFSET)|;|$)',
            query,
            re.IGNORECASE | re.DOTALL
        )

        if not where_match:
            # No WHERE clause - can't generate non-optimizable variant
            return query

        predicate = where_match.group(1).strip()

        # Wrap predicate in subquery
        # Transform: WHERE age > 25
        # Into:      WHERE (SELECT age > 25) = TRUE
        non_opt_predicate = f"(SELECT {predicate}) = TRUE"

        # Replace in original query
        pattern = r'(\bWHERE\b\s+)(.+?)(\s+(?:GROUP|ORDER|LIMIT|OFFSET)|;|$)'
        replacement = r'\1' + non_opt_predicate + r'\3'

        modified_query = re.sub(
            pattern,
            replacement,
            query,
            count=1,
            flags=re.IGNORECASE | re.DOTALL
        )

        # If pattern didn't match, try simpler version
        if modified_query == query:
            pattern = r'(\bWHERE\b\s+)(.+?)(;|$)'
            replacement = r'\1' + non_opt_predicate + r'\3'
            modified_query = re.sub(
                pattern,
                replacement,
                query,
                count=1,
                flags=re.IGNORECASE | re.DOTALL
            )

        return modified_query


# Example usage
if __name__ == "__main__":
    import asyncio

    async def test_norec():
        """Test NoREC validator with example queries"""
        validator = NoRECValidator()

        # Test 1: Query with WHERE clause (should validate)
        query1 = "SELECT * FROM users WHERE age > 25"
        result1 = await validator.validate(
            query1,
            "postgresql://postgres:postgres@localhost:5432/demo"
        )
        print(f"Test 1 (with WHERE): {result1.passed}")
        print(f"  Confidence: {result1.confidence}")
        print(f"  Queries executed: {result1.queries_executed}")

        # Test 2: Query without WHERE (should skip)
        query2 = "SELECT * FROM users"
        result2 = await validator.validate(
            query2,
            "postgresql://postgres:postgres@localhost:5432/demo"
        )
        print(f"\nTest 2 (no WHERE): {result2.passed}")
        print(f"  Confidence: {result2.confidence}")
        print(f"  Reason: {result2.metadata.get('reason', 'N/A')}")

    # Run async test
    # asyncio.run(test_norec())
    print("NoREC Validator module loaded successfully")
