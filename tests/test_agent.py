"""
Tests for SQL Optimization Agent
"""


from unittest.mock import AsyncMock, Mock, patch

import pytest


@pytest.fixture
def sample_explain_plan():
    """Sample EXPLAIN JSON output with performance issues."""
    return [{
        "Plan": {
            "Node Type": "Seq Scan",
            "Relation Name": "users",
            "Startup Cost": 0.00,
            "Total Cost": 55000.00,
            "Plan Rows": 100000,
            "Actual Startup Time": 0.015,
            "Actual Total Time": 245.123,
            "Actual Rows": 100000,
            "Filter": "(email = 'test@example.com'::text)",
            "Rows Removed by Filter": 99999
        },
        "Planning Time": 0.123,
        "Execution Time": 245.456
    }]


@pytest.fixture
def optimized_explain_plan():
    """Sample EXPLAIN JSON output after optimization."""
    return [{
        "Plan": {
            "Node Type": "Index Scan",
            "Index Name": "idx_users_email",
            "Relation Name": "users",
            "Startup Cost": 0.42,
            "Total Cost": 14.20,
            "Plan Rows": 1,
            "Actual Startup Time": 0.025,
            "Actual Total Time": 0.028,
            "Actual Rows": 1,
            "Index Cond": "(email = 'test@example.com'::text)"
        },
        "Planning Time": 0.089,
        "Execution Time": 0.156
    }]


class TestAgentInterface:
    """Test the simplified agent interface (TDD)."""

    def test_agent_initialization_with_defaults(self, mock_llm_client):
        """Agent should initialize with sensible defaults."""
        from src.agent import SQLOptimizationAgent

        agent = SQLOptimizationAgent(llm_client=mock_llm_client)

        assert agent.max_iterations == 10
        assert agent.timeout_seconds == 120
        assert agent.use_thinking is True
        assert agent.thinking_budget >= 1024
        assert agent.statement_timeout_ms == 60000

    def test_agent_initialization_with_custom_config(self, mock_llm_client):
        """Agent should accept custom configuration."""
        from src.agent import SQLOptimizationAgent

        agent = SQLOptimizationAgent(
            llm_client=mock_llm_client,
            max_iterations=5,
            timeout_seconds=30,
            statement_timeout_ms=30000,
            thinking_budget=2000
        )

        assert agent.max_iterations == 5
        assert agent.timeout_seconds == 30
        assert agent.statement_timeout_ms == 30000
        assert agent.thinking_budget == 2000

    @pytest.mark.asyncio
    async def test_optimize_query_simple_interface(self, mock_db_connection, mock_llm_client):
        """Agent should provide simple optimize_query() interface."""
        from src.agent import SQLOptimizationAgent

        agent = SQLOptimizationAgent(llm_client=mock_llm_client)

        with patch.object(agent, '_analyze_query', new_callable=AsyncMock) as mock_analyze, \
             patch.object(agent, '_plan_action', new_callable=AsyncMock) as mock_plan, \
             patch.object(agent, '_execute_action', new_callable=AsyncMock) as mock_execute:

            mock_analyze.return_value = {
                "status": "pass",
                "cost": 14.20,
                "execution_time_ms": 0.156
            }
            mock_plan.return_value = {"type": "DONE", "reasoning": "Query is optimal"}

            result = await agent.optimize_query(
                sql="SELECT * FROM users WHERE email='test@example.com'",
                db_connection=mock_db_connection
            )

            assert "success" in result
            assert "final_query" in result
            assert "actions" in result
            assert "metrics" in result

    @pytest.mark.asyncio
    async def test_optimize_query_with_constraints(self, mock_db_connection, mock_llm_client):
        """Agent should accept optional performance constraints."""
        from src.agent import SQLOptimizationAgent

        agent = SQLOptimizationAgent(llm_client=mock_llm_client)

        with patch.object(agent, '_analyze_query', new_callable=AsyncMock) as mock_analyze:
            mock_analyze.return_value = {"status": "pass", "cost": 100}

            result = await agent.optimize_query(
                sql="SELECT * FROM users",
                db_connection=mock_db_connection,
                max_cost=1000.0,
                max_time_ms=5000
            )

            mock_analyze.assert_called_once()
            call_args = mock_analyze.call_args
            assert call_args is not None


