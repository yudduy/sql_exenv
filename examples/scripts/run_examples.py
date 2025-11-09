#!/usr/bin/env python3
"""
Example SQL Optimization CLI Launcher

This script provides a convenient interface for running SQL optimization
examples with sql_exenv. It handles database setup, query execution,
and result visualization.

Usage:
    python run_examples.py --interactive
    python run_examples.py --file queries/sample_queries.sql
    python run_examples.py --query "SELECT * FROM customers WHERE country='USA'"
"""

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

# Add parent src to path
ROOT = Path(__file__).parent.parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agent import SQLOptimizationAgent
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

class ExampleRunner:
    """Convenient wrapper for running SQL optimization examples"""
    
    def __init__(self, db_connection: Optional[str] = None):
        self.db_connection = db_connection or os.getenv("DB_CONNECTION")
        if not self.db_connection:
            raise ValueError("Database connection required. Set DB_CONNECTION environment variable or use --db-connection")
        
        self.agent = SQLOptimizationAgent(
            db_connection=self.db_connection,
            use_real_translator=False,  # Default to mock for examples
            max_cost=1000.0,
            max_time_ms=60000,
            analyze_cost_threshold=10000000
        )
    
    async def run_query(self, query: str, use_real: bool = False, use_hypopg: bool = False) -> dict:
        """Run a single query optimization"""
        if use_real:
            self.agent.use_real_translator = True
        
        try:
            result = await self.agent.optimize_query(
                sql_query=query,
                use_hypopg=use_hypopg
            )
            return result
        except Exception as e:
            return {
                "error": str(e),
                "query": query,
                "timestamp": datetime.now().isoformat()
            }
    
    async def run_file(self, file_path: str, **kwargs) -> list:
        """Run all queries from a SQL file"""
        queries = self._parse_sql_file(file_path)
        results = []
        
        print(f"📊 Processing {len(queries)} queries from {file_path}")
        print("=" * 60)
        
        for i, query in enumerate(queries, 1):
            print(f"\n🔍 Query {i}/{len(queries)}")
            print("-" * 40)
            print(query[:200] + "..." if len(query) > 200 else query)
            print()
            
            result = await self.run_query(query, **kwargs)
            result["query_number"] = i
            results.append(result)
            
            self._print_result(result)
            print()
        
        return results
    
    async def interactive_mode(self):
        """Run interactive query optimization session"""
        print("🚀 SQL Optimization Interactive Mode")
        print("=" * 50)
        print("Enter SQL queries to optimize, or commands:")
        print("  :help    - Show this help")
        print("  :real    - Toggle real LLM translator")
        print("  :hypopg  - Toggle HypoPG proof")
        print("  :quit    - Exit")
        print()
        
        use_real = False
        use_hypopg = False
        
        while True:
            try:
                query = input("SQL> ").strip()
                
                if not query:
                    continue
                
                # Handle commands
                if query.startswith(":"):
                    if query == ":help":
                        self._show_interactive_help()
                    elif query == ":real":
                        use_real = not use_real
                        print(f"🤖 Real LLM translator: {'ON' if use_real else 'OFF'}")
                    elif query == ":hypopg":
                        use_hypopg = not use_hypopg
                        print(f"🔮 HypoPG proof: {'ON' if use_hypopg else 'OFF'}")
                    elif query == ":quit":
                        print("👋 Goodbye!")
                        break
                    else:
                        print("❓ Unknown command. Type :help for available commands.")
                    continue
                
                # Run query optimization
                print("⚡ Analyzing query...")
                result = await self.run_query(query, use_real=use_real, use_hypopg=use_hypopg)
                self._print_result(result)
                print()
                
            except KeyboardInterrupt:
                print("\n👋 Goodbye!")
                break
            except EOFError:
                print("\n👋 Goodbye!")
                break
            except Exception as e:
                print(f"❌ Error: {e}")
    
    def _parse_sql_file(self, file_path: str) -> list:
        """Parse SQL file and extract individual queries"""
        with open(file_path, 'r') as f:
            content = f.read()
        
        # Remove comments and split by semicolons
        lines = content.split('\n')
        cleaned_lines = []
        
        for line in lines:
            # Skip single-line comments
            if line.strip().startswith('--'):
                continue
            cleaned_lines.append(line)
        
        content = '\n'.join(cleaned_lines)
        queries = [q.strip() for q in content.split(';') if q.strip()]
        
        return queries
    
    def _print_result(self, result: dict):
        """Print optimization result in a readable format"""
        if "error" in result:
            print(f"❌ Error: {result['error']}")
            return
        
        feedback = result.get("feedback", {})
        plans = result.get("plans", {})
        
        # Status
        status = feedback.get("status", "UNKNOWN")
        status_emoji = {"PASS": "✅", "WARNING": "⚠️", "FAIL": "❌"}.get(status, "❓")
        print(f"{status_emoji} Status: {status}")
        
        # Reason
        reason = feedback.get("reason", "No reason provided")
        print(f"📝 Reason: {reason}")
        
        # Suggestion
        suggestion = feedback.get("suggestion", "No suggestion")
        print(f"💡 Suggestion: {suggestion}")
        
        # Cost information
        if "original_plan" in plans:
            original_cost = plans["original_plan"].get("total_cost", 0)
            print(f"💰 Original Cost: {original_cost:,.2f}")
        
        if "hypopg_plan" in plans:
            hypopg_cost = plans["hypopg_plan"].get("total_cost", 0)
            original_cost = plans["original_plan"].get("total_cost", 0)
            improvement = ((original_cost - hypopg_cost) / original_cost * 100) if original_cost > 0 else 0
            print(f"🔮 HypoPG Cost: {hypopg_cost:,.2f} ({improvement:+.1f}%)")
    
    def _show_interactive_help(self):
        """Show interactive mode help"""
        print("\n📚 Interactive Mode Help")
        print("=" * 30)
        print("Enter any SQL query to see optimization suggestions.")
        print("\nAvailable commands:")
        print("  :help    - Show this help message")
        print("  :real    - Toggle between mock and real LLM translator")
        print("  :hypopg  - Toggle HypoPG hypothetical index proof")
        print("  :quit    - Exit the interactive mode")
        print("\nExample queries to try:")
        print("  SELECT * FROM customers WHERE country = 'USA'")
        print("  SELECT c.name, COUNT(o.id) FROM customers c JOIN orders o ON c.id = o.customer_id GROUP BY c.name")
        print()

