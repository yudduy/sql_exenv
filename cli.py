#!/usr/bin/env python3
"""
Intent SQL Optimization CLI

Autonomous query optimization with full reasoning traces.
Users can input SQL queries and watch the agent optimize them in real-time.

Usage:
    python optimize_cli.py [--db-connection <url>] [--max-iterations <n>]

Examples:
    # Interactive mode with database connection
    python optimize_cli.py --db-connection postgresql://localhost/testdb

    # With custom iteration limit
    python optimize_cli.py --max-iterations 5
"""

import asyncio
import argparse
import os
import sys
import json
from datetime import datetime
from typing import Optional
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Ensure src is on path
ROOT = os.path.abspath(os.path.dirname(__file__))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from agent import SQLOptimizationAgent, BIRDCriticTask
from actions import ActionType


# ANSI color codes for terminal output
class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'
    SEPARATOR = '\033[90m'  # Gray for separators
    END = '\033[0m'


def print_header(text: str):
    """Print a styled header."""
    print(f"\n{Colors.BOLD}{Colors.HEADER}{'=' * 80}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.HEADER}{text.center(80)}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.HEADER}{'=' * 80}{Colors.END}\n")


def print_section(title: str):
    """Print a section divider."""
    print(f"\n{Colors.CYAN}{Colors.BOLD}▶ {title}{Colors.END}")
    print(f"{Colors.CYAN}{'─' * 78}{Colors.END}")


def print_success(text: str):
    """Print success message."""
    print(f"{Colors.GREEN}✓ {text}{Colors.END}")


def print_error(text: str):
    """Print error message."""
    print(f"{Colors.RED}✗ {text}{Colors.END}")


def print_warning(text: str):
    """Print warning message."""
    print(f"{Colors.YELLOW}⚠ {text}{Colors.END}")


def print_info(text: str):
    """Print info message."""
    print(f"{Colors.BLUE}ℹ {text}{Colors.END}")


def format_cost(cost: float) -> str:
    """Format cost value with thousands separator."""
    return f"{cost:,.2f}"


def format_time(ms: float) -> str:
    """Format time in milliseconds."""
    if ms < 1000:
        return f"{ms:.2f}ms"
    else:
        return f"{ms/1000:.2f}s"


