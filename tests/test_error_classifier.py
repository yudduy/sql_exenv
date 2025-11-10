"""
Tests for Error Classifier (Phase 2)

Tests the error classification system that categorizes PostgreSQL errors
and provides error-specific guidance for alternative optimization strategies.

Following TDD: Write tests first, then implement.
"""

import pytest
from src.error_classifier import (
    ErrorClassifier,
    ErrorCategory,
    ErrorClassification,
    AlternativeStrategy
)


class TestErrorCategory:
    """Test error category enum."""

    def test_error_categories_exist(self):
        """All expected error categories should be defined."""
        categories = {
            ErrorCategory.INDEX_ALREADY_EXISTS,
            ErrorCategory.PERMISSION_DENIED,
            ErrorCategory.SYNTAX_ERROR,
            ErrorCategory.TIMEOUT,
            ErrorCategory.LOCK_CONFLICT,
            ErrorCategory.RELATION_NOT_FOUND,
            ErrorCategory.DISK_FULL,
            ErrorCategory.CONNECTION_ERROR,
            ErrorCategory.UNKNOWN
        }

        assert len(categories) >= 9


class TestErrorClassification:
    """Test ErrorClassification dataclass."""

    def test_error_classification_structure(self):
        """ErrorClassification should have required fields."""
        classification = ErrorClassification(
            category=ErrorCategory.INDEX_ALREADY_EXISTS,
            message="Index already exists",
            guidance="Try a different index or query rewrite",
            alternatives=[AlternativeStrategy.QUERY_REWRITE, AlternativeStrategy.CHECK_INDEX_USAGE]
        )

        assert classification.category == ErrorCategory.INDEX_ALREADY_EXISTS
        assert "already exists" in classification.message.lower()
        assert len(classification.alternatives) > 0


class TestAlternativeStrategy:
    """Test alternative strategies enum."""

    def test_alternative_strategies_exist(self):
        """All expected alternative strategies should be defined."""
        strategies = {
            AlternativeStrategy.QUERY_REWRITE,
            AlternativeStrategy.CHECK_INDEX_USAGE,
            AlternativeStrategy.CREATE_DIFFERENT_INDEX,
            AlternativeStrategy.USE_CONCURRENT_INDEX,
            AlternativeStrategy.INCREASE_WORK_MEM,
            AlternativeStrategy.RUN_VACUUM,
            AlternativeStrategy.ANALYZE_STATISTICS,
            AlternativeStrategy.MARK_DONE,
            AlternativeStrategy.MARK_FAILED
        }

        assert len(strategies) >= 9


class TestErrorClassifier:
    """Test ErrorClassifier main functionality."""

    def test_classifier_initialization(self):
        """Classifier should initialize without errors."""
        classifier = ErrorClassifier()
        assert classifier is not None

    def test_classify_index_already_exists(self):
        """Should classify 'index already exists' errors correctly."""
        classifier = ErrorClassifier()

        error = 'relation "idx_users_email" already exists'
        classification = classifier.classify(error)

        assert classification.category == ErrorCategory.INDEX_ALREADY_EXISTS
        assert "already exists" in classification.message.lower()
        assert AlternativeStrategy.CHECK_INDEX_USAGE in classification.alternatives
        assert AlternativeStrategy.QUERY_REWRITE in classification.alternatives

    def test_classify_permission_denied(self):
        """Should classify permission errors correctly."""
        classifier = ErrorClassifier()

        error = 'permission denied for table users'
        classification = classifier.classify(error)

        assert classification.category == ErrorCategory.PERMISSION_DENIED
        assert "permission" in classification.message.lower()
        assert AlternativeStrategy.MARK_FAILED in classification.alternatives

    def test_classify_syntax_error(self):
        """Should classify SQL syntax errors correctly."""
        classifier = ErrorClassifier()

        error = 'syntax error at or near "CREAT"'
        classification = classifier.classify(error)

        assert classification.category == ErrorCategory.SYNTAX_ERROR
        assert "syntax" in classification.message.lower()

    def test_classify_timeout(self):
        """Should classify timeout errors correctly."""
        classifier = ErrorClassifier()

        error = 'canceling statement due to statement timeout'
        classification = classifier.classify(error)

        assert classification.category == ErrorCategory.TIMEOUT
        assert "timeout" in classification.message.lower()
        assert AlternativeStrategy.INCREASE_WORK_MEM in classification.alternatives or \
               AlternativeStrategy.QUERY_REWRITE in classification.alternatives

    def test_classify_lock_conflict(self):
        """Should classify lock/deadlock errors correctly."""
        classifier = ErrorClassifier()

        error = 'deadlock detected'
        classification = classifier.classify(error)

        assert classification.category == ErrorCategory.LOCK_CONFLICT
        assert "lock" in classification.message.lower() or "deadlock" in classification.message.lower()
        assert AlternativeStrategy.USE_CONCURRENT_INDEX in classification.alternatives

    def test_classify_relation_not_found(self):
        """Should classify 'relation does not exist' errors correctly."""
        classifier = ErrorClassifier()

        error = 'relation "non_existent_table" does not exist'
        classification = classifier.classify(error)

        assert classification.category == ErrorCategory.RELATION_NOT_FOUND
        assert "not" in classification.message.lower() and "exist" in classification.message.lower()

    def test_classify_unknown_error(self):
        """Should handle unknown errors gracefully."""
        classifier = ErrorClassifier()

        error = 'some completely unexpected database error'
        classification = classifier.classify(error)

        assert classification.category == ErrorCategory.UNKNOWN
        assert classification.message is not None
        assert len(classification.alternatives) > 0