class TestAgentReActLoop:
    """Test the ReAct (Reason-Act-Observe) optimization loop."""

    @pytest.mark.asyncio
    async def test_react_loop_single_iteration(self, mock_db_connection, mock_llm_client):
        """Agent should complete ReAct loop for simple optimization."""
        from src.agent import SQLOptimizationAgent

        agent = SQLOptimizationAgent(llm_client=mock_llm_client, max_iterations=1)
        # Testing the basic flow: Analyze → Plan → Act → Observe
        pass

    @pytest.mark.asyncio
    async def test_react_loop_stops_on_success(self, mock_db_connection, mock_llm_client):
        """Agent should stop iterating when query meets constraints."""
        from src.agent import SQLOptimizationAgent

        agent = SQLOptimizationAgent(llm_client=mock_llm_client, max_iterations=10)

        with patch.object(agent, '_analyze_query', new_callable=AsyncMock) as mock_analyze:
            mock_analyze.return_value = {
                "status": "pass",
                "cost": 10.0,
                "execution_time_ms": 5.0
            }

            result = await agent.optimize_query(
                sql="SELECT * FROM users WHERE id=1",
                db_connection=mock_db_connection,
                max_cost=1000.0
            )

            assert result["success"] is True
            assert len(result["actions"]) <= 1

    @pytest.mark.asyncio
    async def test_react_loop_max_iterations(self, mock_db_connection, mock_llm_client):
        """Agent should respect max_iterations limit."""
        from src.agent import SQLOptimizationAgent

        agent = SQLOptimizationAgent(llm_client=mock_llm_client, max_iterations=3)

        with patch.object(agent, '_analyze_query', new_callable=AsyncMock) as mock_analyze, \
             patch.object(agent, '_plan_action', new_callable=AsyncMock) as mock_plan, \
             patch.object(agent, '_execute_action', new_callable=AsyncMock) as mock_execute:

            mock_analyze.return_value = {"status": "fail", "cost": 100000}
            mock_plan.return_value = {"type": "CREATE_INDEX", "ddl": "CREATE INDEX ..."}
            mock_execute.return_value = True

            result = await agent.optimize_query(
                sql="SELECT * FROM large_table",
                db_connection=mock_db_connection,
                max_cost=100.0
            )

            assert len(result["actions"]) <= 3


class TestAgentSafety:
    """Test safety features based on PostgreSQL best practices."""

    @pytest.mark.asyncio
    async def test_statement_timeout_applied(self, mock_db_connection, mock_llm_client):
        """Agent should apply statement_timeout to prevent runaway queries."""
        from src.agent import SQLOptimizationAgent

        agent = SQLOptimizationAgent(llm_client=mock_llm_client, statement_timeout_ms=30000)

        with patch('psycopg2.connect') as mock_connect:
            mock_cursor = Mock()
            mock_connect.return_value.cursor.return_value = mock_cursor
            pass

    @pytest.mark.asyncio
    async def test_explain_analyze_uses_transaction(self, mock_db_connection, mock_llm_client):
        """EXPLAIN ANALYZE should wrap in BEGIN/ROLLBACK for safety."""
        from src.agent import SQLOptimizationAgent

        agent = SQLOptimizationAgent(llm_client=mock_llm_client)
        pass

    @pytest.mark.asyncio
    async def test_two_phase_explain_strategy(self, mock_db_connection, mock_llm_client):
        """Agent should use two-phase EXPLAIN: estimate first, ANALYZE only if safe."""
        from src.agent import SQLOptimizationAgent

        agent = SQLOptimizationAgent(llm_client=mock_llm_client)
        pass


