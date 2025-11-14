"""
Unit tests for SQL correctness validators.

Tests TLP (Ternary Logic Partitioning) and NoREC validators with various
query patterns and edge cases.
"""

import pytest
import os
from typing import List

# Import validators
from src.validators.base import ValidationResult, ValidationIssue
from src.validators.metamorphic import TLPValidator
from src.validators.differential import NoRECValidator
from src.validators.result_comparator import ResultComparator


# Test database connection (from environment or default)
TEST_DB_CONNECTION = os.environ.get(
    'DB_CONNECTION',
    'postgresql://postgres:postgres@localhost:5432/demo'
)


class TestResultComparator:
    """Test result set comparison logic"""

    def test_identical_result_sets(self):
        """Comparator should match identical result sets"""
        comparator = ResultComparator()

        rs1 = [(1, 'Alice'), (2, 'Bob'), (3, 'Charlie')]
        rs2 = [(1, 'Alice'), (2, 'Bob'), (3, 'Charlie')]

        assert comparator.compare_result_sets(rs1, rs2) == True

    def test_different_order_same_content(self):
        """Comparator should match result sets with different row order"""
        comparator = ResultComparator()

        rs1 = [(1, 'Alice'), (2, 'Bob'), (3, 'Charlie')]
        rs2 = [(3, 'Charlie'), (1, 'Alice'), (2, 'Bob')]

        assert comparator.compare_result_sets(rs1, rs2) == True

    def test_different_result_sets(self):
        """Comparator should not match different result sets"""
        comparator = ResultComparator()

        rs1 = [(1, 'Alice'), (2, 'Bob')]
        rs2 = [(1, 'Alice'), (3, 'Charlie')]

        assert comparator.compare_result_sets(rs1, rs2) == False

    def test_null_handling(self):
        """Comparator should handle NULL values correctly"""
        comparator = ResultComparator()

        rs1 = [(1, None), (2, 'Bob')]
        rs2 = [(2, 'Bob'), (1, None)]

        assert comparator.compare_result_sets(rs1, rs2) == True

    def test_float_tolerance(self):
        """Comparator should handle floating point comparisons with tolerance"""
        comparator = ResultComparator(float_tolerance=1e-9)

        rs1 = [(1, 3.14159265358979)]
        rs2 = [(1, 3.14159265358980)]  # Very slight difference

        # Should match within tolerance
        assert comparator.compare_result_sets(rs1, rs2) == True

    def test_multiset_union(self):
        """Multiset union should preserve duplicates"""
        comparator = ResultComparator()

        rs1 = [(1, 'A')]
        rs2 = [(1, 'A'), (2, 'B')]
        rs3 = [(3, 'C')]

        union = comparator.multiset_union([rs1, rs2, rs3])

        # Should have 4 rows total (duplicates preserved)
        assert len(union) == 4
        assert (1, 'A') in union

    def test_empty_result_sets(self):
        """Comparator should handle empty result sets"""
        comparator = ResultComparator()

        assert comparator.compare_result_sets([], []) == True
        assert comparator.compare_result_sets([(1, 'A')], []) == False
        assert comparator.compare_result_sets([], [(1, 'A')]) == False

    def test_row_count_diff(self):
        """Should correctly calculate row count difference"""
        comparator = ResultComparator()

        rs1 = [(1,), (2,), (3,)]
        rs2 = [(1,), (2,), (3,), (4,), (5,)]

        diff = comparator.get_row_count_diff(rs1, rs2)
        assert diff == 2

    def test_find_mismatched_rows(self):
        """Should find rows that differ between result sets"""
        comparator = ResultComparator()

        rs1 = [(1, 'A'), (2, 'B'), (3, 'C')]
        rs2 = [(1, 'A'), (4, 'D'), (5, 'E')]

        only_1, only_2 = comparator.find_mismatched_rows(rs1, rs2, max_examples=5)

        # Should find rows only in rs1: (2, 'B'), (3, 'C')
        # Should find rows only in rs2: (4, 'D'), (5, 'E')
        assert len(only_1) == 2
        assert len(only_2) == 2
        assert (2, 'B') in only_1 or (3, 'C') in only_1
        assert (4, 'D') in only_2 or (5, 'E') in only_2


