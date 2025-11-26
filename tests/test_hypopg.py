"""
Tests for HypoPG Integration (Virtual Index Testing)

TDD tests for the pragmatic V1 implementation:
1. Extension Detector - detects hypopg availability
2. HypoPG Tool - virtual index testing
3. TEST_INDEX Action - agent integration
"""

import json
from unittest.mock import MagicMock, Mock, patch

import pytest


class TestExtensionDetector:
    """Test ExtensionDetector for hypopg detection."""

    def test_detector_initialization(self):
        """Detector should initialize with supported extensions."""
        from src.extensions.detector import ExtensionDetector

        detector = ExtensionDetector()
        assert "hypopg" in detector.SUPPORTED_EXTENSIONS

    def test_detect_returns_empty_on_connection_failure(self):
        """Detector should return empty dict on connection failure."""
        from src.extensions.detector import ExtensionDetector

        detector = ExtensionDetector()
        result = detector.detect("postgresql://invalid:invalid@localhost:5432/nonexistent")

        assert result == {}
        assert detector.has_hypopg(result) is False

    def test_has_hypopg_with_version(self):
        """has_hypopg should return True when version is present."""
        from src.extensions.detector import ExtensionDetector

        detector = ExtensionDetector()

        assert detector.has_hypopg({"hypopg": "1.3.1"}) is True
        assert detector.has_hypopg({"hypopg": "1.0"}) is True

    def test_has_hypopg_without_version(self):
        """has_hypopg should return False when version is None or missing."""
        from src.extensions.detector import ExtensionDetector

        detector = ExtensionDetector()

        assert detector.has_hypopg({}) is False
        assert detector.has_hypopg({"hypopg": None}) is False
        assert detector.has_hypopg({"other_ext": "1.0"}) is False

    def test_detect_with_mock_connection(self):
        """Detector should query pg_available_extensions."""
        from src.extensions.detector import ExtensionDetector

        detector = ExtensionDetector()

        with patch('psycopg2.connect') as mock_connect:
            mock_cursor = MagicMock()
            mock_cursor.fetchall.return_value = [("hypopg", "1.3.1")]
            mock_cursor.__enter__ = Mock(return_value=mock_cursor)
            mock_cursor.__exit__ = Mock(return_value=False)
            mock_connect.return_value.cursor.return_value = mock_cursor

            result = detector.detect("postgresql://localhost/test")

            assert "hypopg" in result
            assert result["hypopg"] == "1.3.1"


