#!/usr/bin/env python3
"""
SQL Optimization CLI

Interactive command-line interface for autonomous query optimization.

Usage:
    # Analyze a single query
    python cli.py --query "SELECT * FROM users WHERE email='test@example.com'" \\
                  --db-connection postgresql://localhost/mydb

    # Interactive mode
    python cli.py --db-connection postgresql://localhost/mydb --interactive

    # From file
    python cli.py --query-file queries/slow.sql --db-connection postgresql://localhost/mydb

Requirements:
    - ANTHROPIC_API_KEY environment variable
    - PostgreSQL database connection
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path

# Add src to path
ROOT = Path(__file__).parent
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from agent import SQLOptimizationAgent


# ANSI Colors for terminal output
class Color:
    BOLD = '\033[1m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    END = '\033[0m'


def print_result(result: dict):
    """Print optimization result in a readable format."""
    print(f"\n{Color.BOLD}{'='*70}{Color.END}")
    print(f"{Color.BOLD}OPTIMIZATION RESULT{Color.END}")
    print(f"{Color.BOLD}{'='*70}{Color.END}\n")

    # Status
    if result['success']:
        print(f"{Color.GREEN}✓ Status: SUCCESS{Color.END}")
    else:
        print(f"{Color.YELLOW}⚠ Status: NOT OPTIMIZED{Color.END}")

    print(f"  Reason: {result['reason']}")
    print(f"  Iterations: {result['iterations']}/{result.get('max_iterations', 'N/A')}")

    # Final query
    print(f"\n{Color.BOLD}Final Query:{Color.END}")
    print(f"{Color.CYAN}{result['final_query']}{Color.END}")

    # Actions taken
    if result['actions']:
        print(f"\n{Color.BOLD}Actions Taken:{Color.END}")
        for i, action in enumerate(result['actions'], 1):
            print(f"  {i}. {Color.CYAN}{action.type.value}{Color.END}")
            print(f"     Reasoning: {action.reasoning}")
            if action.ddl:
                print(f"     DDL: {Color.GREEN}{action.ddl}{Color.END}")
            if action.new_query:
                print(f"     New Query: {action.new_query[:80]}...")

    # Metrics
    if result['metrics']:
        print(f"\n{Color.BOLD}Performance Metrics:{Color.END}")
        for key, value in result['metrics'].items():
            if isinstance(value, (int, float)):
                print(f"  {key}: {value:,.2f}")
            else:
                print(f"  {key}: {value}")


async def optimize_single_query(agent: SQLOptimizationAgent, query: str, db_connection: str, args):
    """Optimize a single query."""
    print(f"\n{Color.BOLD}Query to optimize:{Color.END}")
    print(f"{Color.CYAN}{query}{Color.END}\n")

    result = await agent.optimize_query(
        sql=query,
        db_connection=db_connection,
        max_cost=args.max_cost,
        max_time_ms=args.max_time_ms,
    )

    print_result(result)
    return result


async def interactive_mode(agent: SQLOptimizationAgent, db_connection: str, args):
    """Run in interactive mode."""
    print(f"\n{Color.BOLD}{'='*70}{Color.END}")
    print(f"{Color.BOLD}SQL OPTIMIZATION - INTERACTIVE MODE{Color.END}")
    print(f"{Color.BOLD}{'='*70}{Color.END}")
    print(f"\nEnter SQL queries to optimize (or 'quit' to exit)")
    print(f"Commands:")
    print(f"  quit     - Exit the program")
    print(f"  help     - Show this help message")
    print(f"  config   - Show current configuration\n")

    while True:
        try:
            # Get query from user
            print(f"{Color.CYAN}SQL>{Color.END} ", end='')
            query = input().strip()

            if not query:
                continue

            # Handle commands
            if query.lower() == 'quit':
                print(f"\n{Color.GREEN}Goodbye!{Color.END}")
                break

            if query.lower() == 'help':
                print(f"\nCommands:")
                print(f"  quit     - Exit the program")
                print(f"  help     - Show this help message")
                print(f"  config   - Show current configuration")
                print(f"\nEnter any SQL query to optimize it.\n")
                continue

            if query.lower() == 'config':
                print(f"\n{Color.BOLD}Current Configuration:{Color.END}")
                print(f"  Max Cost: {args.max_cost}")
                print(f"  Max Time: {args.max_time_ms}ms")
                print(f"  Max Iterations: {agent.max_iterations}")
                print(f"  Extended Thinking: {agent.use_extended_thinking}")
                print(f"  Thinking Budget: {agent.thinking_budget} tokens")
                print(f"  Statement Timeout: {agent.statement_timeout_ms}ms\n")
                continue

            # Optimize the query
            result = await agent.optimize_query(
                sql=query,
                db_connection=db_connection,
                max_cost=args.max_cost,
                max_time_ms=args.max_time_ms,
            )

            print_result(result)

        except KeyboardInterrupt:
            print(f"\n\n{Color.GREEN}Goodbye!{Color.END}")
            break
        except EOFError:
            print(f"\n{Color.GREEN}Goodbye!{Color.END}")
            break
        except Exception as e:
            print(f"\n{Color.RED}Error: {e}{Color.END}\n")


async def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="SQL Optimization CLI - Autonomous query optimization",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Single query
  %(prog)s --query "SELECT * FROM users WHERE email='test@example.com'" \\
           --db-connection postgresql://localhost/mydb

  # Interactive mode
  %(prog)s --db-connection postgresql://localhost/mydb --interactive

  # From file
  %(prog)s --query-file queries/slow.sql --db-connection postgresql://localhost/mydb
        """
    )

    # Required arguments
    parser.add_argument(
        '--db-connection',
        required=True,
        help='PostgreSQL connection string (e.g., postgresql://localhost/mydb)'
    )

    # Query input (mutually exclusive)
    query_group = parser.add_mutually_exclusive_group(required=True)
    query_group.add_argument('--query', help='SQL query to optimize')
    query_group.add_argument('--query-file', help='File containing SQL query')
    query_group.add_argument('--interactive', action='store_true', help='Interactive mode')

    # Optimization parameters
    parser.add_argument('--max-cost', type=float, default=10000.0,
                       help='Maximum acceptable query cost (default: 10000.0)')
    parser.add_argument('--max-time-ms', type=int, default=30000,
                       help='Maximum acceptable execution time in ms (default: 30000)')
    parser.add_argument('--max-iterations', type=int, default=10,
                       help='Maximum optimization iterations (default: 10)')

    # Agent configuration
    parser.add_argument('--no-extended-thinking', action='store_true',
                       help='Disable Claude extended thinking mode')
    parser.add_argument('--thinking-budget', type=int, default=4000,
                       help='Token budget for extended thinking (default: 4000)')
    parser.add_argument('--statement-timeout', type=int, default=60000,
                       help='PostgreSQL statement timeout in ms (default: 60000)')

    args = parser.parse_args()

    # Check for API key
    if not os.environ.get('ANTHROPIC_API_KEY'):
        print(f"{Color.RED}Error: ANTHROPIC_API_KEY environment variable not set{Color.END}")
        print(f"Get your key from: https://console.anthropic.com/")
        sys.exit(1)

    # Initialize agent
    agent = SQLOptimizationAgent(
        max_iterations=args.max_iterations,
        use_extended_thinking=not args.no_extended_thinking,
        thinking_budget=args.thinking_budget,
        statement_timeout_ms=args.statement_timeout,
    )

    # Run based on mode
    if args.interactive:
        await interactive_mode(agent, args.db_connection, args)
    else:
        # Get query from file or argument
        if args.query_file:
            query_path = Path(args.query_file)
            if not query_path.exists():
                print(f"{Color.RED}Error: File not found: {args.query_file}{Color.END}")
                sys.exit(1)
            query = query_path.read_text().strip()
        else:
            query = args.query

        await optimize_single_query(agent, query, args.db_connection, args)


if __name__ == '__main__':
    asyncio.run(main())