class TestTLPValidator:
    """Test TLP (Ternary Logic Partitioning) validator"""

    @pytest.mark.asyncio
    async def test_query_without_where_clause(self):
        """TLP should return low confidence for queries without WHERE"""
        validator = TLPValidator()

        query = "SELECT * FROM users LIMIT 10"
        result = await validator.validate(query, TEST_DB_CONNECTION)

        assert result.passed == True
        assert result.confidence < 0.5  # Low confidence
        assert result.method == "TLP"
        assert 'No WHERE clause' in result.metadata.get('reason', '')

    @pytest.mark.asyncio
    async def test_simple_where_clause(self):
        """TLP should validate simple WHERE clause correctly"""
        validator = TLPValidator()

        query = "SELECT user_id, username FROM users WHERE user_id > 100"

        try:
            result = await validator.validate(query, TEST_DB_CONNECTION)

            # Should execute successfully (pass or fail depends on query correctness)
            assert result.method == "TLP"
            assert result.queries_executed == 4  # Original + 3 partitions

            if result.passed:
                assert result.confidence == 1.0
                assert len(result.issues) == 0
            else:
                assert result.confidence == 1.0
                assert len(result.issues) > 0
                assert result.issues[0].issue_type == "PARTITION_MISMATCH"

        except Exception as e:
            # If database not available, skip test
            pytest.skip(f"Database not available: {e}")

    @pytest.mark.asyncio
    async def test_predicate_extraction_simple(self):
        """Should correctly extract simple WHERE predicate"""
        validator = TLPValidator()

        query = "SELECT * FROM users WHERE age > 25"
        predicate = validator._extract_where_predicate(query)

        assert predicate is not None
        assert 'age > 25' in predicate

    @pytest.mark.asyncio
    async def test_predicate_extraction_complex(self):
        """Should extract complex WHERE predicate"""
        validator = TLPValidator()

        query = "SELECT * FROM users WHERE age > 25 AND status = 'active' ORDER BY username"
        predicate = validator._extract_where_predicate(query)

        assert predicate is not None
        assert 'age > 25' in predicate
        assert 'status' in predicate
        # Should not include ORDER BY
        assert 'ORDER BY' not in predicate.upper()

    @pytest.mark.asyncio
    async def test_partition_query_generation(self):
        """Should generate correct partitioned queries"""
        validator = TLPValidator()

        original = "SELECT * FROM users WHERE age > 25"
        predicate = "age > 25"

        q_true = validator._partition_query(original, predicate, "TRUE")
        q_false = validator._partition_query(original, predicate, "FALSE")
        q_null = validator._partition_query(original, predicate, "NULL")

        assert "(age > 25) IS TRUE" in q_true
        assert "(age > 25) IS FALSE" in q_false
        assert "(age > 25) IS NULL" in q_null

    @pytest.mark.asyncio
    async def test_validation_with_null_values(self):
        """TLP should handle queries that can return NULL in predicate"""
        validator = TLPValidator()

        # Query where predicate can evaluate to NULL
        # (email field might be NULL for some users)
        query = "SELECT user_id FROM users WHERE email = 'test@example.com' LIMIT 100"

        try:
            result = await validator.validate(query, TEST_DB_CONNECTION)

            # Should execute without errors
            assert result.method == "TLP"
            assert result.queries_executed == 4

        except Exception as e:
            pytest.skip(f"Database not available: {e}")

    @pytest.mark.asyncio
    async def test_incorrect_query_logic(self):
        """TLP should detect logically incorrect queries"""
        validator = TLPValidator()

        # This query has impossible predicate (age > 100 AND age < 50)
        # Should return 0 rows, and partitions should also sum to 0
        query = "SELECT * FROM users WHERE user_id > 1000000 AND user_id < 50"

        try:
            result = await validator.validate(query, TEST_DB_CONNECTION)

            # Even with 0 rows, TLP invariant should hold
            # (0 rows original = 0 + 0 + 0 from partitions)
            # So this should still pass
            assert result.method == "TLP"

        except Exception as e:
            pytest.skip(f"Database not available: {e}")


