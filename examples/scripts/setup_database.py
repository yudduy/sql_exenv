#!/usr/bin/env python3
"""
Database Setup Script for SQL Optimization Examples

This script helps users set up a PostgreSQL database with sample data
for testing SQL query optimization with sql_exenv.

Usage:
    python setup_database.py --db-connection postgresql://localhost/example_db
    python setup_database.py --host localhost --port 5432 --dbname example_db --user postgres
"""

import argparse
import psycopg2
import sys
import os
from pathlib import Path

def read_sql_file(filename):
    """Read SQL file content"""
    script_dir = Path(__file__).parent.parent
    file_path = script_dir / "schemas" / filename
    with open(file_path, 'r') as f:
        return f.read()

def execute_sql(connection_string, sql_content):
    """Execute SQL commands"""
    try:
        conn = psycopg2.connect(connection_string)
        conn.autocommit = True
        cursor = conn.cursor()
        
        # Split SQL content by semicolons and execute each statement
        statements = [stmt.strip() for stmt in sql_content.split(';') if stmt.strip()]
        
        for statement in statements:
            if statement:
                try:
                    cursor.execute(statement)
                    print(f"Executed: {statement[:50]}...")
                except Exception as e:
                    print(f"Error executing statement: {e}")
                    print(f"  Statement: {statement[:100]}...")
        
        cursor.close()
        conn.close()
        return True
        
    except Exception as e:
        print(f"Database connection error: {e}")
        return False

def main():
    parser = argparse.ArgumentParser(description="Setup example database for SQL optimization testing")
    parser.add_argument("--db-connection", help="Full PostgreSQL connection string")
    parser.add_argument("--host", default="localhost", help="Database host")
    parser.add_argument("--port", default=5432, type=int, help="Database port")
    parser.add_argument("--dbname", required=True, help="Database name")
    parser.add_argument("--user", default="postgres", help="Database user")
    parser.add_argument("--password", help="Database password (if not using trust/auth)")
    parser.add_argument("--teardown", action="store_true", help="Drop all tables instead of creating them")
    
    args = parser.parse_args()
    
    # Build connection string
    if args.db_connection:
        connection_string = args.db_connection
    else:
        if args.password:
            connection_string = f"postgresql://{args.user}:{args.password}@{args.host}:{args.port}/{args.dbname}"
        else:
            connection_string = f"postgresql://{args.user}@{args.host}:{args.port}/{args.dbname}"
    
    # Choose SQL file
    sql_file = "teardown.sql" if args.teardown else "setup.sql"
    action = "Tearing down" if args.teardown else "Setting up"
    
    print(f"Setting up example database...")
    print(f"Connection: {connection_string}")
    print(f"Using script: {sql_file}")
    print()
    
    # Read and execute SQL
    try:
        sql_content = read_sql_file(sql_file)
        print(f"Read {len(sql_content)} characters from {sql_file}")
        print()
        
        if execute_sql(connection_string, sql_content):
            print(f"Database {action.lower()} completed successfully!")
            if not args.teardown:
                print()
                print("Next steps:")
                print("1. Test the CLI with: python ../cli.py --db-connection " + connection_string)
                print("2. Try sample queries from: ../queries/sample_queries.sql")
                print("3. Run optimization tests with: python ../cli.py --db-connection " + connection_string + " --query-file ../queries/test_queries.sql")
        else:
            print(f"Database {action.lower()} failed!")
            sys.exit(1)
            
    except FileNotFoundError:
        print(f"SQL file not found: {sql_file}")
        sys.exit(1)
    except Exception as e:
        print(f"Unexpected error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