class TestHypoPGTool:
    """Test HypoPGTool for virtual index testing."""

    def test_tool_initialization(self):
        """Tool should store connection string."""
        from src.tools.hypopg import HypoPGTool

        tool = HypoPGTool("postgresql://localhost/test")
        assert tool.connection_string == "postgresql://localhost/test"

    def test_tool_min_improvement_threshold(self):
        """Tool should have configurable improvement threshold."""
        from src.tools.hypopg import HypoPGTool

        tool = HypoPGTool("postgresql://localhost/test")
        assert tool.MIN_IMPROVEMENT_PCT == 10.0

    def test_test_index_returns_error_on_connection_failure(self):
        """Tool should return error result on connection failure."""
        from src.tools.hypopg import HypoPGTool

        tool = HypoPGTool("postgresql://invalid:invalid@localhost:5432/nonexistent")
        result = tool.test_index(
            "SELECT * FROM users WHERE id = 1",
            "CREATE INDEX idx_test ON users(id)"
        )

        assert result.error is not None
        assert result.would_be_used is False
        assert result.improvement_pct == 0

    def test_is_worthwhile_with_good_improvement(self):
        """is_worthwhile should return True for significant improvement."""
        from src.tools.hypopg import HypoIndexResult, HypoPGTool

        tool = HypoPGTool("postgresql://localhost/test")

        # Good result: 50% improvement, index used
        good_result = HypoIndexResult(
            index_def="CREATE INDEX idx_test ON users(id)",
            would_be_used=True,
            cost_before=1000,
            cost_after=500,
            improvement_pct=50.0,
            plan_snippet="Index Scan: idx_test"
        )

        assert tool.is_worthwhile(good_result) is True

    def test_is_worthwhile_with_poor_improvement(self):
        """is_worthwhile should return False for marginal improvement."""
        from src.tools.hypopg import HypoIndexResult, HypoPGTool

        tool = HypoPGTool("postgresql://localhost/test")

        # Poor result: only 5% improvement
        poor_result = HypoIndexResult(
            index_def="CREATE INDEX idx_test ON users(id)",
            would_be_used=True,
            cost_before=1000,
            cost_after=950,
            improvement_pct=5.0,
            plan_snippet="Index Scan: idx_test"
        )

        assert tool.is_worthwhile(poor_result) is False

    def test_is_worthwhile_with_unused_index(self):
        """is_worthwhile should return False if index wouldn't be used."""
        from src.tools.hypopg import HypoIndexResult, HypoPGTool

        tool = HypoPGTool("postgresql://localhost/test")

        # Index not used by planner
        unused_result = HypoIndexResult(
            index_def="CREATE INDEX idx_test ON users(id)",
            would_be_used=False,
            cost_before=1000,
            cost_after=1000,
            improvement_pct=0,
            plan_snippet="Seq Scan on users"
        )

        assert tool.is_worthwhile(unused_result) is False

    def test_is_worthwhile_with_error(self):
        """is_worthwhile should return False if there was an error."""
        from src.tools.hypopg import HypoIndexResult, HypoPGTool

        tool = HypoPGTool("postgresql://localhost/test")

        error_result = HypoIndexResult(
            index_def="CREATE INDEX idx_test ON users(id)",
            would_be_used=False,
            cost_before=0,
            cost_after=0,
            improvement_pct=0,
            plan_snippet="",
            error="Connection failed"
        )

        assert tool.is_worthwhile(error_result) is False

    def test_hypo_index_result_to_dict(self):
        """HypoIndexResult should serialize to dict."""
        from src.tools.hypopg import HypoIndexResult

        result = HypoIndexResult(
            index_def="CREATE INDEX idx_test ON users(id)",
            would_be_used=True,
            cost_before=1000,
            cost_after=500,
            improvement_pct=50.0,
            plan_snippet="Index Scan"
        )

        d = result.to_dict()
        assert d["index_def"] == "CREATE INDEX idx_test ON users(id)"
        assert d["would_be_used"] is True
        assert d["improvement_pct"] == 50.0


class TestTESTINDEXAction:
    """Test TEST_INDEX action type."""

    def test_test_index_action_type_exists(self):
        """TEST_INDEX should be a valid ActionType."""
        from src.actions import ActionType

        assert hasattr(ActionType, "TEST_INDEX")
        assert ActionType.TEST_INDEX.value == "TEST_INDEX"

    def test_parse_test_index_action(self):
        """Parser should handle TEST_INDEX action."""
        from src.actions import ActionType, parse_action_from_llm_response

        response = json.dumps({
            "type": "TEST_INDEX",
            "ddl": "CREATE INDEX idx_users_email ON users(email)",
            "reasoning": "Test if email index helps"
        })

        action = parse_action_from_llm_response(response)

        assert action.type == ActionType.TEST_INDEX
        assert action.ddl == "CREATE INDEX idx_users_email ON users(email)"
        assert action.reasoning == "Test if email index helps"

    def test_parse_test_index_requires_ddl(self):
        """TEST_INDEX should require ddl field."""
        from src.actions import parse_action_from_llm_response

        response = json.dumps({
            "type": "TEST_INDEX",
            "reasoning": "Test index without ddl"
        })

        with pytest.raises(ValueError, match="TEST_INDEX action requires 'ddl' field"):
            parse_action_from_llm_response(response)

    def test_test_index_requires_db_mutation(self):
        """TEST_INDEX should report as potentially mutating."""
        from src.actions import Action, ActionType

        action = Action(
            type=ActionType.TEST_INDEX,
            ddl="CREATE INDEX idx_test ON users(id)",
            reasoning="Testing"
        )

        # TEST_INDEX may create real index if beneficial
        assert action.requires_db_mutation() is True

    def test_test_index_is_not_terminal(self):
        """TEST_INDEX should not be a terminal action."""
        from src.actions import Action, ActionType

        action = Action(
            type=ActionType.TEST_INDEX,
            ddl="CREATE INDEX idx_test ON users(id)",
            reasoning="Testing"
        )

        assert action.is_terminal() is False


