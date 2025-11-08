#!/usr/bin/env python3
"""
Interactive SQL Optimization CLI

Demonstrates autonomous query optimization with full reasoning traces.
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

# Ensure src is on path
ROOT = os.path.abspath(os.path.dirname(__file__))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from agentic_dba.agent import SQLOptimizationAgent, BIRDCriticTask
from agentic_dba.actions import ActionType


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

        print_header("SQL OPTIMIZATION SESSION")

        print(f"{Colors.BOLD}Query:{Colors.END}")
        print(f"{Colors.CYAN}{sql_query}{Colors.END}\n")

        print(f"{Colors.BOLD}Database:{Colors.END} {db_connection}")
        if constraints:
            print(f"{Colors.BOLD}Constraints:{Colors.END}")
            for key, value in constraints.items():
                print(f"  • {key}: {value}")

        print_section("Starting Autonomous Optimization")

        # Monkey-patch the agent's methods to intercept calls
        original_analyze = self.agent._analyze_query
        original_plan = self.agent._plan_action
        original_execute = self.agent._execute_ddl

        iteration_data = []

        async def traced_analyze(query, db_conn, const, task=None):
            """Traced version of _analyze_query."""
            self.iteration_count += 1

            print_section(f"Iteration {self.iteration_count}: Analyzing Query")
            print(f"Current Query: {Colors.CYAN}{query[:100]}{'...' if len(query) > 100 else ''}{Colors.END}")

            result = await original_analyze(query, db_conn, const, task)

            # Display analysis results
            feedback = result.get("feedback", {})
            tech = result.get("technical_analysis", {})

            print(f"\n{Colors.BOLD}Performance Analysis:{Colors.END}")
            print(f"  Status: {self._format_status(feedback.get('status', 'unknown'))}")
            print(f"  Total Cost: {Colors.YELLOW}{format_cost(tech.get('total_cost', 0))}{Colors.END}")

            if tech.get('execution_time_ms'):
                print(f"  Execution Time: {Colors.YELLOW}{format_time(tech.get('execution_time_ms'))}{Colors.END}")

            print(f"\n{Colors.BOLD}Feedback:{Colors.END}")
            print(f"  Priority: {self._format_priority(feedback.get('priority', 'UNKNOWN'))}")
            print(f"  Reason: {feedback.get('reason', 'N/A')}")

            bottlenecks = tech.get('bottlenecks', [])
            if bottlenecks:
                print(f"\n{Colors.BOLD}Bottlenecks Detected:{Colors.END}")
                for i, bn in enumerate(bottlenecks[:3], 1):
                    severity = bn.get('severity', 'UNKNOWN')
                    node_type = bn.get('node_type', 'Unknown')
                    reason = bn.get('reason', 'N/A')
                    print(f"  {i}. [{self._format_severity(severity)}] {node_type}")
                    print(f"     {reason}")

            # Store iteration data
            iteration_data.append({
                'iteration': self.iteration_count,
                'feedback': feedback,
                'technical': tech,
                'query': query
            })

            return result

        async def traced_plan(task, current_query, feedback, iteration, db_connection_string=None, executed_ddls=None):
            """Traced version of _plan_action."""
            print_section("Planning Next Action")

            result = await original_plan(task, current_query, feedback, iteration, db_connection_string, executed_ddls)

            print(f"\n{Colors.BOLD}Agent Decision:{Colors.END}")
            print(f"  Action Type: {self._format_action_type(result.type)}")
            print(f"  Confidence: {Colors.YELLOW}{result.confidence:.0%}{Colors.END}")

            print(f"\n{Colors.BOLD}Reasoning:{Colors.END}")
            # Wrap reasoning text
            reasoning_lines = result.reasoning.split('\n')
            for line in reasoning_lines:
                if line.strip():
                    # Wrap long lines
                    words = line.split()
                    current_line = "  "
                    for word in words:
                        if len(current_line) + len(word) + 1 > 78:
                            print(current_line)
                            current_line = "  " + word + " "
                        else:
                            current_line += word + " "
                    if current_line.strip():
                        print(current_line)

            if result.ddl:
                print(f"\n{Colors.BOLD}DDL Statement:{Colors.END}")
                print(f"  {Colors.CYAN}{result.ddl}{Colors.END}")

            if result.new_query:
                print(f"\n{Colors.BOLD}Rewritten Query:{Colors.END}")
                print(f"  {Colors.CYAN}{result.new_query[:200]}{'...' if len(result.new_query) > 200 else ''}{Colors.END}")

            return result

        async def traced_execute(ddl, db_conn):
            """Traced version of _execute_ddl."""
            print(f"\n{Colors.BOLD}Executing:{Colors.END} {Colors.GREEN}{ddl[:80]}{'...' if len(ddl) > 80 else ''}{Colors.END}")

            try:
                await original_execute(ddl, db_conn)
                print_success("Execution successful")
            except Exception as e:
                print_error(f"Execution failed: {e}")
                raise

        # Apply patches
        self.agent._analyze_query = traced_analyze
        self.agent._plan_action = traced_plan
        self.agent._execute_ddl = traced_execute

        try:
            # Run optimization
            solution = await self.agent.solve_task(task, db_connection, constraints)

            # Display final results
            print_header("OPTIMIZATION COMPLETE")

            if solution.success:
                print_success(f"Optimization successful: {solution.reason}")
            else:
                print_error(f"Optimization failed: {solution.reason}")

            print(f"\n{Colors.BOLD}Summary:{Colors.END}")
            print(f"  Total Iterations: {Colors.YELLOW}{solution.total_iterations()}{Colors.END}")
            print(f"  Actions Taken: {Colors.YELLOW}{len([a for a in solution.actions if not a.is_terminal()])}{Colors.END}")

            print(f"\n{Colors.BOLD}Final Query:{Colors.END}")
            print(f"{Colors.CYAN}{solution.final_query}{Colors.END}")

            print_section("Action History")
            for i, action in enumerate(solution.actions, 1):
                icon = "✓" if action.type == ActionType.DONE else "→" if action.type != ActionType.FAILED else "✗"
                print(f"{icon} Step {i}: {self._format_action_type(action.type)}")
                print(f"  {action.reasoning[:150]}{'...' if len(action.reasoning) > 150 else ''}")
                if action.ddl:
                    print(f"  DDL: {action.ddl[:100]}{'...' if len(action.ddl) > 100 else ''}")

            if solution.metrics:
                print_section("Performance Metrics")
                for key, value in solution.metrics.items():
                    print(f"  {key}: {Colors.YELLOW}{value}{Colors.END}")

            return solution

        finally:
            # Restore original methods
            self.agent._analyze_query = original_analyze
            self.agent._plan_action = original_plan
            self.agent._execute_ddl = original_execute

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

    print_header("INTERACTIVE SQL OPTIMIZATION CLI")
    print_info("This tool demonstrates autonomous SQL query optimization.")
    print_info("The agent will analyze your queries and iteratively optimize them.\n")

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