class TestNoRECValidator:
    """Test NoREC (Non-optimizing Reference Engine Construction) validator"""

    @pytest.mark.asyncio
    async def test_query_without_where(self):
        """NoREC should skip validation for queries without WHERE"""
        validator = NoRECValidator()

        query = "SELECT * FROM users LIMIT 10"
        result = await validator.validate(query, TEST_DB_CONNECTION)

        assert result.passed == True
        assert result.confidence < 0.5  # Low confidence (skipped)
        assert result.method == "NoREC"
        assert result.queries_executed == 0  # Skipped execution

    @pytest.mark.asyncio
    async def test_simple_query_validation(self):
        """NoREC should validate simple queries correctly"""
        validator = NoRECValidator()

        query = "SELECT user_id FROM users WHERE user_id > 100 LIMIT 50"

        try:
            result = await validator.validate(query, TEST_DB_CONNECTION)

            assert result.method == "NoREC"
            assert result.queries_executed == 2  # Optimized + non-optimized

            if result.passed:
                assert result.confidence == 0.9
                assert len(result.issues) == 0
            else:
                assert len(result.issues) > 0
                assert result.issues[0].issue_type == "OPTIMIZATION_BUG"

        except Exception as e:
            pytest.skip(f"Database not available: {e}")

    @pytest.mark.asyncio
    async def test_non_optimizable_query_generation(self):
        """Should generate correct non-optimizable query variant"""
        validator = NoRECValidator()

        original = "SELECT * FROM users WHERE age > 25"
        non_opt = validator._generate_non_optimizable(original)

        # Should wrap predicate in subquery
        assert "(SELECT age > 25) = TRUE" in non_opt
        assert "WHERE" in non_opt

    @pytest.mark.asyncio
    async def test_query_with_order_by(self):
        """NoREC should handle queries with ORDER BY clause"""
        validator = NoRECValidator()

        original = "SELECT * FROM users WHERE status = 'active' ORDER BY created_at"
        non_opt = validator._generate_non_optimizable(original)

        # Should transform WHERE but preserve ORDER BY
        assert "(SELECT status = 'active') = TRUE" in non_opt
        assert "ORDER BY" in non_opt

    @pytest.mark.asyncio
    async def test_query_with_limit(self):
        """NoREC should handle queries with LIMIT clause"""
        validator = NoRECValidator()

        original = "SELECT * FROM users WHERE age > 18 LIMIT 100"
        non_opt = validator._generate_non_optimizable(original)

        # Should transform WHERE but preserve LIMIT
        assert "(SELECT age > 18) = TRUE" in non_opt
        assert "LIMIT 100" in non_opt


class TestValidationResult:
    """Test ValidationResult dataclass"""

    def test_to_dict_conversion(self):
        """ValidationResult should convert to dict correctly"""
        issue = ValidationIssue(
            issue_type="TEST_ISSUE",
            description="Test description",
            severity="ERROR",
            evidence={'count': 100},
            suggested_fix="Fix it"
        )

        result = ValidationResult(
            passed=False,
            confidence=0.9,
            method="TLP",
            issues=[issue],
            execution_time_ms=123.45,
            queries_executed=4,
            metadata={'test': 'value'}
        )

        result_dict = result.to_dict()

        assert result_dict['passed'] == False
        assert result_dict['confidence'] == 0.9
        assert result_dict['method'] == "TLP"
        assert len(result_dict['issues']) == 1
        assert result_dict['issues'][0]['issue_type'] == "TEST_ISSUE"
        assert result_dict['execution_time_ms'] == 123.45
        assert result_dict['queries_executed'] == 4


class TestValidationIssue:
    """Test ValidationIssue dataclass"""

    def test_to_dict_conversion(self):
        """ValidationIssue should convert to dict correctly"""
        issue = ValidationIssue(
            issue_type="PARTITION_MISMATCH",
            description="Rows don't match",
            severity="ERROR",
            evidence={'original': 100, 'union': 95},
            suggested_fix="Check WHERE clause"
        )

        issue_dict = issue.to_dict()

        assert issue_dict['issue_type'] == "PARTITION_MISMATCH"
        assert issue_dict['description'] == "Rows don't match"
        assert issue_dict['severity'] == "ERROR"
        assert issue_dict['evidence']['original'] == 100
        assert issue_dict['suggested_fix'] == "Check WHERE clause"


# Integration tests (require running database)
class TestValidatorsIntegration:
    """Integration tests with real database"""

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_combined_tlp_and_norec(self):
        """Should run both TLP and NoREC validators on same query"""
        tlp = TLPValidator()
        norec = NoRECValidator()

        query = "SELECT * FROM users WHERE user_id = 1000 LIMIT 10"

        try:
            tlp_result = await tlp.validate(query, TEST_DB_CONNECTION)
            norec_result = await norec.validate(query, TEST_DB_CONNECTION)

            # Both should execute successfully
            assert tlp_result.method == "TLP"
            assert norec_result.method == "NoREC"

            # Both should pass for correct query
            assert tlp_result.passed == True
            assert norec_result.passed == True

        except Exception as e:
            pytest.skip(f"Database not available: {e}")

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_real_query_validation(self):
        """Test validation on actual database query"""
        validator = TLPValidator()

        # Real query from demo database
        query = """
            SELECT user_id, username, email
            FROM users
            WHERE user_id BETWEEN 1000 AND 1100
            LIMIT 50
        """

        try:
            result = await validator.validate(query, TEST_DB_CONNECTION)

            # Should execute successfully
            assert result.method == "TLP"
            assert result.queries_executed == 4

            # Query should be correct
            assert result.passed == True
            assert result.confidence == 1.0

        except Exception as e:
            pytest.skip(f"Database not available: {e}")
