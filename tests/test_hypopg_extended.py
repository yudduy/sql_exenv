"""
Extended Tests for HypoPG Integration

Additional edge case and integration tests to complement test_hypopg.py
Focus areas:
1. Boundary conditions (exactly 10% threshold)
2. Real database integration scenarios
3. Error handling edge cases
4. Concurrent access patterns
5. Edge cases in plan extraction
"""

import pytest
from unittest.mock import Mock, patch, MagicMock, call
import json
import psycopg2


class TestExtensionDetectorEdgeCases:
    """Test edge cases for ExtensionDetector."""

    def test_detect_handles_query_permission_error(self):
        """Detector should gracefully handle permission denied errors."""
        from src.extensions.detector import ExtensionDetector

        detector = ExtensionDetector()

        with patch('psycopg2.connect') as mock_connect:
            mock_cursor = MagicMock()
            mock_cursor.execute.side_effect = psycopg2.errors.InsufficientPrivilege("Permission denied")
            mock_cursor.__enter__ = Mock(return_value=mock_cursor)
            mock_cursor.__exit__ = Mock(return_value=False)
            mock_connect.return_value.cursor.return_value = mock_cursor

            result = detector.detect("postgresql://localhost/test")

            # Should return empty dict on permission error
            assert result == {}

    def test_detect_handles_hypopg_not_loaded(self):
        """Detector should set version to None if hypopg installed but not loaded."""
        from src.extensions.detector import ExtensionDetector

        detector = ExtensionDetector()

        with patch('psycopg2.connect') as mock_connect:
            mock_cursor = MagicMock()
            # First query returns hypopg as available
            mock_cursor.fetchall.return_value = [("hypopg", "1.3.1")]
            # Second query (hypopg_reset) fails - extension not loaded
            mock_cursor.execute.side_effect = [
                None,  # First execute (SELECT from pg_available_extensions) succeeds
                psycopg2.errors.UndefinedFunction("function hypopg_reset() does not exist")
            ]
            mock_cursor.__enter__ = Mock(return_value=mock_cursor)
            mock_cursor.__exit__ = Mock(return_value=False)
            mock_connect.return_value.cursor.return_value = mock_cursor

            result = detector.detect("postgresql://localhost/test")

            # hypopg should be None (installed but not loaded)
            assert "hypopg" in result
            assert result["hypopg"] is None

    def test_has_hypopg_with_empty_string_version(self):
        """
        has_hypopg treats empty string as truthy (POTENTIAL BUG).

        Current behavior: Empty string version returns True
        Expected behavior: Should probably return False (empty version = not properly loaded)

        This test documents the current behavior for tracking.
        """
        from src.extensions.detector import ExtensionDetector

        detector = ExtensionDetector()
        # Current behavior: empty string is treated as available
        # This might be a bug - empty version string should probably be treated as unavailable
        assert detector.has_hypopg({"hypopg": ""}) is True  # Current behavior (potentially buggy)

    def test_detect_handles_unexpected_exception_during_connect(self):
        """Detector should handle unexpected exceptions gracefully."""
        from src.extensions.detector import ExtensionDetector

        detector = ExtensionDetector()

        with patch('psycopg2.connect') as mock_connect:
            mock_connect.side_effect = RuntimeError("Unexpected error")

            result = detector.detect("postgresql://localhost/test")

            assert result == {}