def main():
    parser = argparse.ArgumentParser(description="Run SQL optimization examples")
    parser.add_argument("--db-connection", help="PostgreSQL connection string")
    parser.add_argument("--file", help="SQL file with queries to optimize")
    parser.add_argument("--query", help="Single SQL query to optimize")
    parser.add_argument("--interactive", action="store_true", help="Run in interactive mode")
    parser.add_argument("--real", action="store_true", help="Use real LLM translator")
    parser.add_argument("--use-hypopg", action="store_true", help="Enable HypoPG proof")
    parser.add_argument("--output", help="Output file for results (JSON)")
    parser.add_argument("--max-cost", type=float, default=1000, help="Maximum acceptable cost")
    parser.add_argument("--max-time-ms", type=int, default=60000, help="Maximum analysis time in milliseconds")
    
    args = parser.parse_args()
    
    # Validate arguments
    if not any([args.file, args.query, args.interactive]):
        print("❌ Please specify --file, --query, or --interactive")
        sys.exit(1)
    
    try:
        runner = ExampleRunner(args.db_connection)
        
        # Configure agent
        runner.agent.max_cost = args.max_cost
        runner.agent.max_time_ms = args.max_time_ms
        
        async def run():
            if args.interactive:
                await runner.interactive_mode()
            elif args.file:
                results = await runner.run_file(
                    args.file, 
                    use_real=args.real, 
                    use_hypopg=args.use_hypopg
                )
                
                if args.output:
                    with open(args.output, 'w') as f:
                        json.dump(results, f, indent=2)
                    print(f"📄 Results saved to {args.output}")
                
                # Print summary
                passed = sum(1 for r in results if r.get("feedback", {}).get("status") == "PASS")
                total = len(results)
                print(f"\n📊 Summary: {passed}/{total} queries passed optimization")
                
            elif args.query:
                result = await runner.run_query(
                    args.query, 
                    use_real=args.real, 
                    use_hypopg=args.use_hypopg
                )
                runner._print_result(result)
                
                if args.output:
                    with open(args.output, 'w') as f:
                        json.dump(result, f, indent=2)
                    print(f"📄 Result saved to {args.output}")
        
        asyncio.run(run())
        
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