class TestAgentHypoPGIntegration:
    """Test agent integration with HypoPG."""

    @pytest.fixture
    def mock_db_connection(self):
        return "postgresql://localhost:5432/testdb"

    def test_agent_initializes_extension_detector(self):
        """Agent should initialize ExtensionDetector."""
        from src.agent import SQLOptimizationAgent

        agent = SQLOptimizationAgent()

        assert agent.extension_detector is not None
        assert agent.can_use_hypopg is False  # Default before detection
        assert agent.hypopg_tool is None  # Lazy init

    @pytest.mark.asyncio
    async def test_agent_detects_hypopg_on_optimize(self, mock_db_connection):
        """Agent should detect hypopg at start of optimize_query."""
        from src.agent import SQLOptimizationAgent

        agent = SQLOptimizationAgent()

        with patch.object(agent.extension_detector, 'detect') as mock_detect, \
             patch.object(agent.extension_detector, 'has_hypopg') as mock_has_hypopg, \
             patch.object(agent, '_analyze_query') as mock_analyze, \
             patch.object(agent, '_plan_action') as mock_plan:

            mock_detect.return_value = {"hypopg": "1.3.1"}
            mock_has_hypopg.return_value = True
            mock_analyze.return_value = {
                "analysis": {"total_cost": 100, "bottlenecks": []},
                "feedback": {"status": "pass", "reason": "OK", "suggestion": "", "priority": "LOW"}
            }
            mock_plan.return_value = Mock(type=Mock(value="DONE"), reasoning="Done", is_terminal=lambda: True)

            await agent.optimize_query(
                sql="SELECT * FROM users",
                db_connection=mock_db_connection,
                validate_correctness=False
            )

            mock_detect.assert_called_once_with(mock_db_connection)

    @pytest.mark.asyncio
    async def test_agent_creates_hypopg_tool_when_available(self, mock_db_connection):
        """Agent should create HypoPGTool when hypopg is available."""
        from src.agent import SQLOptimizationAgent

        agent = SQLOptimizationAgent()

        with patch.object(agent.extension_detector, 'detect') as mock_detect, \
             patch.object(agent.extension_detector, 'has_hypopg') as mock_has_hypopg, \
             patch.object(agent, '_analyze_query') as mock_analyze, \
             patch.object(agent, '_plan_action') as mock_plan:

            mock_detect.return_value = {"hypopg": "1.3.1"}
            mock_has_hypopg.return_value = True
            mock_analyze.return_value = {
                "analysis": {"total_cost": 100, "bottlenecks": []},
                "feedback": {"status": "pass", "reason": "OK", "suggestion": "", "priority": "LOW"}
            }
            mock_plan.return_value = Mock(type=Mock(value="DONE"), reasoning="Done", is_terminal=lambda: True)

            await agent.optimize_query(
                sql="SELECT * FROM users",
                db_connection=mock_db_connection,
                validate_correctness=False
            )

            assert agent.can_use_hypopg is True
            assert agent.hypopg_tool is not None

    @pytest.mark.asyncio
    async def test_execute_test_index_falls_back_without_hypopg(self, mock_db_connection):
        """TEST_INDEX should fall back to CREATE_INDEX without hypopg."""
        from src.actions import Action, ActionType
        from src.agent import SQLOptimizationAgent

        agent = SQLOptimizationAgent()
        agent.can_use_hypopg = False
        agent.hypopg_tool = None

        action = Action(
            type=ActionType.TEST_INDEX,
            ddl="CREATE INDEX idx_test ON users(id)",
            reasoning="Testing"
        )

        with patch.object(agent, '_execute_ddl') as mock_execute_ddl:
            mock_execute_ddl.return_value = {"success": True, "message": "Index created"}

            result = await agent._execute_test_index(action, mock_db_connection, "SELECT * FROM users")

            mock_execute_ddl.assert_called_once_with(action.ddl, mock_db_connection)

    @pytest.mark.asyncio
    async def test_execute_test_index_creates_index_when_beneficial(self, mock_db_connection):
        """TEST_INDEX should create real index when improvement > 10%."""
        from src.actions import Action, ActionType
        from src.agent import SQLOptimizationAgent
        from src.tools.hypopg import HypoIndexResult

        agent = SQLOptimizationAgent()
        agent.can_use_hypopg = True

        # Mock HypoPGTool
        mock_tool = Mock()
        mock_tool.test_index.return_value = HypoIndexResult(
            index_def="CREATE INDEX idx_test ON users(id)",
            would_be_used=True,
            cost_before=1000,
            cost_after=200,
            improvement_pct=80.0,
            plan_snippet="Index Scan"
        )
        mock_tool.is_worthwhile.return_value = True
        agent.hypopg_tool = mock_tool

        action = Action(
            type=ActionType.TEST_INDEX,
            ddl="CREATE INDEX idx_test ON users(id)",
            reasoning="Testing"
        )

        with patch.object(agent, '_execute_ddl') as mock_execute_ddl:
            mock_execute_ddl.return_value = {"success": True, "message": "Index created"}

            result = await agent._execute_test_index(action, mock_db_connection, "SELECT * FROM users")

            # Should create the real index
            mock_execute_ddl.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_test_index_skips_when_not_beneficial(self, mock_db_connection):
        """TEST_INDEX should skip index creation when improvement < 10%."""
        from src.actions import Action, ActionType
        from src.agent import SQLOptimizationAgent
        from src.tools.hypopg import HypoIndexResult

        agent = SQLOptimizationAgent()
        agent.can_use_hypopg = True

        # Mock HypoPGTool with poor result
        mock_tool = Mock()
        mock_tool.test_index.return_value = HypoIndexResult(
            index_def="CREATE INDEX idx_test ON users(id)",
            would_be_used=True,
            cost_before=1000,
            cost_after=950,
            improvement_pct=5.0,
            plan_snippet="Index Scan"
        )
        mock_tool.is_worthwhile.return_value = False
        agent.hypopg_tool = mock_tool

        action = Action(
            type=ActionType.TEST_INDEX,
            ddl="CREATE INDEX idx_test ON users(id)",
            reasoning="Testing"
        )

        with patch.object(agent, '_execute_ddl') as mock_execute_ddl:
            result = await agent._execute_test_index(action, mock_db_connection, "SELECT * FROM users")

            # Should NOT create the real index
            mock_execute_ddl.assert_not_called()
            assert result["success"] is True
            assert "skipped" in result["message"].lower()


class TestLLMPromptWithHypoPG:
    """Test that LLM prompt includes hypopg context when available."""

    @pytest.mark.asyncio
    async def test_prompt_includes_test_index_when_hypopg_available(self):
        """Planning prompt should mention TEST_INDEX when hypopg is available."""
        from src.agent import SQLOptimizationAgent

        agent = SQLOptimizationAgent()
        agent.can_use_hypopg = True

        with patch.object(agent.llm_client, 'chat') as mock_chat:
            mock_chat.return_value = Mock(content='{"type": "DONE", "reasoning": "test"}')

            await agent._plan_action(
                current_query="SELECT * FROM users",
                analysis={
                    "analysis": {"total_cost": 100, "bottlenecks": []},
                    "feedback": {"status": "fail", "reason": "High cost", "suggestion": "Add index", "priority": "HIGH"}
                },
                previous_actions=[],
                failed_actions=[],
                iteration=1
            )

            # Check that the prompt mentions TEST_INDEX
            call_args = mock_chat.call_args
            prompt = call_args[1]["messages"][0]["content"] if call_args[1] else call_args[0][0][0]["content"]
            assert "TEST_INDEX" in prompt
            assert "hypopg" in prompt.lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
