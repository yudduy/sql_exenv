#!/usr/bin/env python3
"""
Phase 2 Integration Tests

Tests the full autonomous agent workflow using mocks to avoid:
- Database dependencies
- Anthropic API costs

Validates:
- Complete optimization loop execution
- LLM response handling
- Database operation simulation
- Error recovery
- Multi-iteration scenarios
"""

import sys
import os
import asyncio
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from dataclasses import asdict

# Add src to path
ROOT = os.path.abspath(os.path.dirname(__file__))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)


def test_single_iteration_success():
    """Test successful optimization in one iteration."""
    print("TEST 1: Single Iteration Success (CREATE_INDEX → DONE)")
    print("-" * 60)

    from agentic_dba import SQLOptimizationAgent, BIRDCriticTask

    # Mock the LLM response for CREATE_INDEX
    mock_llm_response_create = Mock()
    mock_llm_response_create.content = [
        Mock(
            text='{"action": "CREATE_INDEX", "reasoning": "Seq scan detected", "ddl": "CREATE INDEX idx_email ON users(email);", "confidence": 0.95}'
        )
    ]

    # Mock the LLM response for DONE
    mock_llm_response_done = Mock()
    mock_llm_response_done.content = [
        Mock(
            text='{"action": "DONE", "reasoning": "Query optimized, cost within limits"}'
        )
    ]

    # Mock the optimization tool responses
    mock_feedback_fail = {
        "success": True,
        "feedback": {
            "status": "fail",
            "reason": "Cost 55,072 exceeds limit 1,000",
            "suggestion": "CREATE INDEX idx_email ON users(email);",
            "priority": "HIGH",
        },
        "technical_analysis": {
            "total_cost": 55072.45,
            "execution_time_ms": 245.0,
            "bottlenecks": [
                {
                    "node_type": "Seq Scan",
                    "table": "users",
                    "rows": 100000,
                    "severity": "HIGH",
                }
            ],
        },
    }

    mock_feedback_pass = {
        "success": True,
        "feedback": {
            "status": "pass",
            "reason": "Cost 14.2 within limit 1,000",
            "suggestion": "No optimization needed",
            "priority": "LOW",
        },
        "technical_analysis": {
            "total_cost": 14.2,
            "execution_time_ms": 0.8,
            "bottlenecks": [],
        },
    }

    async def mock_optimize_query(*args, **kwargs):
        # First call returns fail, second returns pass
        if not hasattr(mock_optimize_query, "call_count"):
            mock_optimize_query.call_count = 0
        mock_optimize_query.call_count += 1
        return mock_feedback_fail if mock_optimize_query.call_count == 1 else mock_feedback_pass

    async def run_test():
        task = BIRDCriticTask(
            task_id="test_001",
            db_id="test_db",
            buggy_sql="SELECT * FROM users WHERE email = 'test@example.com'",
            user_query="Find user by email",
            efficiency=True,
        )

        with patch("anthropic.Anthropic") as mock_anthropic:
            # Configure mock client
            mock_client = Mock()
            mock_client.messages.create = Mock(
                side_effect=[mock_llm_response_create, mock_llm_response_done]
            )
            mock_anthropic.return_value = mock_client

            # Create agent
            with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
                agent = SQLOptimizationAgent(
                    max_iterations=3, use_extended_thinking=False
                )

                # Mock the optimization tool
                agent.optimization_tool.optimize_query = mock_optimize_query

                # Mock DDL execution
                agent._execute_ddl_sync = Mock()

                # Run optimization
                solution = await agent.solve_task(task, "postgresql://fake/db")

        # Validate results
        assert solution.success, "Solution should be successful"
        assert solution.total_iterations() == 1, f"Expected 1 iteration, got {solution.total_iterations()}"
        assert len(solution.actions) == 2, f"Expected 2 actions, got {len(solution.actions)}"
        assert solution.actions[0].type.value == "CREATE_INDEX"
        assert solution.actions[1].type.value == "DONE"

        print(f"✓ Solution successful: {solution.success}")
        print(f"✓ Iterations: {solution.total_iterations()}")
        print(f"✓ Actions: {[a.type.value for a in solution.actions]}")
        print(f"✓ Reason: {solution.reason}")
        print()

    asyncio.run(run_test())


