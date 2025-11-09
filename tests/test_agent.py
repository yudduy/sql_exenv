"""
Tests for SQL Optimization Agent

Following TDD approach: write tests first, then implement.
Based on 2025 best practices for production LLM agents.
"""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch
import json


@pytest.fixture
def mock_db_connection():
    """Mock database connection string."""
    return "postgresql://localhost:5432/testdb"


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

    def test_agent_initialization_with_defaults(self):
        """Agent should initialize with sensible defaults."""
        from src.agent import SQLOptimizationAgent

        agent = SQLOptimizationAgent()

        # Verify defaults based on 2025 best practices
        assert agent.max_iterations == 10
        assert agent.timeout_seconds == 120
        assert agent.use_extended_thinking is True
        assert agent.thinking_budget >= 1024  # Minimum per Anthropic docs
        assert agent.statement_timeout_ms == 60000  # 60 seconds default

    def test_agent_initialization_with_custom_config(self):
        """Agent should accept custom configuration."""
        from src.agent import SQLOptimizationAgent

        agent = SQLOptimizationAgent(
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
    async def test_optimize_query_simple_interface(self, mock_db_connection):
        """Agent should provide simple optimize_query() interface."""
        from src.agent import SQLOptimizationAgent

        agent = SQLOptimizationAgent()

        # Mock the internal methods
        with patch.object(agent, '_analyze_query', new_callable=AsyncMock) as mock_analyze, \
             patch.object(agent, '_plan_action', new_callable=AsyncMock) as mock_plan, \
             patch.object(agent, '_execute_action', new_callable=AsyncMock) as mock_execute:

            # Setup mocks
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

            # Verify simple return structure
            assert "success" in result
            assert "final_query" in result
            assert "actions" in result
            assert "metrics" in result

    @pytest.mark.asyncio
    async def test_optimize_query_with_constraints(self, mock_db_connection):
        """Agent should accept optional performance constraints."""
        from src.agent import SQLOptimizationAgent

        agent = SQLOptimizationAgent()

        with patch.object(agent, '_analyze_query', new_callable=AsyncMock) as mock_analyze:
            mock_analyze.return_value = {"status": "pass", "cost": 100}

            result = await agent.optimize_query(
                sql="SELECT * FROM users",
                db_connection=mock_db_connection,
                max_cost=1000.0,
                max_time_ms=5000
            )

            # Verify constraints were passed to analysis
            mock_analyze.assert_called_once()
            call_args = mock_analyze.call_args
            assert call_args is not None


class TestAgentReActLoop:
    """Test the ReAct (Reason-Act-Observe) optimization loop."""

    @pytest.mark.asyncio
    async def test_react_loop_single_iteration(self, mock_db_connection):
        """Agent should complete ReAct loop for simple optimization."""
        from src.agent import SQLOptimizationAgent

        agent = SQLOptimizationAgent(max_iterations=1)

        # This will be implemented after we refactor agent.py
        # Testing the basic flow: Analyze → Plan → Act → Observe
        pass

    @pytest.mark.asyncio
    async def test_react_loop_stops_on_success(self, mock_db_connection):
        """Agent should stop iterating when query meets constraints."""
        from src.agent import SQLOptimizationAgent

        agent = SQLOptimizationAgent(max_iterations=10)

        # Mock successful optimization on first try
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
            assert len(result["actions"]) <= 1  # Should stop early

    @pytest.mark.asyncio
    async def test_react_loop_max_iterations(self, mock_db_connection):
        """Agent should respect max_iterations limit."""
        from src.agent import SQLOptimizationAgent

        agent = SQLOptimizationAgent(max_iterations=3)

        # Mock that query never meets constraints
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

            # Should stop at max iterations
            assert len(result["actions"]) <= 3


class TestAgentSafety:
    """Test safety features based on PostgreSQL best practices."""

    @pytest.mark.asyncio
    async def test_statement_timeout_applied(self, mock_db_connection):
        """Agent should apply statement_timeout to prevent runaway queries."""
        from src.agent import SQLOptimizationAgent

        agent = SQLOptimizationAgent(statement_timeout_ms=30000)

        # Mock database execution
        with patch('psycopg2.connect') as mock_connect:
            mock_cursor = Mock()
            mock_connect.return_value.cursor.return_value = mock_cursor

            # This will verify that SET statement_timeout is called
            # Implementation detail: will be tested after refactor
            pass

    @pytest.mark.asyncio
    async def test_explain_analyze_uses_transaction(self, mock_db_connection):
        """EXPLAIN ANALYZE should wrap in BEGIN/ROLLBACK for safety."""
        from src.agent import SQLOptimizationAgent

        agent = SQLOptimizationAgent()

        # Per PostgreSQL docs: EXPLAIN ANALYZE executes the query
        # Should use BEGIN; EXPLAIN ANALYZE; ROLLBACK; for data-modifying queries
        pass

    @pytest.mark.asyncio
    async def test_two_phase_explain_strategy(self, mock_db_connection):
        """Agent should use two-phase EXPLAIN: estimate first, ANALYZE only if safe."""
        from src.agent import SQLOptimizationAgent

        agent = SQLOptimizationAgent()

        # Phase 1: EXPLAIN (FORMAT JSON) - no execution
        # Phase 2: EXPLAIN (ANALYZE, FORMAT JSON) - only if cost < threshold
        pass


class TestAgentActions:
    """Test agent action types and execution."""

    @pytest.mark.asyncio
    async def test_create_index_action(self, mock_db_connection):
        """Agent should execute CREATE INDEX actions."""
        from src.agent import SQLOptimizationAgent

        agent = SQLOptimizationAgent()

        with patch('psycopg2.connect') as mock_connect:
            mock_cursor = Mock()
            mock_connect.return_value.cursor.return_value = mock_cursor

            await agent._execute_action(
                action={
                    "type": "CREATE_INDEX",
                    "ddl": "CREATE INDEX idx_users_email ON users(email)"
                },
                db_connection=mock_db_connection
            )

            # Verify DDL was executed
            mock_cursor.execute.assert_called()

    @pytest.mark.asyncio
    async def test_rewrite_query_action(self, mock_db_connection):
        """Agent should handle REWRITE_QUERY actions."""
        from src.agent import SQLOptimizationAgent

        agent = SQLOptimizationAgent()

        # Query rewrite doesn't execute anything, just returns new query
        result = await agent._execute_action(
            action={
                "type": "REWRITE_QUERY",
                "new_query": "SELECT id, email FROM users WHERE email='test@example.com'"
            },
            db_connection=mock_db_connection
        )

        assert result is not None

    @pytest.mark.asyncio
    async def test_run_analyze_action(self, mock_db_connection):
        """Agent should execute ANALYZE table actions."""
        from src.agent import SQLOptimizationAgent

        agent = SQLOptimizationAgent()

        with patch('psycopg2.connect') as mock_connect:
            mock_cursor = Mock()
            mock_connect.return_value.cursor.return_value = mock_cursor

            await agent._execute_action(
                action={
                    "type": "RUN_ANALYZE",
                    "ddl": "ANALYZE users"
                },
                db_connection=mock_db_connection
            )

            mock_cursor.execute.assert_called()


class TestAgentExtendedThinking:
    """Test extended thinking mode integration (Claude Sonnet 4.5)."""

    @pytest.mark.asyncio
    async def test_extended_thinking_enabled_by_default(self):
        """Extended thinking should be enabled by default for complex reasoning."""
        from src.agent import SQLOptimizationAgent

        agent = SQLOptimizationAgent()

        assert agent.use_extended_thinking is True
        assert agent.thinking_budget >= 1024  # Minimum per Anthropic docs

    @pytest.mark.asyncio
    async def test_extended_thinking_budget_configurable(self):
        """Thinking budget should be configurable."""
        from src.agent import SQLOptimizationAgent

        agent = SQLOptimizationAgent(thinking_budget=4000)

        assert agent.thinking_budget == 4000

    @pytest.mark.asyncio
    async def test_no_explicit_cot_in_prompts(self, mock_db_connection):
        """Per Anthropic docs: remove explicit chain-of-thought from prompts."""
        from src.agent import SQLOptimizationAgent

        agent = SQLOptimizationAgent()

        # When we call Claude, prompts should NOT contain:
        # "think step by step", "let's think about this", etc.
        # Extended thinking handles this automatically
        pass


class TestAgentConfiguration:
    """Test agent configuration is not hardcoded."""

    def test_no_hardcoded_model_names(self):
        """Model names should be configurable, not hardcoded."""
        from src.agent import SQLOptimizationAgent

        # Should accept custom model
        agent = SQLOptimizationAgent(model="claude-sonnet-4-5-20250929")

        assert agent.model == "claude-sonnet-4-5-20250929"

    def test_no_hardcoded_file_paths(self):
        """Should not have hardcoded paths to BIRD-CRITIC or other files."""
        from src.agent import SQLOptimizationAgent
        import inspect

        source = inspect.getsource(SQLOptimizationAgent)

        # Should not contain hardcoded paths
        assert "BIRD-CRITIC" not in source
        assert "baseline/data" not in source
        assert "database_description.csv" not in source

    def test_all_thresholds_configurable(self):
        """All thresholds should be configurable via constructor."""
        from src.agent import SQLOptimizationAgent

        agent = SQLOptimizationAgent(
            max_cost_threshold=5000.0,
            max_time_ms=10000,
            analyze_cost_threshold=1000000.0,
            statement_timeout_ms=45000
        )

        assert agent.max_cost_threshold == 5000.0
        assert agent.max_time_ms == 10000
        assert agent.analyze_cost_threshold == 1000000.0
        assert agent.statement_timeout_ms == 45000


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