class TestHypoPGToolEdgeCases:
    """Test edge cases for HypoPGTool."""

    def test_test_index_handles_zero_cost_before(self):
        """Test should handle zero cost_before gracefully."""
        from src.tools.hypopg import HypoPGTool

        tool = HypoPGTool("postgresql://localhost/test")

        with patch('psycopg2.connect') as mock_connect:
            mock_cursor = MagicMock()
            # Return zero cost
            mock_cursor.fetchone.side_effect = [
                ([{"Plan": {"Total Cost": 0.0}}],),  # Baseline cost
                (12345,),  # hypopg OID
                ([{"Plan": {"Total Cost": 0.0}}],),  # Cost with index
            ]
            mock_cursor.__enter__ = Mock(return_value=mock_cursor)
            mock_cursor.__exit__ = Mock(return_value=False)
            mock_connect.return_value.cursor.return_value = mock_cursor

            result = tool.test_index("SELECT 1", "CREATE INDEX idx ON t(a)")

            # Should return 0% improvement without division by zero
            assert result.improvement_pct == 0
            assert result.error is None

    def test_test_index_handles_negative_improvement(self):
        """Test should handle cases where index makes query worse."""
        from src.tools.hypopg import HypoPGTool

        tool = HypoPGTool("postgresql://localhost/test")

        with patch('psycopg2.connect') as mock_connect:
            mock_cursor = MagicMock()
            # Index makes query slower
            mock_cursor.fetchone.side_effect = [
                ([{"Plan": {"Total Cost": 100.0}}],),  # Baseline cost
                (12345,),  # hypopg OID
                ([{"Plan": {"Total Cost": 150.0}}],),  # Worse cost with index
            ]
            mock_cursor.__enter__ = Mock(return_value=mock_cursor)
            mock_cursor.__exit__ = Mock(return_value=False)
            mock_connect.return_value.cursor.return_value = mock_cursor

            result = tool.test_index("SELECT * FROM t", "CREATE INDEX idx ON t(a)")

            # Should return negative improvement
            assert result.improvement_pct == -50.0
            assert result.error is None

    def test_is_worthwhile_boundary_exactly_10_percent(self):
        """is_worthwhile should accept exactly 10% improvement."""
        from src.tools.hypopg import HypoPGTool, HypoIndexResult

        tool = HypoPGTool("postgresql://localhost/test")

        # Exactly 10% improvement
        result = HypoIndexResult(
            index_def="CREATE INDEX idx ON t(a)",
            would_be_used=True,
            cost_before=100,
            cost_after=90,
            improvement_pct=10.0,
            plan_snippet="Index Scan"
        )

        # Should be True (>= threshold)
        assert tool.is_worthwhile(result) is True

    def test_is_worthwhile_boundary_just_below_10_percent(self):
        """is_worthwhile should reject 9.99% improvement."""
        from src.tools.hypopg import HypoPGTool, HypoIndexResult

        tool = HypoPGTool("postgresql://localhost/test")

        # Just below threshold
        result = HypoIndexResult(
            index_def="CREATE INDEX idx ON t(a)",
            would_be_used=True,
            cost_before=100,
            cost_after=90.01,
            improvement_pct=9.99,
            plan_snippet="Index Scan"
        )

        # Should be False (< threshold)
        assert tool.is_worthwhile(result) is False

    def test_test_index_handles_hypopg_create_returning_none(self):
        """Test should handle hypopg_create_index returning None."""
        from src.tools.hypopg import HypoPGTool

        tool = HypoPGTool("postgresql://localhost/test")

        with patch('psycopg2.connect') as mock_connect:
            mock_cursor = MagicMock()
            mock_cursor.fetchone.side_effect = [
                ([{"Plan": {"Total Cost": 100.0}}],),  # Baseline cost
                None,  # hypopg_create_index returns None (error case)
            ]
            mock_cursor.__enter__ = Mock(return_value=mock_cursor)
            mock_cursor.__exit__ = Mock(return_value=False)
            mock_connect.return_value.cursor.return_value = mock_cursor

            result = tool.test_index("SELECT * FROM t", "CREATE INDEX idx ON t(a)")

            # Should return error result
            assert result.error == "Failed to create hypothetical index"
            assert result.would_be_used is False

    def test_test_index_cleans_up_on_exception(self):
        """Test should clean up hypothetical index even if exception occurs."""
        from src.tools.hypopg import HypoPGTool

        tool = HypoPGTool("postgresql://localhost/test")

        with patch('psycopg2.connect') as mock_connect:
            mock_cursor = MagicMock()
            mock_cursor.fetchone.side_effect = [
                ([{"Plan": {"Total Cost": 100.0}}],),  # Baseline cost
                (12345,),  # hypopg OID
                Exception("Unexpected error during second EXPLAIN"),  # Error during second EXPLAIN
            ]
            mock_cursor.__enter__ = Mock(return_value=mock_cursor)
            mock_cursor.__exit__ = Mock(return_value=False)
            mock_connect.return_value.cursor.return_value = mock_cursor

            result = tool.test_index("SELECT * FROM t", "CREATE INDEX idx ON t(a)")

            # Should return error result
            assert result.error is not None
            assert "Unexpected error" in result.error

            # Should have attempted cleanup (best effort)
            # Check that hypopg_drop_index was called
            execute_calls = [str(call) for call in mock_cursor.execute.call_args_list]
            drop_calls = [c for c in execute_calls if 'hypopg_drop_index' in c]
            assert len(drop_calls) > 0

    def test_extract_index_usage_handles_no_plan_key(self):
        """_extract_index_usage should handle malformed plan without 'Plan' key."""
        from src.tools.hypopg import HypoPGTool

        tool = HypoPGTool("postgresql://localhost/test")
        result = tool._extract_index_usage({})

        assert result == "No index usage detected"

    def test_extract_index_usage_handles_nested_plans(self):
        """_extract_index_usage should recursively find index nodes."""
        from src.tools.hypopg import HypoPGTool

        tool = HypoPGTool("postgresql://localhost/test")

        plan = {
            "Plan": {
                "Node Type": "Nested Loop",
                "Plans": [
                    {
                        "Node Type": "Index Scan",
                        "Index Name": "idx_users_email"
                    },
                    {
                        "Node Type": "Hash Join",
                        "Plans": [
                            {
                                "Node Type": "Index Scan",
                                "Index Name": "idx_orders_user_id"
                            }
                        ]
                    }
                ]
            }
        }

        result = tool._extract_index_usage(plan)

        # Should find both indexes
        assert "idx_users_email" in result
        assert "idx_orders_user_id" in result
        assert "Index Scan" in result

    def test_extract_index_usage_handles_missing_index_name(self):
        """_extract_index_usage should handle index node without index name."""
        from src.tools.hypopg import HypoPGTool

        tool = HypoPGTool("postgresql://localhost/test")

        plan = {
            "Plan": {
                "Node Type": "Index Scan",
                # Missing "Index Name" key
            }
        }

        result = tool._extract_index_usage(plan)

        assert "Index Scan: N/A" in result

    def test_reset_returns_true_on_success(self):
        """reset should return True when successful."""
        from src.tools.hypopg import HypoPGTool

        tool = HypoPGTool("postgresql://localhost/test")

        with patch('psycopg2.connect') as mock_connect:
            mock_cursor = MagicMock()
            mock_cursor.__enter__ = Mock(return_value=mock_cursor)
            mock_cursor.__exit__ = Mock(return_value=False)
            mock_connect.return_value.cursor.return_value = mock_cursor

            result = tool.reset()

            assert result is True
            mock_cursor.execute.assert_called_once_with("SELECT hypopg_reset()")

    def test_reset_returns_false_on_error(self):
        """reset should return False on error."""
        from src.tools.hypopg import HypoPGTool

        tool = HypoPGTool("postgresql://localhost/test")

        with patch('psycopg2.connect') as mock_connect:
            mock_connect.side_effect = Exception("Connection failed")

            result = tool.reset()

            assert result is False


