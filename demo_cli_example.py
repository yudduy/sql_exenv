#!/usr/bin/env python3
"""
Quick Demo Script for Interactive CLI

This script demonstrates the CLI with a sample query to show users
what the output looks like.

Usage:
    # Run with a real database
    export ANTHROPIC_API_KEY='your-key'
    export DB_CONNECTION='postgresql://localhost/testdb'
    python demo_cli_example.py

    # Or use mock mode (no database required)
    python demo_cli_example.py --mock
"""

import sys
import os

# Add src to path
ROOT = os.path.abspath(os.path.dirname(__file__))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

def print_demo_usage():
    """Print demonstration of CLI capabilities."""

    print("""
================================================================================
           INTERACTIVE SQL OPTIMIZATION CLI - DEMO
================================================================================

This tool provides an interactive interface for SQL query optimization.

EXAMPLE SESSION
---------------

$ python optimize_cli.py --db-connection postgresql://localhost/testdb

Configuration:
  Database: postgresql://localhost/testdb
  Max Iterations: 5
  Max Cost: 10000.0
  Max Time: 30000ms

Enter SQL query (type 'GO' to execute, 'EXIT' to quit):
> SELECT * FROM users WHERE email = 'alice@example.com'
> GO

================================================================================
                        SQL OPTIMIZATION SESSION
================================================================================

Query: SELECT * FROM users WHERE email = 'alice@example.com'
Database: postgresql://localhost/testdb

▶ Starting Autonomous Optimization
────────────────────────────────────────────────────────────────────────────

▶ Iteration 1: Analyzing Query
────────────────────────────────────────────────────────────────────────────
Current Query: SELECT * FROM users WHERE email = 'alice@example.com'

Performance Analysis:
  Status: FAIL
  Total Cost: 55,072.50
  Execution Time: 245.12ms

Feedback:
  Priority: HIGH
  Reason: Sequential scan on large table with 100,000 rows

Bottlenecks Detected:
  1. [HIGH] Seq Scan
     Sequential scan on 'users' with 100,000 rows

▶ Planning Next Action
────────────────────────────────────────────────────────────────────────────

Agent Decision:
  Action Type: CREATE_INDEX
  Confidence: 95%

Reasoning:
  The query performs a sequential scan on the users table. Creating an index
  on the email column will enable index scan and significantly reduce cost.

DDL Statement:
  CREATE INDEX idx_users_email ON users(email);

Executing: CREATE INDEX idx_users_email ON users(email);
✓ Execution successful

▶ Iteration 2: Analyzing Query
────────────────────────────────────────────────────────────────────────────
Current Query: SELECT * FROM users WHERE email = 'alice@example.com'

Performance Analysis:
  Status: PASS
  Total Cost: 142.50
  Execution Time: 2.3ms

Feedback:
  Priority: LOW
  Reason: Query now uses Index Scan efficiently

▶ Planning Next Action
────────────────────────────────────────────────────────────────────────────

Agent Decision:
  Action Type: DONE
  Confidence: 100%

Reasoning:
  Query meets all performance constraints. Cost reduced from 55,072 to 142.
  Using Index Scan as expected.

================================================================================
                         OPTIMIZATION COMPLETE
================================================================================

✓ Optimization successful: Query optimized successfully

Summary:
  Total Iterations: 2
  Actions Taken: 1

Final Query:
SELECT * FROM users WHERE email = 'alice@example.com'

▶ Action History
────────────────────────────────────────────────────────────────────────────
→ Step 1: CREATE_INDEX
  Sequential scan detected on large table. Creating index to improve performance.
  DDL: CREATE INDEX idx_users_email ON users(email);

✓ Step 2: DONE
  Query now meets performance constraints.

▶ Performance Metrics
────────────────────────────────────────────────────────────────────────────
  total_cost: 142.5
  execution_time_ms: 2.3
  bottlenecks_found: 0

Optimize another query? (yes/no):

================================================================================

KEY FEATURES DEMONSTRATED
-------------------------

1. ✓ Interactive query input
2. ✓ Real-time optimization tracing
3. ✓ Detailed feedback at each iteration
4. ✓ Agent reasoning and decision-making
5. ✓ DDL execution and validation
6. ✓ Performance metrics comparison
7. ✓ Complete action history

GETTING STARTED
---------------

1. Set up environment:
   export ANTHROPIC_API_KEY='your-api-key'
   export DB_CONNECTION='postgresql://localhost/yourdb'

2. Run the CLI:
   python optimize_cli.py

3. Enter your queries and watch the agent optimize them!

For more details, see:
  - OPTIMIZE_CLI_USAGE.txt (comprehensive guide)
  - README.md (project overview)
  - CLAUDE.md (architecture details)

""")

def main():
    """Run the demo."""
    import argparse

    parser = argparse.ArgumentParser(description='CLI Demo')
    parser.add_argument('--mock', action='store_true',
                       help='Show demo output (no actual execution)')

    args = parser.parse_args()

    if args.mock:
        print_demo_usage()
    else:
        # Check if requirements are met
        if not os.environ.get('ANTHROPIC_API_KEY'):
            print("❌ Error: ANTHROPIC_API_KEY not set")
            print("\nTo run this demo, you need:")
            print("  1. Anthropic API key: export ANTHROPIC_API_KEY='your-key'")
            print("  2. Database connection: export DB_CONNECTION='postgresql://...'")
            print("\nOr run in mock mode to see example output:")
            print("  python demo_cli_example.py --mock")
            sys.exit(1)

        if not os.environ.get('DB_CONNECTION'):
            print("❌ Error: DB_CONNECTION not set")
            print("\nTo run this demo, you need:")
            print("  export DB_CONNECTION='postgresql://localhost/yourdb'")
            print("\nOr run in mock mode to see example output:")
            print("  python demo_cli_example.py --mock")
            sys.exit(1)

        print("✓ Environment configured correctly!")
        print("\nTo start the interactive CLI, run:")
        print("  python optimize_cli.py")
        print("\nOr to see example output without running:")
        print("  python demo_cli_example.py --mock")

if __name__ == '__main__':
    main()
