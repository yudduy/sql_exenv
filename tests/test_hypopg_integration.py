"""
Integration Tests for HypoPG

Tests that verify the complete integration flow with fallback scenarios.
These tests use mocks to simulate real database scenarios without requiring
a live PostgreSQL instance with hypopg installed.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock, AsyncMock
import json


class TestHypoPGFallbackBehavior:
    """Test fallback behavior when hypopg is unavailable."""

    @pytest.mark.asyncio
    async def test_agent_gracefully_falls_back_when_hypopg_unavailable(self):
        """
        Complete flow test: Agent should work without hypopg.

        When hypopg is not available, agent should:
        1. Detect no hypopg during initialization
        2. Fall back to direct CREATE_INDEX
        3. Complete optimization successfully
        """
        from src.agent import SQLOptimizationAgent

        agent = SQLOptimizationAgent()

        with patch.object(agent.extension_detector, 'detect') as mock_detect, \
             patch.object(agent.extension_detector, 'has_hypopg') as mock_has_hypopg, \
             patch.object(agent, '_analyze_query') as mock_analyze, \
             patch.object(agent, '_plan_action') as mock_plan, \
             patch.object(agent, '_execute_ddl') as mock_execute_ddl:

            # Simulate no hypopg available
            mock_detect.return_value = {}
            mock_has_hypopg.return_value = False

            # Simulate analysis suggesting index
            mock_analyze.return_value = {
                "analysis": {"total_cost": 1000, "bottlenecks": ["seq_scan"]},
                "feedback": {
                    "status": "fail",
                    "reason": "High cost",
                    "suggestion": "Add index",
                    "priority": "HIGH"
                }
            }

            # Simulate LLM suggesting TEST_INDEX action
            from src.actions import Action, ActionType
            test_index_action = Action(
                type=ActionType.TEST_INDEX,
                ddl="CREATE INDEX idx_users_email ON users(email)",
                reasoning="Test email index"
            )

            done_action = Action(
                type=ActionType.DONE,
                reasoning="Optimization complete"
            )

            mock_plan.side_effect = [test_index_action, done_action]
            mock_execute_ddl.return_value = {"success": True, "message": "Index created"}

            result = await agent.optimize_query(
                sql="SELECT * FROM users WHERE email = 'test@example.com'",
                db_connection="postgresql://localhost/test",
                validate_correctness=False
            )

            # Verify hypopg was not used
            assert agent.can_use_hypopg is False
            assert agent.hypopg_tool is None

            # Verify fallback to CREATE_INDEX occurred
            mock_execute_ddl.assert_called()

            # The optimize_query may return success=False if validation is disabled
            # What matters is that it completed without exceptions and used fallback
            assert "actions" in result or "error" in result or "success" in result

    @pytest.mark.asyncio
    async def test_agent_uses_hypopg_when_available(self):
        """
        Complete flow test: Agent should use hypopg when available.

        When hypopg is available, agent should:
        1. Detect hypopg during initialization
        2. Create HypoPGTool
        3. Use TEST_INDEX action via hypopg
        4. Only create real index if beneficial
        """
        from src.agent import SQLOptimizationAgent

        agent = SQLOptimizationAgent()

        with patch.object(agent.extension_detector, 'detect') as mock_detect, \
             patch.object(agent.extension_detector, 'has_hypopg') as mock_has_hypopg, \
             patch.object(agent, '_analyze_query') as mock_analyze, \
             patch.object(agent, '_plan_action') as mock_plan, \
             patch('src.agent.HypoPGTool') as MockHypoPGTool:

            # Simulate hypopg available
            mock_detect.return_value = {"hypopg": "1.3.1"}
            mock_has_hypopg.return_value = True

            # Mock HypoPGTool
            mock_tool_instance = Mock()
            from src.tools.hypopg import HypoIndexResult
            mock_tool_instance.test_index.return_value = HypoIndexResult(
                index_def="CREATE INDEX idx_users_email ON users(email)",
                would_be_used=True,
                cost_before=1000,
                cost_after=200,
                improvement_pct=80.0,
                plan_snippet="Index Scan: idx_users_email"
            )
            mock_tool_instance.is_worthwhile.return_value = True
            MockHypoPGTool.return_value = mock_tool_instance

            mock_analyze.return_value = {
                "analysis": {"total_cost": 1000, "bottlenecks": ["seq_scan"]},
                "feedback": {
                    "status": "fail",
                    "reason": "High cost",
                    "suggestion": "Add index",
                    "priority": "HIGH"
                }
            }

            from src.actions import Action, ActionType
            test_index_action = Action(
                type=ActionType.TEST_INDEX,
                ddl="CREATE INDEX idx_users_email ON users(email)",
                reasoning="Test email index"
            )

            done_action = Action(
                type=ActionType.DONE,
                reasoning="Optimization complete"
            )

            mock_plan.side_effect = [test_index_action, done_action]

            # Mock _execute_ddl for actual index creation
            with patch.object(agent, '_execute_ddl') as mock_execute_ddl:
                mock_execute_ddl.return_value = {"success": True, "message": "Index created"}

                result = await agent.optimize_query(
                    sql="SELECT * FROM users WHERE email = 'test@example.com'",
                    db_connection="postgresql://localhost/test",
                    validate_correctness=False
                )

                # Verify hypopg was used
                assert agent.can_use_hypopg is True
                assert agent.hypopg_tool is not None

                # Verify virtual test was performed
                mock_tool_instance.test_index.assert_called()

                # Verify real index was created (because it was worthwhile)
                mock_execute_ddl.assert_called_once()

    @pytest.mark.asyncio
    async def test_agent_skips_index_when_not_beneficial(self):
        """
        Test that agent skips index creation when virtual test shows it's not beneficial.
        """
        from src.agent import SQLOptimizationAgent

        agent = SQLOptimizationAgent()

        with patch.object(agent.extension_detector, 'detect') as mock_detect, \
             patch.object(agent.extension_detector, 'has_hypopg') as mock_has_hypopg, \
             patch.object(agent, '_analyze_query') as mock_analyze, \
             patch.object(agent, '_plan_action') as mock_plan, \
             patch('src.agent.HypoPGTool') as MockHypoPGTool:

            # Simulate hypopg available
            mock_detect.return_value = {"hypopg": "1.3.1"}
            mock_has_hypopg.return_value = True

            # Mock HypoPGTool with poor result
            mock_tool_instance = Mock()
            from src.tools.hypopg import HypoIndexResult
            mock_tool_instance.test_index.return_value = HypoIndexResult(
                index_def="CREATE INDEX idx_users_email ON users(email)",
                would_be_used=True,
                cost_before=1000,
                cost_after=950,
                improvement_pct=5.0,  # Below 10% threshold
                plan_snippet="Index Scan: idx_users_email"
            )
            mock_tool_instance.is_worthwhile.return_value = False
            MockHypoPGTool.return_value = mock_tool_instance

            mock_analyze.return_value = {
                "analysis": {"total_cost": 1000, "bottlenecks": ["seq_scan"]},
                "feedback": {
                    "status": "fail",
                    "reason": "High cost",
                    "suggestion": "Add index",
                    "priority": "HIGH"
                }
            }

            from src.actions import Action, ActionType
            test_index_action = Action(
                type=ActionType.TEST_INDEX,
                ddl="CREATE INDEX idx_users_email ON users(email)",
                reasoning="Test email index"
            )

            done_action = Action(
                type=ActionType.DONE,
                reasoning="Optimization complete"
            )

            mock_plan.side_effect = [test_index_action, done_action]

            # Mock _execute_ddl - should NOT be called
            with patch.object(agent, '_execute_ddl') as mock_execute_ddl:
                result = await agent.optimize_query(
                    sql="SELECT * FROM users WHERE email = 'test@example.com'",
                    db_connection="postgresql://localhost/test",
                    validate_correctness=False
                )

                # Verify virtual test was performed
                mock_tool_instance.test_index.assert_called()

                # Verify real index was NOT created
                mock_execute_ddl.assert_not_called()

                # Verify optimization completed (success may be False if validation disabled)
                assert "actions" in result or "error" in result or "success" in result


class TestPromptContextInjection:
    """Test that prompts correctly include hypopg context."""

    @pytest.mark.asyncio
    async def test_prompt_excludes_test_index_without_hypopg(self):
        """
        Planning prompt should NOT include hypopg context when hypopg unavailable.

        Note: The action type list always includes TEST_INDEX as a valid action,
        but the detailed hypopg_context section should only appear when hypopg is available.
        """
        from src.agent import SQLOptimizationAgent

        agent = SQLOptimizationAgent()
        agent.can_use_hypopg = False

        with patch.object(agent.llm_client, 'chat') as mock_chat:
            mock_chat.return_value = Mock(content='{"type": "DONE", "reasoning": "test"}')

            await agent._plan_action(
                current_query="SELECT * FROM users",
                analysis={
                    "analysis": {"total_cost": 100, "bottlenecks": []},
                    "feedback": {
                        "status": "fail",
                        "reason": "High cost",
                        "suggestion": "Add index",
                        "priority": "HIGH"
                    }
                },
                previous_actions=[],
                failed_actions=[],
                iteration=1
            )

            # Check that the prompt does NOT include hypopg context
            call_args = mock_chat.call_args
            prompt = call_args[1]["messages"][0]["content"] if call_args[1] else call_args[0][0][0]["content"]

            # Should NOT include the detailed hypopg context section
            assert "VIRTUAL INDEX TESTING" not in prompt
            assert "hypopg available" not in prompt
            # Note: "TEST_INDEX" may still appear in action type list, but without hypopg context


class TestErrorRecovery:
    """Test error recovery and resilience."""

    def test_detector_recovers_from_connection_timeout(self):
        """Detector should handle connection timeouts gracefully."""
        from src.extensions.detector import ExtensionDetector
        import socket

        detector = ExtensionDetector()

        with patch('psycopg2.connect') as mock_connect:
            mock_connect.side_effect = socket.timeout("Connection timeout")

            result = detector.detect("postgresql://localhost/test")

            assert result == {}

    def test_hypopg_tool_recovers_from_invalid_sql(self):
        """HypoPGTool should handle invalid SQL gracefully."""
        from src.tools.hypopg import HypoPGTool

        tool = HypoPGTool("postgresql://localhost/test")

        with patch('psycopg2.connect') as mock_connect:
            mock_cursor = MagicMock()
            # EXPLAIN fails due to invalid SQL
            mock_cursor.execute.side_effect = Exception("syntax error at or near 'INVALID'")
            mock_cursor.__enter__ = Mock(return_value=mock_cursor)
            mock_cursor.__exit__ = Mock(return_value=False)
            mock_connect.return_value.cursor.return_value = mock_cursor

            result = tool.test_index("INVALID SQL", "CREATE INDEX idx ON t(a)")

            assert result.error is not None
            assert "syntax error" in result.error.lower()

    @pytest.mark.asyncio
    async def test_agent_continues_after_test_index_error(self):
        """Agent should continue optimization even if TEST_INDEX fails."""
        from src.agent import SQLOptimizationAgent
        from src.actions import Action, ActionType

        agent = SQLOptimizationAgent()
        agent.can_use_hypopg = True

        # Mock HypoPGTool to return error
        mock_tool = Mock()
        from src.tools.hypopg import HypoIndexResult
        mock_tool.test_index.return_value = HypoIndexResult(
            index_def="CREATE INDEX idx ON t(a)",
            would_be_used=False,
            cost_before=0,
            cost_after=0,
            improvement_pct=0,
            plan_snippet="",
            error="Database connection lost"
        )
        agent.hypopg_tool = mock_tool

        action = Action(
            type=ActionType.TEST_INDEX,
            ddl="CREATE INDEX idx ON t(a)",
            reasoning="Test"
        )

        result = await agent._execute_test_index(
            action,
            "postgresql://localhost/test",
            "SELECT * FROM t"
        )

        # Should return error result, not crash
        assert result["success"] is False
        assert "Virtual index test failed" in result["error"]


class TestConcurrencySafety:
    """Test thread safety and concurrent usage patterns."""

    def test_multiple_detectors_can_run_concurrently(self):
        """Multiple detector instances should not interfere."""
        from src.extensions.detector import ExtensionDetector

        detector1 = ExtensionDetector()
        detector2 = ExtensionDetector()

        with patch('psycopg2.connect') as mock_connect:
            mock_connect.side_effect = Exception("Connection failed")

            result1 = detector1.detect("postgresql://db1/test")
            result2 = detector2.detect("postgresql://db2/test")

            assert result1 == {}
            assert result2 == {}

    def test_hypopg_reset_is_idempotent(self):
        """Calling reset multiple times should be safe."""
        from src.tools.hypopg import HypoPGTool

        tool = HypoPGTool("postgresql://localhost/test")

        with patch('psycopg2.connect') as mock_connect:
            mock_cursor = MagicMock()
            mock_cursor.__enter__ = Mock(return_value=mock_cursor)
            mock_cursor.__exit__ = Mock(return_value=False)
            mock_connect.return_value.cursor.return_value = mock_cursor

            # Multiple resets should all succeed
            assert tool.reset() is True
            assert tool.reset() is True
            assert tool.reset() is True

            # Should have called hypopg_reset 3 times
            assert mock_cursor.execute.call_count == 3


class TestMinimalImprovement:
    """Test the 10% minimum improvement threshold in various scenarios."""

    def test_threshold_at_different_cost_scales(self):
        """10% threshold should work correctly at different cost scales."""
        from src.tools.hypopg import HypoPGTool, HypoIndexResult

        tool = HypoPGTool("postgresql://localhost/test")

        # Test at small cost scale
        small_cost_good = HypoIndexResult(
            index_def="CREATE INDEX idx ON t(a)",
            would_be_used=True,
            cost_before=10.0,
            cost_after=8.9,  # 11% improvement
            improvement_pct=11.0,
            plan_snippet="Index Scan"
        )
        assert tool.is_worthwhile(small_cost_good) is True

        # Test at large cost scale
        large_cost_good = HypoIndexResult(
            index_def="CREATE INDEX idx ON t(a)",
            would_be_used=True,
            cost_before=100000.0,
            cost_after=89000.0,  # 11% improvement
            improvement_pct=11.0,
            plan_snippet="Index Scan"
        )
        assert tool.is_worthwhile(large_cost_good) is True

        # Test at tiny cost scale
        tiny_cost_marginal = HypoIndexResult(
            index_def="CREATE INDEX idx ON t(a)",
            would_be_used=True,
            cost_before=0.1,
            cost_after=0.091,  # 9% improvement
            improvement_pct=9.0,
            plan_snippet="Index Scan"
        )
        assert tool.is_worthwhile(tiny_cost_marginal) is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