class TestActionParsingEdgeCases:
    """Test edge cases for action parsing."""

    def test_parse_action_with_type_field_instead_of_action(self):
        """Parser should accept 'type' field as well as 'action'."""
        from src.actions import parse_action_from_llm_response, ActionType

        response = json.dumps({
            "type": "TEST_INDEX",
            "ddl": "CREATE INDEX idx ON t(a)",
            "reasoning": "Test"
        })

        action = parse_action_from_llm_response(response)
        assert action.type == ActionType.TEST_INDEX

    def test_parse_action_strips_markdown_code_blocks(self):
        """Parser should strip markdown code blocks."""
        from src.actions import parse_action_from_llm_response, ActionType

        response = """```json
{
    "type": "TEST_INDEX",
    "ddl": "CREATE INDEX idx ON t(a)",
    "reasoning": "Test"
}
```"""

        action = parse_action_from_llm_response(response)
        assert action.type == ActionType.TEST_INDEX

    def test_parse_action_handles_confidence_as_string(self):
        """Parser should convert string confidence to float."""
        from src.actions import parse_action_from_llm_response

        response = json.dumps({
            "type": "TEST_INDEX",
            "ddl": "CREATE INDEX idx ON t(a)",
            "reasoning": "Test",
            "confidence": "0.95"
        })

        action = parse_action_from_llm_response(response)
        assert action.confidence == 0.95
        assert isinstance(action.confidence, float)

    def test_parse_action_raises_on_empty_string(self):
        """Parser should raise ValueError on empty string."""
        from src.actions import parse_action_from_llm_response

        with pytest.raises(ValueError, match="Empty response"):
            parse_action_from_llm_response("")

    def test_parse_action_raises_on_whitespace_only(self):
        """Parser should raise ValueError on whitespace-only string."""
        from src.actions import parse_action_from_llm_response

        with pytest.raises(ValueError, match="Empty response"):
            parse_action_from_llm_response("   \n\t  ")

    def test_action_to_dict_serialization(self):
        """Action should serialize all fields correctly."""
        from src.actions import Action, ActionType

        action = Action(
            type=ActionType.TEST_INDEX,
            reasoning="Test index effectiveness",
            ddl="CREATE INDEX idx ON t(a)",
            confidence=0.85
        )

        d = action.to_dict()

        assert d["type"] == "TEST_INDEX"
        assert d["reasoning"] == "Test index effectiveness"
        assert d["ddl"] == "CREATE INDEX idx ON t(a)"
        assert d["new_query"] is None
        assert d["confidence"] == 0.85