def test_multi_iteration_optimization():
    """Test optimization requiring multiple iterations."""
    print("TEST 2: Multi-Iteration Optimization")
    print("-" * 60)

    from agentic_dba import SQLOptimizationAgent, BIRDCriticTask

    # Simulate 3 iterations: CREATE_INDEX → RUN_ANALYZE → DONE
    responses = [
        '{"action": "CREATE_INDEX", "reasoning": "Add index on user_id", "ddl": "CREATE INDEX idx_user ON orders(user_id);", "confidence": 0.9}',
        '{"action": "RUN_ANALYZE", "reasoning": "Update statistics", "ddl": "ANALYZE orders;", "confidence": 0.8}',
        '{"action": "DONE", "reasoning": "Optimized"}',
    ]

    feedbacks = [
        {
            "success": True,
            "feedback": {"status": "fail", "reason": "Seq scan", "suggestion": "Index"},
            "technical_analysis": {"total_cost": 50000, "bottlenecks": [{}]},
        },
        {
            "success": True,
            "feedback": {"status": "fail", "reason": "Bad stats", "suggestion": "Analyze"},
            "technical_analysis": {"total_cost": 30000, "bottlenecks": [{}]},
        },
        {
            "success": True,
            "feedback": {"status": "pass", "reason": "Optimized", "suggestion": "None"},
            "technical_analysis": {"total_cost": 100, "bottlenecks": []},
        },
    ]

    async def run_test():
        task = BIRDCriticTask(
            task_id="test_multi",
            db_id="test_db",
            buggy_sql="SELECT * FROM orders WHERE user_id = 123",
            user_query="Get user orders",
            efficiency=True,
        )

        iteration = [0]

        async def mock_optimize(*args, **kwargs):
            result = feedbacks[iteration[0]]
            iteration[0] = min(iteration[0] + 1, len(feedbacks) - 1)
            return result

        with patch("anthropic.Anthropic") as mock_anthropic:
            mock_client = Mock()
            mock_responses = [Mock(content=[Mock(text=r)]) for r in responses]
            mock_client.messages.create = Mock(side_effect=mock_responses)
            mock_anthropic.return_value = mock_client

            with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
                agent = SQLOptimizationAgent(max_iterations=5, use_extended_thinking=False)
                agent.optimization_tool.optimize_query = mock_optimize
                agent._execute_ddl_sync = Mock()

                solution = await agent.solve_task(task, "postgresql://fake/db")

        assert solution.success
        assert solution.total_iterations() == 2, f"Expected 2 iterations, got {solution.total_iterations()}"
        assert len(solution.actions) == 3

        print(f"✓ Multi-iteration optimization successful")
        print(f"✓ Total iterations: {solution.total_iterations()}")
        print(f"✓ Actions: {[a.type.value for a in solution.actions]}")
        print()

    asyncio.run(run_test())


def test_max_iterations_timeout():
    """Test agent stops at max iterations."""
    print("TEST 3: Max Iterations Timeout")
    print("-" * 60)

    from agentic_dba import SQLOptimizationAgent, BIRDCriticTask

    # Always return FAIL but not terminal
    response = '{"action": "CREATE_INDEX", "reasoning": "Try again", "ddl": "CREATE INDEX idx ON t(c);", "confidence": 0.5}'

    feedback = {
        "success": True,
        "feedback": {"status": "fail", "reason": "Still slow", "suggestion": "Index"},
        "technical_analysis": {"total_cost": 50000, "bottlenecks": [{}]},
    }

    async def run_test():
        task = BIRDCriticTask(
            task_id="test_timeout",
            db_id="test_db",
            buggy_sql="SELECT * FROM big_table",
            user_query="Query big table",
            efficiency=True,
        )

        async def mock_optimize(*args, **kwargs):
            return feedback

        with patch("anthropic.Anthropic") as mock_anthropic:
            mock_client = Mock()
            mock_client.messages.create = Mock(
                return_value=Mock(content=[Mock(text=response)])
            )
            mock_anthropic.return_value = mock_client

            with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
                agent = SQLOptimizationAgent(
                    max_iterations=3, use_extended_thinking=False
                )
                agent.optimization_tool.optimize_query = mock_optimize
                agent._execute_ddl_sync = Mock()

                solution = await agent.solve_task(task, "postgresql://fake/db")

        assert not solution.success, "Should fail after max iterations"
        assert "Max iterations" in solution.reason
        assert len(solution.actions) == 3, f"Expected 3 actions, got {len(solution.actions)}"

        print(f"✓ Stopped at max iterations: {len(solution.actions)}")
        print(f"✓ Reason: {solution.reason}")
        print()

    asyncio.run(run_test())


def test_query_analysis_failure():
    """Test handling of query analysis failures."""
    print("TEST 4: Query Analysis Failure Handling")
    print("-" * 60)

    from agentic_dba import SQLOptimizationAgent, BIRDCriticTask

    async def run_test():
        task = BIRDCriticTask(
            task_id="test_fail",
            db_id="test_db",
            buggy_sql="SELECT * FROM invalid_syntax WHERE",  # Broken query
            user_query="Test failure",
            efficiency=True,
        )

        async def mock_optimize_fail(*args, **kwargs):
            return {
                "success": False,
                "error": "Syntax error at position 30",
                "feedback": {
                    "status": "error",
                    "reason": "Query execution failed",
                    "suggestion": "Fix SQL syntax",
                },
            }

        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
            agent = SQLOptimizationAgent(max_iterations=3, use_extended_thinking=False)
            agent.optimization_tool.optimize_query = mock_optimize_fail

            solution = await agent.solve_task(task, "postgresql://fake/db")

        assert not solution.success, "Should fail on query error"
        assert "analysis failed" in solution.reason.lower() or "execution failed" in solution.reason.lower()

        print(f"✓ Error handled gracefully")
        print(f"✓ Reason: {solution.reason}")
        print()

    asyncio.run(run_test())