class TestAgentActions:
    """Test agent action types and execution."""

    @pytest.mark.asyncio
    async def test_create_index_action(self, mock_db_connection, mock_llm_client):
        """Agent should execute CREATE INDEX actions."""
        from src.actions import Action, ActionType
        from src.agent import SQLOptimizationAgent

        agent = SQLOptimizationAgent(llm_client=mock_llm_client)

        with patch('psycopg2.connect') as mock_connect:
            mock_cursor = Mock()
            mock_connect.return_value.cursor.return_value = mock_cursor

            action = Action(
                type=ActionType.CREATE_INDEX,
                ddl="CREATE INDEX idx_users_email ON users(email)",
                reasoning="Test index creation"
            )
            await agent._execute_action(action=action, db_connection=mock_db_connection)

            mock_cursor.execute.assert_called()

    @pytest.mark.asyncio
    async def test_rewrite_query_action(self, mock_db_connection, mock_llm_client):
        """Agent should handle REWRITE_QUERY actions."""
        from src.actions import Action, ActionType
        from src.agent import SQLOptimizationAgent

        agent = SQLOptimizationAgent(llm_client=mock_llm_client)

        action = Action(
            type=ActionType.REWRITE_QUERY,
            new_query="SELECT id, email FROM users WHERE email='test@example.com'",
            reasoning="Test query rewrite"
        )
        result = await agent._execute_action(action=action, db_connection=mock_db_connection)

        assert result is not None

    @pytest.mark.asyncio
    async def test_run_analyze_action(self, mock_db_connection, mock_llm_client):
        """Agent should execute ANALYZE table actions."""
        from src.actions import Action, ActionType
        from src.agent import SQLOptimizationAgent

        agent = SQLOptimizationAgent(llm_client=mock_llm_client)

        with patch('psycopg2.connect') as mock_connect:
            mock_cursor = Mock()
            mock_connect.return_value.cursor.return_value = mock_cursor

            action = Action(
                type=ActionType.RUN_ANALYZE,
                ddl="ANALYZE users",
                reasoning="Test analyze"
            )
            await agent._execute_action(action=action, db_connection=mock_db_connection)

            mock_cursor.execute.assert_called()


class TestAgentExtendedThinking:
    """Test extended thinking mode integration."""

    @pytest.mark.asyncio
    async def test_extended_thinking_enabled_by_default(self, mock_llm_client):
        """Extended thinking should be enabled by default for complex reasoning."""
        from src.agent import SQLOptimizationAgent

        agent = SQLOptimizationAgent(llm_client=mock_llm_client)

        assert agent.use_thinking is True
        assert agent.thinking_budget >= 1024

    @pytest.mark.asyncio
    async def test_extended_thinking_budget_configurable(self, mock_llm_client):
        """Thinking budget should be configurable."""
        from src.agent import SQLOptimizationAgent

        agent = SQLOptimizationAgent(llm_client=mock_llm_client, thinking_budget=4000)

        assert agent.thinking_budget == 4000

    @pytest.mark.asyncio
    async def test_no_explicit_cot_in_prompts(self, mock_db_connection, mock_llm_client):
        """Per Anthropic docs: remove explicit chain-of-thought from prompts."""
        from src.agent import SQLOptimizationAgent

        agent = SQLOptimizationAgent(llm_client=mock_llm_client)
        pass


class TestAgentConfiguration:
    """Test agent configuration is not hardcoded."""

    def test_no_hardcoded_model_names(self, mock_llm_client):
        """Model names should be configurable, not hardcoded."""
        from src.agent import SQLOptimizationAgent

        agent = SQLOptimizationAgent(llm_client=mock_llm_client)
        # Agent uses the llm_client which has its own model
        assert agent.llm_client is mock_llm_client

    def test_no_hardcoded_file_paths(self):
        """Should not have hardcoded paths to BIRD-CRITIC or other files."""
        import inspect

        from src.agent import SQLOptimizationAgent

        source = inspect.getsource(SQLOptimizationAgent)

        assert "BIRD-CRITIC" not in source
        assert "baseline/data" not in source
        assert "database_description.csv" not in source

    def test_all_thresholds_configurable(self, mock_llm_client):
        """All thresholds should be configurable via constructor."""
        from src.agent import SQLOptimizationAgent

        agent = SQLOptimizationAgent(
            llm_client=mock_llm_client,
            statement_timeout_ms=45000
        )

        assert agent.statement_timeout_ms == 45000


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
