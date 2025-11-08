import os
import sys
import pytest
import asyncio

# Ensure project root and src are importable
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from optimize_cli import OptimizationTracer
from agent import SQLOptimizationAgent
from actions import Action, ActionType


def test_traced_plan_accepts_and_forwards_iteration_history(monkeypatch):
    # Ensure anthropic client can be constructed without real key usage
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    # Create agent with minimal iterations to keep test fast
    agent = SQLOptimizationAgent(max_iterations=1, use_extended_thinking=False)

    # Stub analyze to avoid DB calls and return a valid analysis structure
    async def fake_analyze(query, db_conn, constraints, task=None):
        return {
            "success": True,
            "feedback": {
                "status": "fail",
                "priority": "HIGH",
                "reason": "test stub"
            },
            "technical_analysis": {
                "total_cost": 1000.0,
                "bottlenecks": []
            }
        }

    forwarded = {}

    # Stub plan to capture the forwarded iteration_history parameter
    async def fake_plan(task, current_query, feedback, iteration, db_connection_string=None, executed_ddls=None, iteration_history=None):
        forwarded["iteration_history"] = iteration_history
        return Action(type=ActionType.DONE, reasoning="stop")

    # Apply stubs
    agent._analyze_query = fake_analyze
    agent._plan_action = fake_plan

    tracer = OptimizationTracer(agent)

    # Run a minimal optimization trace; should not raise TypeError
    constraints = {
        "max_cost": 10000.0,
        "max_time_ms": 30000,
        "analyze_cost_threshold": 5_000_000.0,
    }

    result = asyncio.run(tracer.optimize_with_trace("SELECT 1", "postgresql://localhost/testdb", constraints))

    # Verify the result and that iteration_history was forwarded as a list
    assert result.success is True
    assert "iteration_history" in forwarded
    assert isinstance(forwarded["iteration_history"], list)