class OptimizationTracer:
    """
    Enhanced agent that captures and displays optimization traces.

    Extends the base SQLOptimizationAgent to intercept and display
    each step of the optimization process.
    """

    def __init__(self, agent: SQLOptimizationAgent):
        self.agent = agent
        self.iteration_count = 0

    async def optimize_with_trace(
        self,
        sql_query: str,
        db_connection: str,
        constraints: Optional[dict] = None
    ):
        """
        Run optimization with detailed trace output.

        Args:
            sql_query: SQL query to optimize
            db_connection: PostgreSQL connection string
            constraints: Performance constraints
        """
        # Create task from query
        task = BIRDCriticTask(
            task_id=f"cli_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            db_id="user_db",
            buggy_sql=sql_query,
            user_query="User-provided query for optimization",
            efficiency=True,
        )

        print(f"\n{Colors.SEPARATOR}{'=' * 78}{Colors.END}")
        print(f"\n{Colors.BOLD}Your Query:{Colors.END}")
        print(f"{Colors.CYAN}{sql_query}{Colors.END}")

        # Preflight check: verify tables exist
        missing_tables = self._check_tables_exist(sql_query, db_connection)
        if missing_tables:
            print(f"\n{Colors.RED}Error: The following tables do not exist in your database:{Colors.END}")
            for table in missing_tables:
                print(f"  • {table}")
            
            # Show available tables
            available_tables = self._get_available_tables(db_connection)
            if available_tables:
                print(f"\n{Colors.YELLOW}Available tables in your database:{Colors.END}")
                for table in sorted(available_tables):
                    print(f"  • {table}")
            
            print(f"\n{Colors.YELLOW}Tip: Check test_queries.sql for working query examples{Colors.END}")
            return None

        # Monkey-patch the agent's methods to intercept calls
        original_analyze = self.agent._analyze_query
        original_plan = self.agent._plan_action
        original_execute = self.agent._execute_ddl

        iteration_data = []

        async def traced_analyze(query, db_connection_string, constraints, task=None):
            """Traced version of _analyze_query with conversational output."""
            print(f"\n{Colors.CYAN}Analyzing query performance...{Colors.END}")

            result = await original_analyze(query, db_connection_string, constraints, task)

            # Analyzer Output
            print(f"\n{Colors.BOLD}Analyzer Output:{Colors.END}")
            tech = result.get("technical_analysis", {})
            
            print(f"{Colors.BOLD}Performance Check:{Colors.END}")
            fb = result.get("feedback", {})
            status = fb.get("status", "unknown").upper()
            status_icon = "PASS" if status == "PASS" else "FAIL"
            print(f"  Status: {status_icon}")
            
            cost = tech.get('total_cost', 'N/A')
            if isinstance(cost, (int, float)):
                print(f"  Total Cost: {cost:,.2f}")
            else:
                print(f"  Total Cost: {cost}")
                
            if result.get("execution_time"):
                print(f"  Execution Time: {result['execution_time']:.2f}ms")

            # Semanticizer Output
            print(f"\n{Colors.BOLD}Semanticizer Output:{Colors.END}")
            print(f"  Feedback Priority: {fb.get('priority', 'N/A')}")
            reason = fb.get('reason', 'N/A')
            
            # Parse and improve error messages
            if "Error code: 401" in reason and "authentication_error" in reason:
                print(f"  Reason: {Colors.RED}Authentication Error: Invalid API key{Colors.END}")
                print(f"           Please check your ANTHROPIC_API_KEY environment variable")
                print(f"           Make sure the API key is valid and has credits available")
            elif "Error code:" in reason:
                import re
                error_match = re.search(r"Error code: (\d+) - (.+)", reason)
                if error_match:
                    error_code = error_match.group(1)
                    error_msg = error_match.group(2)
                    if error_code == "401":
                        print(f"  Reason: {Colors.RED}Authentication Error: Invalid API key{Colors.END}")
                        print(f"           Please check your ANTHROPIC_API_KEY environment variable")
                    elif error_code == "429":
                        print(f"  Reason: {Colors.YELLOW}Rate Limit Error: Too many requests{Colors.END}")
                        print(f"           Please wait a moment and try again")
                    elif error_code == "500":
                        print(f"  Reason: {Colors.YELLOW}Service Error: Anthropic API issue{Colors.END}")
                        print(f"           Please try again in a few minutes")
                    else:
                        print(f"  Reason: API Error ({error_code}): {error_msg}")
                else:
                    print(f"  Reason: {reason}")
            else:
                print(f"  Reason: {reason}")

            # Show bottlenecks if any (only those with real descriptions)
            bottlenecks = tech.get("bottlenecks", [])
            real_bottlenecks = [bn for bn in bottlenecks if bn.get("description", "N/A") != "N/A"]
            if real_bottlenecks:
                print(f"\n  Bottlenecks Detected:")
                for i, bn in enumerate(real_bottlenecks[:3], 1):
                    severity = bn.get("severity", "unknown").upper()
                    node_type = bn.get("node_type", "Unknown")
                    desc = bn.get("description")
                    print(f"    {i}. [{severity}] {node_type}")
                    print(f"       {desc}")

            return result

        async def traced_plan(task, current_query, feedback, iteration, db_connection_string=None, executed_ddls=None, iteration_history=None, constraints=None, stagnation_warning=None):
            """Traced version of _plan_action with Claude's commentary."""
            result = await original_plan(task, current_query, feedback, iteration, db_connection_string, executed_ddls, iteration_history, constraints, stagnation_warning)

            # Claude's reasoning (conversational)
            print(f"\n{Colors.GREEN}Claude:{Colors.END} ", end="")
            import textwrap
            import re
            
            reasoning = result.reasoning
            
            # Parse API key errors in Claude's reasoning
            if "Error code: 401" in reasoning and "authentication_error" in reasoning:
                reasoning = f"{Colors.RED}Authentication Error: Invalid API key{Colors.END}\n" \
                           f"Please check your ANTHROPIC_API_KEY environment variable.\n" \
                           f"Make sure the API key is valid and has credits available."
            elif "Error code:" in reasoning:
                error_match = re.search(r"Error code: (\d+) - (.+)", reasoning)
                if error_match:
                    error_code = error_match.group(1)
                    error_msg = error_match.group(2)
                    if error_code == "401":
                        reasoning = f"{Colors.RED}Authentication Error: Invalid API key{Colors.END}\n" \
                                   f"Please check your ANTHROPIC_API_KEY environment variable."
                    elif error_code == "429":
                        reasoning = f"{Colors.YELLOW}Rate Limit Error: Too many requests{Colors.END}\n" \
                                   f"Please wait a moment and try again."
                    elif error_code == "500":
                        reasoning = f"{Colors.YELLOW}Service Error: Anthropic API issue{Colors.END}\n" \
                                   f"Please try again in a few minutes."
                    else:
                        reasoning = f"API Error ({error_code}): {error_msg}"
            
            wrapped = textwrap.fill(reasoning, width=74, subsequent_indent="          ")
            print(wrapped)

            # Show what Claude is proposing
            if result.type == ActionType.CREATE_INDEX and result.ddl:
                print(f"\n{Colors.BLUE}Proposed action:{Colors.END} {result.ddl}")
            elif result.type == ActionType.RUN_ANALYZE and result.ddl:
                print(f"\n{Colors.BLUE}Proposed action:{Colors.END} {result.ddl}")
            elif result.type == ActionType.REWRITE_QUERY and result.new_query:
                print(f"\n{Colors.BLUE}Proposed action:{Colors.END} Rewrite query")

            return result

        async def traced_execute(ddl, db_connection_string):
            """Traced version of _execute_ddL."""
            try:
                await original_execute(ddl, db_connection_string)
                print(f"{Colors.GREEN}Done{Colors.END}")
            except Exception as e:
                print(f"{Colors.RED}Failed: {e}{Colors.END}")
                raise

        # Apply patches
        self.agent._analyze_query = traced_analyze
        self.agent._plan_action = traced_plan
        self.agent._execute_ddl = traced_execute

        try:
            # Run optimization
            solution = await self.agent.solve_task(task, db_connection, constraints)

            # Display final results (conversational style)
            print(f"\n{Colors.SEPARATOR}{'=' * 78}{Colors.END}\n")

            if solution.success:
                print(f"{Colors.GREEN}Claude: Great! The query is now optimized and working well.{Colors.END}\n")
                print(f"{Colors.BOLD}Optimization Complete{Colors.END}")
                if solution.metrics:
                    print(f"\n{Colors.BOLD}Final Performance:{Colors.END}")
                    print(f"  • Cost: {solution.metrics.get('final_cost', 'N/A')}")
                    print(f"  • Execution Time: {solution.metrics.get('execution_time', 'N/A')}ms")
            else:
                print(f"{Colors.YELLOW}Claude: {solution.reason}{Colors.END}\n")
                print(f"{Colors.BOLD}Optimization Status{Colors.END}")

            print(f"\n{Colors.BOLD}Final SQL Query:{Colors.END}")
            print(f"{Colors.CYAN}{solution.final_query}{Colors.END}")

            return solution

        finally:
            # Restore original methods
            self.agent._analyze_query = original_analyze
            self.agent._plan_action = original_plan
            self.agent._execute_ddl = original_execute

    def _check_tables_exist(self, query: str, db_connection: str) -> list:
        """
        Extract table names from query and check if they exist in the database.
        Returns list of missing table names.
        """
        import re
        import psycopg2
        
        # Extract table names from FROM and JOIN clauses
        pattern = r'(?:FROM|JOIN)\s+(\w+)(?:\s+(?:AS\s+)?(\w+))?'
        matches = re.findall(pattern, query, re.IGNORECASE)
        table_names = set()
        for match in matches:
            if match[0]:
                table_names.add(match[0].lower())
        
        if not table_names:
            return []
        
        # Check which tables exist
        missing_tables = []
        try:
            with psycopg2.connect(db_connection) as conn:
                with conn.cursor() as cursor:
                    for table in table_names:
                        cursor.execute("""
                            SELECT EXISTS (
                                SELECT 1 FROM information_schema.tables 
                                WHERE table_schema = 'public' AND table_name = %s
                            )
                        """, (table,))
                        exists, = cursor.fetchone()
                        if not exists:
                            missing_tables.append(table)
        except Exception as e:
            # If we can't check, just return empty (let the agent handle it)
            return []
        
        return missing_tables
    
    def _get_available_tables(self, db_connection: str) -> list:
        """Get list of available tables in the database."""
        import psycopg2
        
        try:
            with psycopg2.connect(db_connection) as conn:
                with conn.cursor() as cursor:
                    cursor.execute("""
                        SELECT table_name 
                        FROM information_schema.tables 
                        WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
                        ORDER BY table_name
                    """)
                    return [row[0] for row in cursor.fetchall()]
        except Exception:
            return []

    def _format_status(self, status: str) -> str:
        """Format status with color."""
        status_upper = status.upper()
        if status_upper == "PASS":
            return f"{Colors.GREEN}{status_upper}{Colors.END}"
        elif status_upper == "FAIL":
            return f"{Colors.RED}{status_upper}{Colors.END}"
        else:
            return f"{Colors.YELLOW}{status_upper}{Colors.END}"

    def _format_priority(self, priority: str) -> str:
        """Format priority with color."""
        if priority == "HIGH" or priority == "CRITICAL":
            return f"{Colors.RED}{priority}{Colors.END}"
        elif priority == "MEDIUM":
            return f"{Colors.YELLOW}{priority}{Colors.END}"
        else:
            return f"{Colors.GREEN}{priority}{Colors.END}"

    def _format_severity(self, severity: str) -> str:
        """Format severity with color."""
        if severity == "HIGH":
            return f"{Colors.RED}{severity}{Colors.END}"
        elif severity == "MEDIUM":
            return f"{Colors.YELLOW}{severity}{Colors.END}"
        else:
            return f"{Colors.GREEN}{severity}{Colors.END}"

    def _format_action_type(self, action_type: ActionType) -> str:
        """Format action type with color."""
        if action_type == ActionType.DONE:
            return f"{Colors.GREEN}{action_type.value}{Colors.END}"
        elif action_type == ActionType.FAILED:
            return f"{Colors.RED}{action_type.value}{Colors.END}"
        elif action_type == ActionType.CREATE_INDEX:
            return f"{Colors.CYAN}{action_type.value}{Colors.END}"
        elif action_type == ActionType.REWRITE_QUERY:
            return f"{Colors.BLUE}{action_type.value}{Colors.END}"
        else:
            return f"{Colors.YELLOW}{action_type.value}{Colors.END}"


