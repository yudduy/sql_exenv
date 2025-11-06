#!/usr/bin/env python3
"""
BIRD Setup Verification Script

Quick test to verify that the BIRD dataset and PostgreSQL setup is correct.
Run this after setup_bird_databases.sh to ensure everything is working.

Usage:
    python test_bird_setup.py [--database bird_dev] [--user bird_user]
"""

import json
import asyncio
import argparse
import sys
from pathlib import Path

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
except ImportError:
    print("Error: psycopg2 not installed. Run: pip install psycopg2-binary")
    sys.exit(1)

try:
    from mcp_server import QueryOptimizationTool
except ImportError:
    print("Error: Could not import mcp_server. Ensure you're in the correct directory.")
    sys.exit(1)


class SetupTester:
    """Tests BIRD dataset and database setup."""

    def __init__(self, db_name: str, user: str = None):
        self.db_name = db_name
        self.user = user
        self.conn_string = self._build_conn_string()
        self.passed = 0
        self.failed = 0

    def _build_conn_string(self) -> str:
        """Build PostgreSQL connection string."""
        if self.user:
            return f"postgresql://{self.user}@localhost/{self.db_name}"
        return f"postgresql:///{ self.db_name}"

    def print_header(self, text: str):
        """Print section header."""
        print()
        print("=" * 60)
        print(text)
        print("=" * 60)

    def print_test(self, name: str, passed: bool, details: str = ""):
        """Print test result."""
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status} - {name}")
        if details:
            print(f"      {details}")

        if passed:
            self.passed += 1
        else:
            self.failed += 1

    def test_files_exist(self):
        """Test 1: Check if BIRD dataset files exist."""
        self.print_header("Test 1: Dataset Files")

        # Check JSON data
        json_path = Path("./mini_dev/minidev/MINIDEV/mini_dev_postgresql.json")
        json_exists = json_path.exists()
        self.print_test(
            "BIRD JSON data exists",
            json_exists,
            str(json_path) if json_exists else f"Missing: {json_path}"
        )

        # Check SQL dump
        sql_path = Path("./mini_dev/minidev/MINIDEV_postgresql/BIRD_dev.sql")
        sql_exists = sql_path.exists()
        self.print_test(
            "PostgreSQL dump exists",
            sql_exists,
            f"{sql_path.stat().st_size / 1024 / 1024:.1f} MB" if sql_exists else f"Missing: {sql_path}"
        )

        # Load and validate JSON
        if json_exists:
            try:
                with open(json_path) as f:
                    data = json.load(f)
                query_count = len(data)
                self.print_test(
                    "JSON data is valid",
                    query_count == 500,
                    f"{query_count} queries (expected 500)"
                )
            except Exception as e:
                self.print_test("JSON data is valid", False, str(e))

    def test_database_connection(self):
        """Test 2: Test database connection."""
        self.print_header("Test 2: Database Connection")

        try:
            conn = psycopg2.connect(self.conn_string)
            self.print_test("Database connection successful", True, self.conn_string)

            # Check database size
            with conn.cursor() as cur:
                cur.execute("SELECT pg_size_pretty(pg_database_size(%s))", (self.db_name,))
                size = cur.fetchone()[0]
                self.print_test("Database size query", True, size)

            conn.close()

        except Exception as e:
            self.print_test("Database connection successful", False, str(e))

    def test_tables_exist(self):
        """Test 3: Check if tables exist."""
        self.print_header("Test 3: Database Tables")

        try:
            conn = psycopg2.connect(self.conn_string)

            # Count tables
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT count(*) FROM information_schema.tables "
                    "WHERE table_schema='public'"
                )
                table_count = cur.fetchone()[0]
                self.print_test(
                    "Tables imported",
                    table_count > 100,
                    f"{table_count} tables (expected ~170)"
                )

            # Check specific tables from different databases
            sample_tables = ['customers', 'users', 'drivers', 'account']

            with conn.cursor() as cur:
                for table in sample_tables:
                    cur.execute(
                        "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
                        "WHERE table_schema='public' AND table_name=%s)",
                        (table,)
                    )
                    exists = cur.fetchone()[0]
                    self.print_test(f"Table '{table}' exists", exists)

            conn.close()

        except Exception as e:
            self.print_test("Table check", False, str(e))

    def test_sample_queries(self):
        """Test 4: Run sample BIRD queries."""
        self.print_header("Test 4: Sample Queries")

        try:
            conn = psycopg2.connect(self.conn_string)

            # Test 1: Simple aggregation
            with conn.cursor() as cur:
                try:
                    cur.execute(
                        "SELECT COUNT(*) FROM customers WHERE Currency = 'EUR'"
                    )
                    result = cur.fetchone()[0]
                    self.print_test(
                        "Simple aggregation query",
                        result >= 0,
                        f"Result: {result} EUR customers"
                    )
                except Exception as e:
                    self.print_test("Simple aggregation query", False, str(e))

            # Test 2: EXPLAIN works
            with conn.cursor() as cur:
                try:
                    cur.execute(
                        "EXPLAIN (FORMAT JSON, ANALYZE) "
                        "SELECT COUNT(*) FROM customers LIMIT 1"
                    )
                    explain = cur.fetchone()[0]
                    self.print_test(
                        "EXPLAIN ANALYZE works",
                        isinstance(explain, list),
                        f"Got {len(explain)} plan node(s)"
                    )
                except Exception as e:
                    self.print_test("EXPLAIN ANALYZE works", False, str(e))

            conn.close()

        except Exception as e:
            self.print_test("Sample queries", False, str(e))

    async def test_optimization_tool(self):
        """Test 5: Test the optimization tool."""
        self.print_header("Test 5: Optimization Tool")

        try:
            # Create tool with mock translator (no API key needed)
            tool = QueryOptimizationTool(use_mock_translator=True)
            self.print_test("QueryOptimizationTool initialized", True)

            # Load first BIRD query
            json_path = Path("./mini_dev/minidev/MINIDEV/mini_dev_postgresql.json")
            with open(json_path) as f:
                queries = json.load(f)

            first_query = queries[0]

            # Run optimization
            result = await tool.optimize_query(
                sql_query=first_query['SQL'],
                db_connection_string=self.conn_string,
                constraints={"max_cost": 1000.0}
            )

            self.print_test(
                "Optimization executed",
                result['success'],
                result.get('error', 'Success')
            )

            if result['success']:
                feedback = result.get('feedback', {})
                self.print_test(
                    "Feedback generated",
                    'status' in feedback,
                    f"Status: {feedback.get('status', 'N/A')}"
                )

                tech = result.get('technical_analysis', {})
                self.print_test(
                    "Technical analysis",
                    'total_cost' in tech,
                    f"Cost: {tech.get('total_cost', 'N/A')}"
                )

        except Exception as e:
            self.print_test("Optimization tool", False, str(e))

    def print_summary(self):
        """Print test summary."""
        self.print_header("Test Summary")

        total = self.passed + self.failed
        success_rate = (self.passed / total * 100) if total > 0 else 0

        print(f"Total tests: {total}")
        print(f"Passed: {self.passed} ✅")
        print(f"Failed: {self.failed} ❌")
        print(f"Success rate: {success_rate:.1f}%")
        print()

        if self.failed == 0:
            print("🎉 All tests passed! Your setup is ready.")
            print()
            print("Next steps:")
            print("  1. Run full validation:")
            print("     python bird_validator.py --database bird_dev --limit 10 --mock-translator")
            print()
            print("  2. Test with Claude API (set ANTHROPIC_API_KEY):")
            print("     python bird_validator.py --database bird_dev --limit 5")
            print()
        else:
            print("⚠️  Some tests failed. Check the errors above.")
            print()
            print("Common issues:")
            print("  - Database not created: Run ./setup_bird_databases.sh")
            print("  - Connection refused: Start PostgreSQL service")
            print("  - Missing files: Re-download BIRD dataset")
            print()

    async def run_all_tests(self):
        """Run all tests."""
        print()
        print("╔════════════════════════════════════════════════════════════╗")
        print("║        BIRD Dataset Setup Verification                     ║")
        print("╚════════════════════════════════════════════════════════════╝")

        self.test_files_exist()
        self.test_database_connection()
        self.test_tables_exist()
        self.test_sample_queries()
        await self.test_optimization_tool()
        self.print_summary()

        return self.failed == 0


async def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='Verify BIRD dataset and database setup'
    )
    parser.add_argument('--database', default='bird_dev',
                        help='PostgreSQL database name (default: bird_dev)')
    parser.add_argument('--user', default=None,
                        help='PostgreSQL user (default: current user)')

    args = parser.parse_args()

    tester = SetupTester(db_name=args.database, user=args.user)
    success = await tester.run_all_tests()

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    asyncio.run(main())