def test_llm_planning_error():
    """Test handling of LLM planning failures."""
    print("TEST 5: LLM Planning Error Handling")
    print("-" * 60)

    from agentic_dba import SQLOptimizationAgent, BIRDCriticTask

    async def run_test():
        task = BIRDCriticTask(
            task_id="test_llm_fail",
            db_id="test_db",
            buggy_sql="SELECT * FROM users",
            user_query="Test LLM failure",
            efficiency=True,
        )

        feedback = {
            "success": True,
            "feedback": {"status": "fail", "reason": "Slow", "suggestion": "Index"},
            "technical_analysis": {"total_cost": 5000, "bottlenecks": []},
        }

        async def mock_optimize(*args, **kwargs):
            return feedback

        with patch("anthropic.Anthropic") as mock_anthropic:
            # Simulate API error
            mock_client = Mock()
            mock_client.messages.create = Mock(
                side_effect=Exception("API rate limit exceeded")
            )
            mock_anthropic.return_value = mock_client

            with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
                agent = SQLOptimizationAgent(max_iterations=3, use_extended_thinking=False)
                agent.optimization_tool.optimize_query = mock_optimize

                solution = await agent.solve_task(task, "postgresql://fake/db")

        assert not solution.success, "Should fail on LLM error"
        assert len(solution.actions) > 0
        assert solution.actions[0].type.value == "FAILED"

        print(f"✓ LLM error handled gracefully")
        print(f"✓ Failure action created")
        print(f"✓ Reason: {solution.reason}")
        print()

    asyncio.run(run_test())


def test_solution_serialization():
    """Test solution can be serialized to JSON."""
    print("TEST 6: Solution JSON Serialization")
    print("-" * 60)

    from agentic_dba import Solution, Action, ActionType
    import json

    actions = [
        Action(
            type=ActionType.CREATE_INDEX,
            reasoning="Need index",
            ddl="CREATE INDEX idx ON t(c);",
            confidence=0.9,
        ),
        Action(type=ActionType.DONE, reasoning="Complete", confidence=1.0),
    ]

    solution = Solution(
        final_query="SELECT * FROM t WHERE c = 1",
        actions=actions,
        success=True,
        reason="Optimized",
        metrics={"cost": 14.2, "time": 0.8},
    )

    # Serialize to JSON
    solution_dict = solution.to_dict()
    json_str = json.dumps(solution_dict, indent=2)

    # Deserialize and validate
    parsed = json.loads(json_str)
    assert parsed["success"] is True
    assert len(parsed["actions"]) == 2
    assert parsed["actions"][0]["type"] == "CREATE_INDEX"
    assert parsed["metrics"]["cost"] == 14.2

    print(f"✓ Solution serializes to JSON")
    print(f"✓ JSON size: {len(json_str)} bytes")
    print(f"✓ Contains {len(parsed['actions'])} actions")
    print()


def run_all_tests():
    """Run all integration tests."""
    print("\n" + "=" * 60)
    print("PHASE 2 INTEGRATION TESTS (MOCKED)")
    print("=" * 60 + "\n")

    tests = [
        test_single_iteration_success,
        test_multi_iteration_optimization,
        test_max_iterations_timeout,
        test_query_analysis_failure,
        test_llm_planning_error,
        test_solution_serialization,
    ]

    passed = 0
    failed = 0

    for test_func in tests:
        try:
            test_func()
            passed += 1
        except Exception as e:
            print(f"✗ FAILED: {test_func.__name__}")
            print(f"  Error: {e}")
            import traceback

            traceback.print_exc()
            failed += 1
            print()

    print("=" * 60)
    print(f"RESULTS: {passed} passed, {failed} failed")
    print("=" * 60)

    if failed == 0:
        print("\n✅ ALL INTEGRATION TESTS PASSED!\n")
        print("Agent workflow validated:")
        print("  ✓ Single iteration optimization")
        print("  ✓ Multi-iteration refinement")
        print("  ✓ Max iteration timeout handling")
        print("  ✓ Query analysis failure recovery")
        print("  ✓ LLM planning error recovery")
        print("  ✓ Solution JSON serialization")
        print()
        print("Ready for real testing with database and API key!")
        print()
        return 0
    else:
        print(f"\n❌ {failed} test(s) failed\n")
        return 1


if __name__ == "__main__":
    sys.exit(run_all_tests())