async def interactive_session(db_connection: str, max_iterations: int, constraints: dict):
    """
    Run interactive optimization session.

    Args:
        db_connection: PostgreSQL connection string
        max_iterations: Maximum optimization iterations
        constraints: Performance constraints
    """
    # Initialize agent
    agent = SQLOptimizationAgent(
        max_iterations=max_iterations,
        timeout_per_task_seconds=120,
        use_extended_thinking=True,
        extended_thinking_budget=8000,
    )

    tracer = OptimizationTracer(agent)

    print(f"{Colors.BOLD}{'SQL INTENT OPTIMIZATION CLI'.center(80)}{Colors.END}")
    print(f"{Colors.SEPARATOR}{'=' * 80}{Colors.END}")

    print(f"{Colors.BOLD}Configuration:{Colors.END}")
    print(f"  Database: {db_connection}")
    print(f"  Max Iterations: {max_iterations}")
    print(f"  Max Cost: {constraints.get('max_cost', 'unlimited')}")
    print(f"  Max Time: {constraints.get('max_time_ms', 'unlimited')}ms")

    print(f"\n{Colors.BOLD}Instructions:{Colors.END}")
    print("  • Enter your SQL query (multi-line supported)")
    print("  • Type 'GO' on a new line to execute")
    print("  • Type 'EXIT' or 'QUIT' to quit")
    print("  • Press Ctrl+C to interrupt\n")

    query_count = 0

    while True:
        try:
            # Prompt for SQL query
            print(f"\n{Colors.BOLD}{Colors.BLUE}Enter SQL query (type 'GO' to execute, 'EXIT' to quit):{Colors.END}")

            lines = []
            while True:
                line = input()

                if line.strip().upper() == 'EXIT' or line.strip().upper() == 'QUIT':
                    print_info("Goodbye!")
                    return

                if line.strip().upper() == 'GO':
                    break

                lines.append(line)

            sql_query = '\n'.join(lines).strip()

            if not sql_query:
                print_warning("Empty query. Please enter a valid SQL statement.")
                continue

            query_count += 1

            # Run optimization with trace
            await tracer.optimize_with_trace(sql_query, db_connection, constraints)

            # Ask if user wants to continue
            print(f"\n{Colors.BOLD}Optimize another query? (yes/no):{Colors.END} ", end='')
            response = input().strip().lower()

            if response not in ['yes', 'y']:
                print_info(f"Processed {query_count} {'query' if query_count == 1 else 'queries'}. Goodbye!")
                break

        except KeyboardInterrupt:
            print(f"\n\n{Colors.YELLOW}Session interrupted.{Colors.END}")
            print_info(f"Processed {query_count} {'query' if query_count == 1 else 'queries'}.")
            break
        except Exception as e:
            print_error(f"Error: {e}")
            print_warning("You can try another query or type EXIT to quit.")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Interactive SQL Optimization CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --db-connection postgresql://localhost/testdb
  %(prog)s --db-connection postgresql://user:pass@host/db --max-iterations 5
  %(prog)s --max-cost 10000 --max-time-ms 30000

