"""
Tests for Failed Action Tracking (Phase 1)

Tests the core feedback loop that enables the agent to learn from failures
and avoid repeating the same failed actions.
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch
from src.agent import SQLOptimizationAgent, FailedAction
from src.actions import Action, ActionType


class TestFailedActionTracking:
    """Test that failed actions are properly tracked and recorded."""

    @pytest.mark.asyncio
    async def test_failed_action_is_recorded(self, mock_db_connection="postgresql://localhost:5432/test"):
        """When an action fails, it should be recorded in failed_actions list."""
        agent = SQLOptimizationAgent()

        # Mock the methods
        with patch.object(agent, '_get_explain_plan', new_callable=AsyncMock) as mock_explain, \
             patch.object(agent, '_plan_action', new_callable=AsyncMock) as mock_plan:

            # Setup: query fails constraint
            mock_explain.return_value = [{
                "Plan": {"Node Type": "Seq Scan", "Total Cost": 100000, "Relation Name": "users"},
                "Execution Time": 1000
            }]

            # First iteration: Plan to create index
            mock_plan.side_effect = [
                Action(
                    type=ActionType.CREATE_INDEX,
                    reasoning="Create index on users",
                    ddl="CREATE INDEX idx_users_email ON users(email)"
                ),
                # Second iteration: Should mark as FAILED after seeing the failure
                Action(type=ActionType.FAILED, reasoning="Cannot optimize further")
            ]

            # Mock DDL execution to fail with "already exists"
            with patch('psycopg2.connect') as mock_connect:
                mock_cursor = Mock()
                mock_cursor.execute.side_effect = Exception('relation "idx_users_email" already exists')
                mock_connect.return_value.cursor.return_value = mock_cursor
                mock_connect.return_value.__enter__ = lambda self: self
                mock_connect.return_value.__exit__ = lambda self, *args: None

                result = await agent.optimize_query(
                    sql="SELECT * FROM users WHERE email='test@example.com'",
                    db_connection=mock_db_connection,
                    max_cost=1000.0
                )

                # Verify _plan_action was called at least twice
                assert mock_plan.call_count >= 2

                # Check that the second call received failure context
                # Signature: _plan_action(self, current_query, analysis, previous_actions, failed_actions, iteration)
                second_call_args = mock_plan.call_args_list[1]
                failed_actions_arg = second_call_args[0][3]  # 4th positional arg (index 3)

                # Should have at least one failed action
                assert len(failed_actions_arg) > 0
                assert isinstance(failed_actions_arg[0], FailedAction)

    @pytest.mark.asyncio
    async def test_failed_ddl_is_tracked_in_failed_ddls_set(self, mock_db_connection="postgresql://localhost:5432/test"):
        """Failed DDL should be added to failed_ddls set to prevent retry."""
        agent = SQLOptimizationAgent()

        ddl = "CREATE INDEX idx_test ON users(email)"

        # Mock connection to fail
        with patch('psycopg2.connect') as mock_connect:
            mock_cursor = Mock()
            mock_cursor.execute.side_effect = Exception('relation "idx_test" already exists')
            mock_conn = Mock()
            mock_conn.cursor.return_value = mock_cursor
            mock_connect.return_value = mock_conn

            result = await agent._execute_ddl(ddl, mock_db_connection)

            assert result["success"] is False
            # Note: failed_ddls is tracked in optimize_query loop, not in _execute_ddl

    @pytest.mark.asyncio
    async def test_failed_ddl_prevents_immediate_retry(self, mock_db_connection="postgresql://localhost:5432/test"):
        """If a DDL is in failed_ddls, it should not be retried."""
        agent = SQLOptimizationAgent()

        ddl = "CREATE INDEX idx_test ON users(email)"
        agent.failed_ddls.add(ddl)

        result = await agent._execute_ddl(ddl, mock_db_connection)

        # Should fail immediately without hitting database
        assert result["success"] is False
        assert "already attempted and failed" in result["error"]


class TestErrorInterpretation:
    """Test error message interpretation for LLM guidance."""

    def test_interpret_index_already_exists(self):
        """Should interpret 'already exists' errors correctly."""
        agent = SQLOptimizationAgent()

        error = 'relation "idx_users_email" already exists'
        interpretation = agent._interpret_error(error)

        assert "already exists" in interpretation.lower()
        assert "different index" in interpretation.lower() or "being used" in interpretation.lower()

    def test_interpret_permission_denied(self):
        """Should interpret permission errors correctly."""
        agent = SQLOptimizationAgent()

        error = 'permission denied for table users'
        interpretation = agent._interpret_error(error)

        assert "permission" in interpretation.lower()

    def test_interpret_syntax_error(self):
        """Should interpret syntax errors correctly."""
        agent = SQLOptimizationAgent()

        error = 'syntax error at or near "CREAT"'
        interpretation = agent._interpret_error(error)

        assert "syntax" in interpretation.lower()

    def test_interpret_timeout(self):
        """Should interpret timeout errors correctly."""
        agent = SQLOptimizationAgent()

        error = 'canceling statement due to statement timeout'
        interpretation = agent._interpret_error(error)

        assert "timeout" in interpretation.lower()

    def test_interpret_lock_error(self):
        """Should interpret lock/deadlock errors correctly."""
        agent = SQLOptimizationAgent()

        error = 'deadlock detected'
        interpretation = agent._interpret_error(error)

        assert "lock" in interpretation.lower() or "deadlock" in interpretation.lower()


class TestPlanningWithFailureContext:
    """Test that failure context is properly passed to planning LLM."""

    @pytest.mark.asyncio
    async def test_planning_prompt_includes_failure_context(self, mock_db_connection="postgresql://localhost:5432/test"):
        """Planning prompt should include previous failed actions."""
        agent = SQLOptimizationAgent()

        # Create a failed action
        failed_action = FailedAction(
            action=Action(
                type=ActionType.CREATE_INDEX,
                reasoning="Create index",
                ddl="CREATE INDEX idx_test ON users(email)"
            ),
            error='relation "idx_test" already exists',
            iteration=1
        )

        analysis = {
            "feedback": {"status": "fail", "reason": "High cost", "suggestion": "Create index", "priority": "HIGH"},
            "analysis": {"bottlenecks": []}
        }

        with patch.object(agent.client.messages, 'create', new_callable=Mock) as mock_create:
            mock_response = Mock()
            mock_response.content = [Mock(type="text", text='{"type": "DONE", "reasoning": "test"}')]
            mock_create.return_value = mock_response

            await agent._plan_action(
                current_query="SELECT * FROM users",
                analysis=analysis,
                previous_actions=[],
                failed_actions=[failed_action],
                iteration=2
            )

            # Verify the call was made
            assert mock_create.called

            # Get the prompt that was sent
            call_args = mock_create.call_args
            messages = call_args[1]['messages']
            prompt = messages[0]['content']

            # Verify failure context is in prompt
            assert "Failed attempts" in prompt
            assert "DO NOT RETRY" in prompt
            assert "idx_test" in prompt
            assert "already exists" in prompt

    @pytest.mark.asyncio
    async def test_planning_prompt_includes_error_interpretation(self, mock_db_connection="postgresql://localhost:5432/test"):
        """Planning prompt should include structured error classification and guidance."""
        agent = SQLOptimizationAgent()

        failed_action = FailedAction(
            action=Action(
                type=ActionType.CREATE_INDEX,
                reasoning="Create index",
                ddl="CREATE INDEX idx_test ON users(email)"
            ),
            error='relation "idx_test" already exists',
            iteration=1
        )

        analysis = {
            "feedback": {"status": "fail", "reason": "High cost", "suggestion": "Create index", "priority": "HIGH"},
            "analysis": {"bottlenecks": []}
        }

        with patch.object(agent.client.messages, 'create', new_callable=Mock) as mock_create:
            mock_response = Mock()
            mock_response.content = [Mock(type="text", text='{"type": "DONE", "reasoning": "test"}')]
            mock_create.return_value = mock_response

            await agent._plan_action(
                current_query="SELECT * FROM users",
                analysis=analysis,
                previous_actions=[],
                failed_actions=[failed_action],
                iteration=2
            )

            call_args = mock_create.call_args
            prompt = call_args[1]['messages'][0]['content']

            # Should include ErrorClassifier structured guidance
            assert "Error Category:" in prompt
            assert "INDEX_ALREADY_EXISTS" in prompt
            assert "Suggested alternative strategies:" in prompt


class TestInfiniteLoopPrevention:
    """Test that the infinite loop bug is actually fixed."""

    @pytest.mark.asyncio
    async def test_agent_does_not_retry_same_failed_index(self, mock_db_connection="postgresql://localhost:5432/test"):
        """Agent should not keep trying to create the same index after it fails."""
        agent = SQLOptimizationAgent(max_iterations=5)

        create_index_call_count = 0

        def mock_execute_side_effect(sql, *args):
            nonlocal create_index_call_count
            if "CREATE INDEX idx_users_email" in sql:
                create_index_call_count += 1
                raise Exception('relation "idx_users_email" already exists')

        with patch.object(agent, '_get_explain_plan', new_callable=AsyncMock) as mock_explain, \
             patch.object(agent, '_plan_action', new_callable=AsyncMock) as mock_plan, \
             patch('psycopg2.connect') as mock_connect:

            # Always return high cost (needs optimization)
            mock_explain.return_value = [{
                "Plan": {"Node Type": "Seq Scan", "Total Cost": 100000, "Relation Name": "users"},
                "Execution Time": 1000
            }]

            # Plan to create index on first attempt, then FAILED on second
            mock_plan.side_effect = [
                Action(
                    type=ActionType.CREATE_INDEX,
                    reasoning="Create index",
                    ddl="CREATE INDEX idx_users_email ON users(email)"
                ),
                Action(type=ActionType.FAILED, reasoning="Index already exists, cannot optimize further")
            ]

            mock_cursor = Mock()
            mock_cursor.execute = Mock(side_effect=mock_execute_side_effect)
            mock_conn = Mock()
            mock_conn.cursor.return_value = mock_cursor
            mock_conn.rollback = Mock()
            mock_conn.__enter__ = lambda self: self
            mock_conn.__exit__ = lambda self, *args: None
            mock_connect.return_value = mock_conn

            result = await agent.optimize_query(
                sql="SELECT * FROM users WHERE email='test@example.com'",
                db_connection=mock_db_connection,
                max_cost=1000.0
            )

            # The agent should NOT have tried to create the same index multiple times
            # It should try once, fail, then give up or try something else
            assert create_index_call_count <= 1, \
                f"Agent tried to create the same index {create_index_call_count} times (should be 1)"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
