#!/usr/bin/env python3
"""
Demo: Stateful iteration history feature

This script demonstrates the new Tier 1 enhancement where the agent
tracks iteration history and learns from previous actions.
"""

import asyncio
import os
import sys

# Ensure src is on path
ROOT = os.path.abspath(os.path.dirname(__file__))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from agentic_dba.agent import SQLOptimizationAgent, BIRDCriticTask, IterationState


def demo_iteration_state():
    """Demo: IterationState dataclass and helper methods"""
    print("=" * 80)
    print("DEMO 1: Iteration State Tracking")
    print("=" * 80)

    # Set dummy API key for demo
    if not os.environ.get('ANTHROPIC_API_KEY'):
        os.environ['ANTHROPIC_API_KEY'] = 'sk-ant-demo-key-for-testing'

    # Create mock iteration history
    history = [
        IterationState(
            iteration=1,
            action_type="CREATE_INDEX",
            action_summary="idx_users_email",
            cost_before=55072.5,
            cost_after=800.25,
            cost_delta_pct=-98.5,
            outcome="improved",
            insight=""
        ),
        IterationState(
            iteration=2,
            action_type="CREATE_INDEX",
            action_summary="idx_users_status",
            cost_before=800.25,
            cost_after=1200.0,
            cost_delta_pct=+50.0,
            outcome="regressed",
            insight="Index created but not used by planner"
        ),
    ]

    # Create agent
    agent = SQLOptimizationAgent(max_iterations=3)

    # Format history
    formatted = agent._format_iteration_history(history)

    print("\nIteration History (Compressed Format):")
    print("-" * 80)
    print(formatted)
    print("-" * 80)

    # Calculate token savings
    full_context_tokens = 500 * len(history)  # ~500 tokens per full iteration
    compressed_tokens = len(formatted.split())  # Rough approximation
    savings_pct = (1 - compressed_tokens / full_context_tokens) * 100

    print(f"\nToken Efficiency:")
    print(f"  Full context (estimated): {full_context_tokens} tokens")
    print(f"  Compressed format: ~{compressed_tokens} tokens")
    print(f"  Savings: ~{savings_pct:.0f}%")


async def demo_action_summarization():
    """Demo: Action summarization"""
    print("\n" + "=" * 80)
    print("DEMO 2: Action Summarization")
    print("=" * 80)

    from agentic_dba.actions import Action, ActionType

    # Create agent
    agent = SQLOptimizationAgent(max_iterations=3)

    # Test different action types
    test_actions = [
        Action(
            type=ActionType.CREATE_INDEX,
            ddl="CREATE INDEX idx_users_email ON users(email);",
            reasoning="Need index for email lookup"
        ),
        Action(
            type=ActionType.RUN_ANALYZE,
            ddl="ANALYZE users;",
            reasoning="Update statistics"
        ),
        Action(
            type=ActionType.REWRITE_QUERY,
            new_query="SELECT id, email FROM users WHERE email = 'test@example.com'",
            reasoning="Avoid SELECT *"
        ),
    ]

    print("\nAction Summaries:")
    print("-" * 80)
    for action in test_actions:
        summary = agent._summarize_action(action)
        print(f"  {action.type.value:20s} → '{summary}'")
    print("-" * 80)


def demo_insight_extraction():
    """Demo: Insight extraction from feedback"""
    print("\n" + "=" * 80)
    print("DEMO 3: Insight Extraction")
    print("=" * 80)

    from agentic_dba.actions import Action, ActionType

    # Create agent
    agent = SQLOptimizationAgent(max_iterations=3)

    # Test different scenarios
    scenarios = [
        {
            "name": "Regression - Index not used",
            "feedback": {
                "technical_analysis": {
                    "bottlenecks": [
                        {"node_type": "Seq Scan", "table": "users"}
                    ]
                }
            },
            "action": Action(type=ActionType.CREATE_INDEX, ddl="CREATE INDEX idx_users_email ON users(email);", reasoning=""),
            "outcome": "regressed"
        },
        {
            "name": "Unchanged",
            "feedback": {"technical_analysis": {"bottlenecks": []}},
            "action": Action(type=ActionType.RUN_ANALYZE, ddl="ANALYZE users;", reasoning=""),
            "outcome": "unchanged"
        },
        {
            "name": "Improved",
            "feedback": {"technical_analysis": {"bottlenecks": []}},
            "action": Action(type=ActionType.CREATE_INDEX, ddl="CREATE INDEX idx_users_email ON users(email);", reasoning=""),
            "outcome": "improved"
        },
    ]

    print("\nExtracted Insights:")
    print("-" * 80)
    for scenario in scenarios:
        insight = agent._extract_insight(scenario["feedback"], scenario["action"], scenario["outcome"])
        insight_text = insight if insight else "(no insight - optimization successful)"
        print(f"  {scenario['name']:30s} → {insight_text}")
    print("-" * 80)


async def demo_full_integration():
    """Demo: Full integration (requires database)"""
    print("\n" + "=" * 80)
    print("DEMO 4: Full Agent Integration (Simulation)")
    print("=" * 80)

    print("\nThis demo shows how iteration history would flow through the agent:")
    print("1. Agent analyzes query → gets cost = 55072.5")
    print("2. Agent creates index → cost improves to 800.25 (-98.5%)")
    print("3. Iteration history records: ✓ Iter 1: CREATE_INDEX (idx_users_email) → Cost -98.5%")
    print("4. Next iteration, agent sees history in prompt")
    print("5. Agent makes informed decision based on past success")

    print("\nTo run with real database:")
    print("  export ANTHROPIC_API_KEY='your-key'")
    print("  export DB_CONNECTION='postgresql://localhost/testdb'")
    print("  python demo_agent.py")


async def main():
    """Run all demos"""
    print("\n" + "=" * 80)
    print("STATEFUL ITERATION HISTORY DEMO")
    print("Tier 1 Enhancement - Compressed State Representation")
    print("=" * 80)

    # Demo 1: Iteration state tracking
    demo_iteration_state()

    # Demo 2: Action summarization
    await demo_action_summarization()

    # Demo 3: Insight extraction
    demo_insight_extraction()

    # Demo 4: Full integration
    await demo_full_integration()

    print("\n" + "=" * 80)
    print("✅ All demos completed successfully!")
    print("=" * 80)
    print("\nKey Benefits:")
    print("  - 6-12% token overhead (minimal!)")
    print("  - Agent learns from previous actions")
    print("  - Prevents repeating ineffective optimizations")
    print("  - Fresh state per new query")
    print("  - Autonomous updates after each iteration")


if __name__ == '__main__':
    asyncio.run(main())