class TestAgentExecuteTestIndexEdgeCases:
    """Test edge cases for agent's _execute_test_index."""

    @pytest.fixture
    def mock_db_connection(self):
        return "postgresql://localhost:5432/testdb"

    @pytest.mark.asyncio
    async def test_execute_test_index_with_error_result(self, mock_db_connection):
        """_execute_test_index should return error if virtual test fails."""
        from src.agent import SQLOptimizationAgent
        from src.actions import Action, ActionType
        from src.tools.hypopg import HypoIndexResult

        agent = SQLOptimizationAgent()
        agent.can_use_hypopg = True

        # Mock HypoPGTool with error result
        mock_tool = Mock()
        mock_tool.test_index.return_value = HypoIndexResult(
            index_def="CREATE INDEX idx ON t(a)",
            would_be_used=False,
            cost_before=0,
            cost_after=0,
            improvement_pct=0,
            plan_snippet="",
            error="Invalid index syntax"
        )
        agent.hypopg_tool = mock_tool

        action = Action(
            type=ActionType.TEST_INDEX,
            ddl="CREATE INDEX idx ON t(a)",
            reasoning="Test"
        )

        result = await agent._execute_test_index(action, mock_db_connection, "SELECT * FROM t")

        assert result["success"] is False
        assert "Virtual index test failed" in result["error"]
        assert "Invalid index syntax" in result["error"]

    @pytest.mark.asyncio
    async def test_execute_test_index_includes_virtual_test_data(self, mock_db_connection):
        """_execute_test_index should include virtual test data when skipping."""
        from src.agent import SQLOptimizationAgent
        from src.actions import Action, ActionType
        from src.tools.hypopg import HypoIndexResult

        agent = SQLOptimizationAgent()
        agent.can_use_hypopg = True

        # Mock HypoPGTool with marginal improvement
        mock_tool = Mock()
        test_result = HypoIndexResult(
            index_def="CREATE INDEX idx ON t(a)",
            would_be_used=True,
            cost_before=1000,
            cost_after=920,
            improvement_pct=8.0,
            plan_snippet="Index Scan: idx"
        )
        mock_tool.test_index.return_value = test_result
        mock_tool.is_worthwhile.return_value = False
        agent.hypopg_tool = mock_tool

        action = Action(
            type=ActionType.TEST_INDEX,
            ddl="CREATE INDEX idx ON t(a)",
            reasoning="Test"
        )

        result = await agent._execute_test_index(action, mock_db_connection, "SELECT * FROM t")

        assert result["success"] is True
        assert "skipped" in result["message"].lower()
        assert "virtual_test" in result
        assert result["virtual_test"]["improvement_pct"] == 8.0

    @pytest.mark.asyncio
    async def test_execute_test_index_fallback_no_query(self, mock_db_connection):
        """_execute_test_index should fallback to CREATE_INDEX if no query provided."""
        from src.agent import SQLOptimizationAgent
        from src.actions import Action, ActionType

        agent = SQLOptimizationAgent()
        agent.can_use_hypopg = True
        agent.hypopg_tool = Mock()

        action = Action(
            type=ActionType.TEST_INDEX,
            ddl="CREATE INDEX idx ON t(a)",
            reasoning="Test"
        )

        with patch.object(agent, '_execute_ddl') as mock_execute_ddl:
            mock_execute_ddl.return_value = {"success": True, "message": "Index created"}

            # No query provided
            result = await agent._execute_test_index(action, mock_db_connection, None)

            # Should fall back to direct creation
            mock_execute_ddl.assert_called_once_with(action.ddl, mock_db_connection)

    @pytest.mark.asyncio
    async def test_execute_test_index_fallback_empty_query(self, mock_db_connection):
        """_execute_test_index should fallback if query is empty string."""
        from src.agent import SQLOptimizationAgent
        from src.actions import Action, ActionType

        agent = SQLOptimizationAgent()
        agent.can_use_hypopg = True
        agent.hypopg_tool = Mock()

        action = Action(
            type=ActionType.TEST_INDEX,
            ddl="CREATE INDEX idx ON t(a)",
            reasoning="Test"
        )

        with patch.object(agent, '_execute_ddl') as mock_execute_ddl:
            mock_execute_ddl.return_value = {"success": True, "message": "Index created"}

            # Empty string query
            result = await agent._execute_test_index(action, mock_db_connection, "")

            # Should fall back to direct creation
            mock_execute_ddl.assert_called_once_with(action.ddl, mock_db_connection)


