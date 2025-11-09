#!/usr/bin/env python3
"""
Autonomous SQL Optimization Agent Demo

Demonstrates the ReAct-style optimization loop on real queries.

Usage:
    export ANTHROPIC_API_KEY='your-key'
    export DB_CONNECTION='postgresql://localhost:5432/testdb'
    python run_agent.py

Requirements:
    - ANTHROPIC_API_KEY environment variable
    - DB_CONNECTION environment variable
    - PostgreSQL database with test data
"""

import asyncio
import os
import sys

# Load environment variables from .env file if present
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # dotenv is optional

# Add project root to path for src package imports
ROOT = os.path.abspath(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from src.agent import SQLOptimizationAgent


async def demo_index_optimization():
    """
    Demo: Simple query optimization (Seq Scan → Index Scan)
    """
    print("\n" + "=" * 70)
    print("DEMO: Autonomous Index Creation")
    print("=" * 70)

    # Get database connection from environment
    db_conn = os.environ.get("DB_CONNECTION")
    if not db_conn:
        print("Error: DB_CONNECTION environment variable not set")
        print("   Example: export DB_CONNECTION='postgresql://localhost:5432/testdb'")
        sys.exit(1)

    # Initialize agent
    agent = SQLOptimizationAgent(
        max_iterations=5,
        timeout_seconds=120,
        use_extended_thinking=True,
        thinking_budget=4000,
    )

    # Example query with performance issues
    query = "SELECT * FROM users WHERE email = 'alice@example.com'"

    print(f"\nQuery: {query}")
    print(f"Database: {db_conn}\n")

    # Run autonomous optimization
    result = await agent.optimize_query(
        sql=query,
        db_connection=db_conn,
        max_cost=1000.0,
        max_time_ms=5000,
    )

    # Display results
    print("\n" + "=" * 70)
    print("OPTIMIZATION COMPLETE")
    print("=" * 70)
    print(f"Success:       {result['success']}")
    print(f"Reason:        {result['reason']}")
    print(f"Final Query:   {result['final_query']}")

    if result['actions']:
        print("\nActions Taken:")
        for i, action in enumerate(result['actions'], 1):
            print(f"  {i}. {action.type.value}")
            print(f"     Reasoning: {action.reasoning}")
            if action.ddl:
                print(f"     DDL: {action.ddl}")
            if action.new_query:
                print(f"     New Query: {action.new_query[:60]}...")
            print()

    if result['metrics']:
        print("Performance Metrics:")
        for key, value in result['metrics'].items():
            print(f"  {key}: {value}")

    return result


async def demo_query_rewrite():
    """
    Demo: Query rewrite optimization
    """
    print("\n" + "=" * 70)
    print("DEMO: Query Rewrite Optimization")
    print("=" * 70)

    db_conn = os.environ.get("DB_CONNECTION")
    if not db_conn:
        print("Error: DB_CONNECTION environment variable not set")
        sys.exit(1)

    agent = SQLOptimizationAgent(
        max_iterations=5,
        use_extended_thinking=True,
    )

    # Example query that could benefit from rewrite
    query = """
    SELECT DISTINCT customer_id, customer_name
    FROM orders o
    JOIN customers c ON o.customer_id = c.id
    WHERE order_date > '2024-01-01'
    """

    print(f"\nQuery: {query}")
    print(f"Database: {db_conn}\n")

    result = await agent.optimize_query(
        sql=query,
        db_connection=db_conn,
        max_cost=5000.0,
        max_time_ms=10000,
    )

    print("\n" + "=" * 70)
    print("OPTIMIZATION COMPLETE")
    print("=" * 70)
    print(f"Success: {result['success']}")
    print(f"Final Query:\n{result['final_query']}")

    return result


async def main():
    """Run all demos"""
    # Check for API key
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("Error: ANTHROPIC_API_KEY environment variable not set")
        print("   Get your key from: https://console.anthropic.com/")
        sys.exit(1)

    print("\n" + "=" * 70)
    print("SQL OPTIMIZATION AGENT - AUTONOMOUS DEMO")
    print("=" * 70)

    try:
        # Run demo 1: Index optimization
        await demo_index_optimization()

        # Optionally run demo 2: Query rewrite
        # await demo_query_rewrite()

    except KeyboardInterrupt:
        print("\n\nDemo interrupted by user")
    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
