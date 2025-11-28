#!/usr/bin/env python3
"""
Exque Environment CLI

Chat-based command-line interface for autonomous SQL query optimization.

Usage:
    # Set environment variables (recommended)
    export ANTHROPIC_API_KEY='your-key'
    export DB_CONNECTION='postgresql://localhost:5432/mydb'

    # Chat mode (default)
    python cli.py

    # Single query mode
    python cli.py --query "SELECT * FROM users WHERE email='test@example.com'"

    # Query from file
    python cli.py --query-file slow_query.sql

    # Override with explicit connection string
    python cli.py --query "..." --db-connection postgresql://other-host:5432/db

Requirements:
    - ANTHROPIC_API_KEY environment variable
    - DB_CONNECTION environment variable (or --db-connection argument)
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path

# Load environment variables from .env file if present
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # dotenv is optional

# Add project root to path for src package imports
ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from src.agent import SQLOptimizationAgent
from src.display import display
from src.validators.base import ValidationResult
from urllib.parse import urlparse
import psycopg2


def extract_db_name(connection_string: str) -> str:
    """Extract database name from connection string."""
    try:
        parsed = urlparse(connection_string)
        db_name = parsed.path.lstrip('/')
        return db_name if db_name else "unknown"
    except Exception:
        return "unknown"


def test_connection(connection_string: str) -> tuple[bool, str]:
    """Test database connection. Returns (success, error_message)."""
    try:
        conn = psycopg2.connect(connection_string)
        conn.close()
        return True, ""
    except Exception as e:
        return False, str(e)


def examine_database(connection_string: str) -> tuple[bool, int, str]:
    """
    Examine database schema to understand structure.
    Returns (success, table_count, error_message).
    """
    try:
        conn = psycopg2.connect(connection_string)
        with conn.cursor() as cur:
            cur.execute("""
                SELECT COUNT(*) FROM information_schema.tables
                WHERE table_schema = CURRENT_SCHEMA AND table_type = 'BASE TABLE'
            """)
            table_count = cur.fetchone()[0]
        conn.close()
        return True, table_count, ""
    except Exception as e:
        return False, 0, str(e)


def print_validation_result(validation: ValidationResult):
    """Print validation result in user-friendly format."""
    display.newline()
    display.subheader("Correctness Validation")

    if validation.passed:
        display.success(f"✓ Validation PASSED ({validation.method})")
        display.metric("Confidence", f"{validation.confidence * 100:.0f}%")
        display.metric("Queries Executed", str(validation.queries_executed))
        display.metric("Validation Time", f"{validation.execution_time_ms:.0f}ms")

        if validation.confidence < 0.5:
            display.warning(f"Note: {validation.metadata.get('reason', 'Low confidence validation')}")
    else:
        display.error(f"✗ Validation FAILED ({validation.method})")
        display.metric("Confidence", f"{validation.confidence * 100:.0f}%")

        display.newline()
        display.subheader("Issues Detected")
        for i, issue in enumerate(validation.issues, 1):
            print(f"\n{i}. **{issue.issue_type}** [{issue.severity}]")
            print(f"   {issue.description}")

            if issue.evidence:
                print(f"   ")
                print(f"   Evidence:")
                for key, value in issue.evidence.items():
                    if key.startswith('example_'):
                        continue  # Skip example rows for brevity
                    print(f"     - {key}: {value}")

            if issue.suggested_fix:
                print(f"   ")
                print(f"   Suggested fix:")
                for line in issue.suggested_fix.split('\n'):
                    print(f"   {line}")

        display.newline()
        display.warning(
            "Query may return incorrect results. Fix issues before optimizing performance."
        )

    display.newline()


def print_result(result: dict):
    """Print optimization result in markdown format."""
    display.newline()

    # Show validation results if present
    if 'validation' in result and result['validation']:
        print_validation_result(result['validation'])

    # Status
    if result['success']:
        display.success("Optimization successful")
    else:
        display.warning("Could not fully optimize query")

    if result['reason']:
        print(f"  {result['reason']}")

    # Final query
    display.section("Final Query", result['final_query'], code_block=True)

    # Actions taken
    if result['actions']:
        display.subheader("Actions Taken")
        for i, action in enumerate(result['actions'], 1):
            print(f"{i}. **{action.type.value}**")
            print(f"   {action.reasoning}")
            if action.ddl:
                print(f"   DDL: `{action.ddl}`")
            if action.new_query:
                print(f"   New Query: `{action.new_query[:60]}...`")

    # Metrics
    if result['metrics']:
        display.subheader("Performance Metrics")

        initial_cost = result['metrics'].get('initial_cost', 0)
        final_cost = result['metrics'].get('final_cost', 0)

        if initial_cost > 0 and final_cost > 0:
            improvement_pct = ((initial_cost - final_cost) / initial_cost) * 100
            improvement_str = f"({improvement_pct:,.1f}% improvement)" if improvement_pct > 0 else ""
            display.metric("Query Cost", f"{initial_cost:,.0f} → {final_cost:,.0f}", improvement_str)
        elif final_cost > 0:
            display.metric("Query Cost", f"{final_cost:,.0f}")

        final_time = result['metrics'].get('final_time_ms', 0)
        if final_time > 0:
            display.metric("Execution Time", f"{final_time:,.0f}ms")


async def validate_query_only(agent: SQLOptimizationAgent, query: str, db_connection: str):
    """
    Validation-only mode (no optimization).

    Runs correctness validation without performance optimization.
    """
    display.section("Validating Query Correctness", query, code_block=True)

    # Run validation directly
    validation = await agent._validate_correctness(query, db_connection)

    print_validation_result(validation)

    if not validation.passed:
        display.newline()
        display.warning(
            "Query failed correctness validation. Review issues above before proceeding."
        )
        return {'success': False, 'validation': validation}

    return {'success': True, 'validation': validation}


async def optimize_single_query(agent: SQLOptimizationAgent, query: str, db_connection: str, args):
    """Optimize a single query."""
    display.section("Query to Optimize", query, code_block=True)

    # Check if validation-only mode
    if hasattr(args, 'validate_only') and args.validate_only:
        result = await validate_query_only(agent, query, db_connection)
        return result

    # Normal optimization with optional validation
    validate_correctness = not getattr(args, 'no_validation', False)

    result = await agent.optimize_query(
        sql=query,
        db_connection=db_connection,
        max_cost=args.max_cost,
        max_time_ms=args.max_time_ms,
        validate_correctness=validate_correctness,
    )

    print_result(result)
    return result


async def chat_mode(agent: SQLOptimizationAgent, db_connection: str, args):
    """Run in chat mode."""
    display.header("Exque Environment")

    # Extract database name
    db_name = extract_db_name(db_connection)

    # Test connection
    print(f"  {display.DIM}database:{display.RESET} {db_name}")
    connected, conn_error = test_connection(db_connection)
    if connected:
        print(f"  {display.DIM}connected:{display.RESET} {display.GREEN}success{display.RESET}")
    else:
        print(f"  {display.DIM}connected:{display.RESET} {display.RED}failure{display.RESET}")
        display.error(f"Connection error: {conn_error}")
        return

    # Examine database schema
    print(f"  {display.DIM}examined:{display.RESET} {display.YELLOW}loading{display.RESET}", end='', flush=True)
    examined, table_count, exam_error = examine_database(db_connection)
    # Clear loading and print final status
    print(f"\r  {display.DIM}examined:{display.RESET} ", end='')
    if examined:
        print(f"{display.GREEN}success{display.RESET} ({table_count} tables)")
    else:
        print(f"{display.RED}failure{display.RESET}")
        display.warning(f"Could not examine database: {exam_error}")

    print("\nEnter SQL queries to optimize (or 'quit' to exit)")
    print("Commands: quit, help, config\n")

    while True:
        try:
            # Get query from user (support multi-line)
            print(f"{display.CYAN}SQL>{display.RESET} ", end='')
            lines = []
            while True:
                line = input()
                if not line.strip() and lines:
                    # Empty line after content - end of input
                    break
                if line.strip():
                    lines.append(line)
                    # If single line ends with semicolon, accept it
                    if line.strip().endswith(';') and len(lines) == 1:
                        break
                    # For multi-line, show continuation prompt
                    if lines and not line.strip().endswith(';'):
                        print(f"{display.CYAN}...>{display.RESET} ", end='')

            query = '\n'.join(lines).strip()

            if not query:
                continue

            # Handle commands
            if query.lower() == 'quit':
                display.success("Goodbye!")
                break

            if query.lower() == 'help':
                print("\nCommands:")
                print("  quit     - Exit the program")
                print("  help     - Show this help message")
                print("  config   - Show current configuration")
                print("\nEnter any SQL query to optimize it.\n")
                continue

            if query.lower() == 'config':
                display.subheader("Current Configuration")
                print(f"  Max Cost: {args.max_cost}")
                print(f"  Max Time: {args.max_time_ms}ms")
                print(f"  Extended Thinking: {agent.use_thinking}")
                print(f"  Thinking Budget: {agent.thinking_budget} tokens")
                print(f"  Statement Timeout: {agent.statement_timeout_ms}ms")
                print(f"  Safety Iteration Limit: {agent.max_iterations}\n")
                continue

            # Optimize the query
            validate_correctness = not getattr(args, 'no_validation', False)

            result = await agent.optimize_query(
                sql=query,
                db_connection=db_connection,
                max_cost=args.max_cost,
                max_time_ms=args.max_time_ms,
                validate_correctness=validate_correctness,
            )

            print_result(result)

        except KeyboardInterrupt:
            display.success("\nGoodbye!")
            break
        except EOFError:
            display.success("\nGoodbye!")
            break
        except Exception as e:
            display.error(f"Error: {e}\n")


async def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Exque Environment - Autonomous SQL query optimization",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Set environment variables first
  export DB_CONNECTION='postgresql://localhost:5432/mydb'
  export ANTHROPIC_API_KEY='your-key'

  # Chat mode (default)
  %(prog)s

  # Single query
  %(prog)s --query "SELECT * FROM users WHERE email='test@example.com'"

  # Query from file
  %(prog)s --query-file slow_query.sql
        """
    )

    # Database connection (optional - falls back to DB_CONNECTION env var)
    parser.add_argument(
        '--db-connection',
        help='PostgreSQL connection string (default: $DB_CONNECTION env var)'
    )

    # Query input (optional - defaults to chat mode)
    query_group = parser.add_mutually_exclusive_group()
    query_group.add_argument('--query', help='SQL query to optimize (single query mode)')
    query_group.add_argument('--query-file', help='File containing SQL query (single query mode)')

    # Optimization parameters
    parser.add_argument('--max-cost', type=float, default=500.0,
                       help='Maximum acceptable query cost (default: 500.0)')
    parser.add_argument('--max-time-ms', type=int, default=50,
                       help='Maximum acceptable execution time in ms (default: 50)')
    parser.add_argument('--max-iterations', type=int, default=10,
                       help='Maximum optimization iterations (default: 10)')

    # Agent configuration
    parser.add_argument('--no-extended-thinking', action='store_true',
                       help='Disable Claude extended thinking mode')
    parser.add_argument('--thinking-budget', type=int, default=4000,
                       help='Token budget for extended thinking (default: 4000)')
    parser.add_argument('--statement-timeout', type=int, default=60000,
                       help='PostgreSQL statement timeout in ms (default: 60000)')

    # Correctness validation options
    parser.add_argument('--validate-only', action='store_true',
                       help='Validate correctness only (skip performance optimization)')
    parser.add_argument('--no-validation', action='store_true',
                       help='Skip correctness validation (only optimize performance)')

    args = parser.parse_args()

    # Check for API key
    if not os.environ.get('ANTHROPIC_API_KEY'):
        display.error("ANTHROPIC_API_KEY environment variable not set")
        print("Get your key from: https://console.anthropic.com/")
        sys.exit(1)

    # Get database connection (command line arg or environment variable)
    db_connection = args.db_connection or os.environ.get('DB_CONNECTION')
    if not db_connection:
        display.error("Database connection not specified")
        print("Either set DB_CONNECTION environment variable or use --db-connection argument")
        sys.exit(1)

    # Initialize agent
    agent = SQLOptimizationAgent(
        max_iterations=args.max_iterations,
        use_thinking=not args.no_extended_thinking,
        thinking_budget=args.thinking_budget,
        statement_timeout_ms=args.statement_timeout,
    )

    # Run based on mode (chat mode by default)
    if args.query or args.query_file:
        # Single query mode
        if args.query_file:
            query_path = Path(args.query_file)
            if not query_path.exists():
                display.error(f"File not found: {args.query_file}")
                sys.exit(1)
            query = query_path.read_text().strip()
        else:
            query = args.query

        await optimize_single_query(agent, query, db_connection, args)
    else:
        # Chat mode (default)
        await chat_mode(agent, db_connection, args)


if __name__ == '__main__':
    asyncio.run(main())
