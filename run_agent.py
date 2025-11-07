#!/usr/bin/env python3
"""
Demo: Autonomous SQL Optimization Agent

Demonstrates the full autonomous loop:
1. Agent analyzes query
2. Agent plans action
3. Agent executes optimization
4. Agent validates improvement
5. Repeat until optimized

Usage:
    python demo_agent.py

Requirements:
    - ANTHROPIC_API_KEY environment variable
    - PostgreSQL database with test data
"""

import asyncio
import os
import sys

# Ensure src is on path
ROOT = os.path.abspath(os.path.dirname(__file__))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from agentic_dba import SQLOptimizationAgent, BIRDCriticTask


async def demo_simple_optimization():
    """
    Demo 1: Simple query optimization (Seq Scan → Index Scan)
    """
    print("\n" + "=" * 70)
    print("DEMO 1: Autonomous Index Creation")
    print("=" * 70)

    # Define a task with a slow query
    task = BIRDCriticTask(
        task_id="demo_001",
        db_id="test_db",
        buggy_sql="SELECT * FROM users WHERE email = 'alice@example.com'",
        user_query="Find user by email address",
        efficiency=True,
    )

    # Initialize agent
    agent = SQLOptimizationAgent(
        max_iterations=3,
        timeout_per_task_seconds=60,
        use_extended_thinking=True,  # Enable deep reasoning
        extended_thinking_budget=4000,  # 4K tokens for planning
    )

    # Get database connection from environment
    db_conn = os.environ.get(
        "DB_CONNECTION",
        "postgresql://localhost/testdb",
    )

    print(f"\nTask: {task.user_query}")
    print(f"Query: {task.buggy_sql}")
    print(f"Database: {db_conn}\n")

    # Run autonomous optimization
    solution = await agent.solve_task(task, db_conn)

    # Display results
    print("\n" + "=" * 70)
    print("SOLUTION")
    print("=" * 70)
    print(f"✓ Success:       {solution.success}")
    print(f"✓ Reason:        {solution.reason}")
    print(f"✓ Iterations:    {solution.total_iterations()}")
    print(f"✓ Final Query:   {solution.final_query}")

    print("\n🔧 Actions Taken:")
    for i, action in enumerate(solution.actions, 1):
        print(f"  {i}. {action.type.value}")
        print(f"     Reasoning: {action.reasoning}")
        if action.ddl:
            print(f"     DDL: {action.ddl}")
        if action.new_query:
            print(f"     New Query: {action.new_query[:60]}...")
        print()

    if solution.metrics:
        print("📊 Performance Metrics:")
        for key, value in solution.metrics.items():
            print(f"  {key}: {value}")

    return solution


async def demo_bird_critic_style():
    """
    Demo 2: BIRD-CRITIC style task (efficiency optimization)
    """
    print("\n" + "=" * 70)
    print("DEMO 2: BIRD-CRITIC Style Efficiency Optimization")
    print("=" * 70)

    # Simulating a BIRD-CRITIC efficiency task
    task = BIRDCriticTask(
        task_id="bird_critic_127",
        db_id="ecommerce",
        buggy_sql="""
            SELECT o.order_id, u.name, p.product_name, o.total
            FROM orders o
            JOIN users u ON o.user_id = u.user_id
            JOIN products p ON o.product_id = p.product_id
            WHERE u.country = 'USA'
            AND o.order_date >= '2024-01-01'
        """,
        user_query="Get all orders from US customers in 2024 with user and product details",
        solution_sql="-- Ground truth with proper indexes",
        efficiency=True,
    )

    agent = SQLOptimizationAgent(
        max_iterations=5,
        timeout_per_task_seconds=120,
        use_extended_thinking=True,
        extended_thinking_budget=8000,  # More budget for complex tasks
    )

    db_conn = os.environ.get("DB_CONNECTION", "postgresql://localhost/ecommerce")

    print(f"\nTask ID: {task.task_id}")
    print(f"Database: {task.db_id}")
    print(f"User Query: {task.user_query}")
    print(f"\nBuggy SQL:\n{task.buggy_sql}\n")

    solution = await agent.solve_task(
        task,
        db_conn,
        constraints={
            "max_cost": 50000.0,  # BIRD-CRITIC typical threshold
            "max_time_ms": 30000,
            "analyze_cost_threshold": 5_000_000,
        },
    )

    # Results
    print("\n" + "=" * 70)
    print("AUTONOMOUS OPTIMIZATION COMPLETE")
    print("=" * 70)
    print(f"Success: {'✅ YES' if solution.success else '❌ NO'}")
    print(f"Reason: {solution.reason}")
    print(f"Total Iterations: {solution.total_iterations()}")

    print("\n📋 Optimization Trace:")
    for i, action in enumerate(solution.actions, 1):
        status = "✓" if action.type.value in ["DONE"] else "→"
        print(f"{status} Step {i}: {action.type.value}")
        print(f"  Reasoning: {action.reasoning}")
        if action.ddl:
            print(f"  DDL: {action.ddl[:80]}...")

    return solution


async def demo_comparison():
    """
    Demo 3: Before/After Comparison
    """
    print("\n" + "=" * 70)
    print("DEMO 3: Performance Improvement Comparison")
    print("=" * 70)

    task = BIRDCriticTask(
        task_id="demo_comparison",
        db_id="analytics",
        buggy_sql="SELECT COUNT(*) FROM events WHERE user_id = 12345 AND event_type = 'click'",
        user_query="Count click events for a specific user",
        efficiency=True,
    )

    agent = SQLOptimizationAgent(max_iterations=3)
    db_conn = os.environ.get("DB_CONNECTION", "postgresql://localhost/analytics")

    print("\n🔴 BEFORE Optimization:")
    print(f"Query: {task.buggy_sql}")
    print("Expected: Sequential Scan on large events table")
    print("Performance: SLOW (scanning millions of rows)")

    solution = await agent.solve_task(task, db_conn)

    if solution.success:
        print("\n🟢 AFTER Optimization:")
        print(f"Success: ✅")
        print(f"Iterations: {solution.total_iterations()}")

        # Show what was done
        for action in solution.actions:
            if action.type.value == "CREATE_INDEX":
                print(f"\nIndex Created: {action.ddl}")
                print("Expected: Index Scan instead of Sequential Scan")
                print("Performance: FAST (direct index lookup)")

    return solution


async def main():
    """Run all demos."""

    # Check for API key
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ERROR: ANTHROPIC_API_KEY environment variable not set")
        print("Please export your API key:")
        print("  export ANTHROPIC_API_KEY='your-key-here'")
        sys.exit(1)

    # Check for database connection
    if not os.environ.get("DB_CONNECTION"):
        print("WARNING: DB_CONNECTION not set, using default postgresql://localhost/testdb")
        print("Set custom connection:")
        print("  export DB_CONNECTION='postgresql://user:pass@host/db'")
        print()

    try:
        # Run demos
        await demo_simple_optimization()
        # await demo_bird_critic_style()  # Uncomment if you have test data
        # await demo_comparison()  # Uncomment for before/after demo

        print("\n" + "=" * 70)
        print("✅ ALL DEMOS COMPLETE")
        print("=" * 70)
        print("\nNext Steps:")
        print("1. Run against BIRD-CRITIC benchmark:")
        print("   python -m agentic_dba.bird_critic_runner \\")
        print("     --dataset ./mini_dev/flash-exp.json \\")
        print("     --db-connection postgresql://localhost/bird_db \\")
        print("     --limit 10")
        print()
        print("2. Evaluate on full dataset and submit to leaderboard")
        print()

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