Environment Variables:
  ANTHROPIC_API_KEY    Anthropic API key (required)
  DB_CONNECTION        Default database connection string
        """
    )

    parser.add_argument(
        '--db-connection',
        type=str,
        default=os.environ.get('DB_CONNECTION', 'postgresql://localhost/testdb'),
        help='PostgreSQL connection string (default: from DB_CONNECTION env var or postgresql://localhost/testdb)'
    )

    parser.add_argument(
        '--max-iterations',
        type=int,
        default=5,
        help='Maximum optimization iterations (default: 5)'
    )

    parser.add_argument(
        '--max-cost',
        type=float,
        default=10000.0,
        help='Maximum acceptable query cost (default: 10000.0)'
    )

    parser.add_argument(
        '--max-time-ms',
        type=int,
        default=30000,
        help='Maximum execution time in milliseconds (default: 30000)'
    )

    parser.add_argument(
        '--analyze-cost-threshold',
        type=float,
        default=5_000_000.0,
        help='Only run EXPLAIN ANALYZE if estimated cost below this (default: 5000000.0)'
    )

    args = parser.parse_args()

    # Check for API key
    if not os.environ.get('ANTHROPIC_API_KEY'):
        print_error("ANTHROPIC_API_KEY environment variable not set!")
        print_info("Please export your API key:")
        print("  export ANTHROPIC_API_KEY='your-key-here'")
        sys.exit(1)

    # Build constraints
    constraints = {
        'max_cost': args.max_cost,
        'max_time_ms': args.max_time_ms,
        'analyze_cost_threshold': args.analyze_cost_threshold,
    }

    # Run interactive session
    try:
        asyncio.run(interactive_session(args.db_connection, args.max_iterations, constraints))
    except Exception as e:
        print_error(f"Fatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