class TestErrorGuidance:
    """Test that classifications provide actionable guidance."""

    def test_index_exists_guidance_is_actionable(self):
        """Guidance for index already exists should suggest specific actions."""
        classifier = ErrorClassifier()

        classification = classifier.classify('relation "idx_test" already exists')

        # Should suggest checking if index is being used
        assert "check" in classification.guidance.lower() or "verify" in classification.guidance.lower()
        # Should suggest alternative approaches
        assert len(classification.alternatives) >= 2

    def test_permission_denied_guidance_explains_limitation(self):
        """Guidance for permission errors should explain the limitation."""
        classifier = ErrorClassifier()

        classification = classifier.classify('permission denied for table users')

        # Should explain that user lacks privileges
        assert "permission" in classification.guidance.lower() or "privilege" in classification.guidance.lower()
        # Should suggest marking as failed since user can't fix this
        assert AlternativeStrategy.MARK_FAILED in classification.alternatives

    def test_timeout_guidance_suggests_optimization(self):
        """Guidance for timeouts should suggest performance improvements."""
        classifier = ErrorClassifier()

        classification = classifier.classify('statement timeout')

        # Should suggest optimization approaches
        has_optimization_suggestion = any([
            AlternativeStrategy.QUERY_REWRITE in classification.alternatives,
            AlternativeStrategy.CREATE_DIFFERENT_INDEX in classification.alternatives,
            AlternativeStrategy.INCREASE_WORK_MEM in classification.alternatives
        ])
        assert has_optimization_suggestion


class TestClassificationPriority:
    """Test error classification priority and specificity."""

    def test_specific_match_over_generic(self):
        """Should match specific error patterns over generic ones."""
        classifier = ErrorClassifier()

        # This error contains both "relation" and "already exists"
        # Should classify as INDEX_ALREADY_EXISTS, not RELATION_NOT_FOUND
        error = 'relation "idx_test" already exists'
        classification = classifier.classify(error)

        assert classification.category == ErrorCategory.INDEX_ALREADY_EXISTS

    def test_case_insensitive_matching(self):
        """Should match errors regardless of case."""
        classifier = ErrorClassifier()

        error1 = 'PERMISSION DENIED for table users'
        error2 = 'permission denied for table users'

        classification1 = classifier.classify(error1)
        classification2 = classifier.classify(error2)

        assert classification1.category == classification2.category


class TestIntegrationWithAgent:
    """Test how ErrorClassifier integrates with the agent."""

    def test_classifier_provides_better_guidance_than_simple_interpreter(self):
        """ErrorClassifier should provide more structured guidance than simple text interpretation."""
        classifier = ErrorClassifier()

        error = 'relation "idx_users_email" already exists'
        classification = classifier.classify(error)

        # Should have structured alternatives, not just a text message
        assert isinstance(classification.alternatives, list)
        assert all(isinstance(alt, AlternativeStrategy) for alt in classification.alternatives)

        # Should have actionable guidance
        assert len(classification.guidance) > 20  # More than a simple phrase

    def test_get_alternative_strategies_for_llm(self):
        """Should be able to format alternatives for LLM consumption."""
        classifier = ErrorClassifier()

        error = 'relation "idx_test" already exists'
        classification = classifier.classify(error)

        # Should be able to format alternatives as text for LLM
        alternatives_text = classifier.format_alternatives_for_llm(classification)

        assert "CHECK_INDEX_USAGE" in alternatives_text or "check" in alternatives_text.lower()
        assert "QUERY_REWRITE" in alternatives_text or "rewrite" in alternatives_text.lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