class TestConcurrentHypoPGUsage:
    """Test concurrent usage patterns."""

    def test_multiple_tools_can_coexist(self):
        """Multiple HypoPGTool instances should be able to coexist."""
        from src.tools.hypopg import HypoPGTool

        tool1 = HypoPGTool("postgresql://localhost/db1")
        tool2 = HypoPGTool("postgresql://localhost/db2")

        assert tool1.connection_string != tool2.connection_string
        assert tool1.MIN_IMPROVEMENT_PCT == tool2.MIN_IMPROVEMENT_PCT

    def test_detector_multiple_calls(self):
        """Detector should be callable multiple times."""
        from src.extensions.detector import ExtensionDetector

        detector = ExtensionDetector()

        # Multiple detect calls should not interfere
        result1 = detector.detect("postgresql://invalid1/db")
        result2 = detector.detect("postgresql://invalid2/db")

        assert result1 == {}
        assert result2 == {}


class TestHypoIndexResultEdgeCases:
    """Test HypoIndexResult edge cases."""

    def test_hypo_index_result_with_all_fields(self):
        """HypoIndexResult should serialize all fields including error."""
        from src.tools.hypopg import HypoIndexResult

        result = HypoIndexResult(
            index_def="CREATE INDEX idx ON t(a)",
            would_be_used=False,
            cost_before=100,
            cost_after=100,
            improvement_pct=0,
            plan_snippet="Seq Scan",
            error="Test error"
        )

        d = result.to_dict()

        assert d["error"] == "Test error"
        assert d["would_be_used"] is False

    def test_hypo_index_result_defaults(self):
        """HypoIndexResult should have None as default for error."""
        from src.tools.hypopg import HypoIndexResult

        result = HypoIndexResult(
            index_def="CREATE INDEX idx ON t(a)",
            would_be_used=True,
            cost_before=100,
            cost_after=50,
            improvement_pct=50,
            plan_snippet="Index Scan"
        )

        assert result.error is None
        d = result.to_dict()
        assert d["error"] is None


class TestPlanExtractionCornerCases:
    """Test plan extraction corner cases."""

    def test_find_index_nodes_with_bitmap_index_scan(self):
        """Should detect Bitmap Index Scan nodes."""
        from src.tools.hypopg import HypoPGTool

        tool = HypoPGTool("postgresql://localhost/test")

        plan = {
            "Plan": {
                "Node Type": "Bitmap Heap Scan",
                "Plans": [
                    {
                        "Node Type": "Bitmap Index Scan",
                        "Index Name": "idx_bitmap"
                    }
                ]
            }
        }

        result = tool._extract_index_usage(plan)

        assert "Bitmap Index Scan" in result
        assert "idx_bitmap" in result

    def test_find_index_nodes_with_index_only_scan(self):
        """Should detect Index Only Scan nodes."""
        from src.tools.hypopg import HypoPGTool

        tool = HypoPGTool("postgresql://localhost/test")

        plan = {
            "Plan": {
                "Node Type": "Index Only Scan",
                "Index Name": "idx_covering"
            }
        }

        result = tool._extract_index_usage(plan)

        assert "Index Only Scan" in result
        assert "idx_covering" in result

    def test_find_index_nodes_multiple_results(self):
        """_find_index_nodes should accumulate results across recursion."""
        from src.tools.hypopg import HypoPGTool

        tool = HypoPGTool("postgresql://localhost/test")

        # Start with existing results
        initial_results = ["Index Scan: idx_existing"]
        node = {
            "Node Type": "Index Scan",
            "Index Name": "idx_new"
        }

        results = tool._find_index_nodes(node, initial_results)

        # Should contain both
        assert len(results) == 2
        assert "Index Scan: idx_existing" in results
        assert "Index Scan: idx_new" in results


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
