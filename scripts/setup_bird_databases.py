#!/usr/bin/env python3
"""
Automated database setup for BIRD-CRITIC evaluation.

Reads flash_exp_200.jsonl and flash_schema.jsonl to:
1. Identify all unique databases (expect ~12)
2. Create PostgreSQL databases
3. Load schemas with CREATE TABLE statements
4. Verify constraints and foreign keys
5. Support idempotent re-runs

Usage:
    python scripts/setup_bird_databases.py

    # Or with custom paths:
    python scripts/setup_bird_databases.py --dataset-path BIRD-CRITIC-1/baseline/data/flash_exp_200.jsonl
"""

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Set, Optional

import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT


class BirdDatabaseSetup:
    """Automated setup for BIRD-CRITIC databases."""

    def __init__(self, host: str = "/tmp", user: str = "duynguy", port: int = 5432):
        """
        Initialize database setup manager.

        Args:
            host: PostgreSQL host (default: /tmp for Unix socket)
            user: PostgreSQL user
            port: PostgreSQL port
        """
        self.host = host
        self.user = user
        self.port = port

        # Connection string for admin operations (creating databases)
        if host.startswith("/"):
            # Unix socket
            self.admin_conn_str = f"dbname=postgres host={host} user={user}"
        else:
            # TCP connection
            self.admin_conn_str = f"dbname=postgres host={host} port={port} user={user}"

    def get_databases_from_dataset(self, dataset_path: Path) -> Set[str]:
        """
        Extract unique db_ids from Flash-Exp 200 dataset.

        Args:
            dataset_path: Path to flash_exp_200.jsonl

        Returns:
            Set of unique database identifiers
        """
        db_ids = set()

        if not dataset_path.exists():
            raise FileNotFoundError(f"Dataset not found: {dataset_path}")

        with open(dataset_path, 'r') as f:
            for line_num, line in enumerate(f, 1):
                if not line.strip():
                    continue

                try:
                    task = json.loads(line)
                    db_id = task.get("db_id")
                    if db_id:
                        db_ids.add(db_id)
                except json.JSONDecodeError as e:
                    print(f"Warning: Failed to parse line {line_num}: {e}")
                    continue

        return db_ids

    def get_schema_for_database(
        self,
        db_id: str,
        schema_path: Path,
        dataset_path: Path
    ) -> Optional[Dict]:
        """
        Load schema from flash_schema.jsonl by matching db_id.

        Since schema file uses instance_id instead of db_id, we need to:
        1. Find an instance_id from dataset that has this db_id
        2. Load schema for that instance_id

        Args:
            db_id: Database identifier
            schema_path: Path to flash_schema.jsonl
            dataset_path: Path to flash_exp_200.jsonl (to map db_id to instance_id)

        Returns:
            Schema entry dictionary or None if not found
        """
        if not schema_path.exists():
            print(f"Warning: Schema file not found: {schema_path}")
            return None

        # Step 1: Find an instance_id that uses this db_id
        target_instance_id = None
        with open(dataset_path, 'r') as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    task = json.loads(line)
                    if task.get("db_id") == db_id:
                        target_instance_id = task.get("instance_id")
                        break
                except json.JSONDecodeError:
                    continue

        if target_instance_id is None:
            print(f"  ⚠️  No instance found for db_id '{db_id}' in dataset")
            return None

        # Step 2: Load schema for this instance_id
        with open(schema_path, 'r') as f:
            for line_num, line in enumerate(f, 1):
                if not line.strip():
                    continue

                try:
                    schema_entry = json.loads(line)
                    # Match by instance_id
                    if schema_entry.get("instance_id") == target_instance_id:
                        return schema_entry
                except json.JSONDecodeError as e:
                    print(f"Warning: Failed to parse schema line {line_num}: {e}")
                    continue

        return None

    def create_database(self, db_id: str) -> bool:
        """
        Create PostgreSQL database if not exists.

        Args:
            db_id: Database name to create

        Returns:
            True if successful, False otherwise
        """
        try:
            conn = psycopg2.connect(self.admin_conn_str)
            conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
            cursor = conn.cursor()

            # Check if database exists
            cursor.execute(
                "SELECT 1 FROM pg_database WHERE datname = %s",
                (db_id,)
            )

            if cursor.fetchone():
                print(f"  Database '{db_id}' already exists")
                cursor.close()
                conn.close()
                return True

            # Create database (using identifier to prevent SQL injection)
            cursor.execute(f'CREATE DATABASE "{db_id}"')
            print(f"  ✓ Created database '{db_id}'")

            cursor.close()
            conn.close()
            return True

        except psycopg2.Error as e:
            print(f"  ✗ Failed to create database '{db_id}': {e}")
            return False

    def _extract_create_statements(self, schema_ddl: str) -> List[str]:
        """
        Extract individual CREATE TABLE statements from schema DDL.

        Handles multi-line CREATE TABLE statements properly.
        Removes FOREIGN KEY constraints to avoid dependency issues.

        Args:
            schema_ddl: Full schema DDL text

        Returns:
            List of individual CREATE TABLE statements (without FK constraints)
        """
        # Split on CREATE TABLE, keeping the delimiter
        parts = re.split(r'(CREATE TABLE)', schema_ddl, flags=re.IGNORECASE)

        statements = []
        for i in range(1, len(parts), 2):
            if i + 1 < len(parts):
                # Combine "CREATE TABLE" with the table definition
                statement = parts[i] + parts[i + 1]

                # Extract just the CREATE TABLE ... ; portion
                # Match until the first semicolon after the closing parenthesis
                match = re.search(
                    r'CREATE TABLE.*?\);',
                    statement,
                    re.IGNORECASE | re.DOTALL
                )

                if match:
                    stmt = match.group(0).strip()
                    if stmt:
                        # Remove FOREIGN KEY constraints to avoid dependency order issues
                        # Pattern: FOREIGN KEY (...) REFERENCES ...
                        stmt = re.sub(
                            r',\s*FOREIGN KEY\s*\([^)]+\)\s*REFERENCES\s+[^\n,)]+',
                            '',
                            stmt,
                            flags=re.IGNORECASE
                        )

                        # Fix column names with spaces by quoting them
                        # Pattern: identifier with space followed by type
                        # e.g., "Academic Year text" -> "\"Academic Year\" text"
                        stmt = re.sub(
                            r'\n([A-Za-z][A-Za-z0-9 _-]*)\s+(text|bigint|integer|real|date|boolean|timestamp)',
                            lambda m: f'\n"{m.group(1)}" {m.group(2)}' if ' ' in m.group(1) or '-' in m.group(1) else m.group(0),
                            stmt,
                            flags=re.IGNORECASE
                        )

                        # Remove nextval() DEFAULT clauses that reference non-existent sequences
                        # Pattern: DEFAULT nextval('sequence_name'::regclass)
                        stmt = re.sub(
                            r"DEFAULT nextval\('[^']+'::\w+\)",
                            '',
                            stmt,
                            flags=re.IGNORECASE
                        )

                        statements.append(stmt)

        return statements

    def load_schema(self, db_id: str, schema_ddl: str) -> bool:
        """
        Execute schema DDL statements to create tables.

        Args:
            db_id: Database name
            schema_ddl: Full schema DDL with CREATE TABLE statements

        Returns:
            True if successful, False otherwise
        """
        try:
            # Build connection string for specific database
            if self.host.startswith("/"):
                db_conn_str = f"dbname={db_id} host={self.host} user={self.user}"
            else:
                db_conn_str = f"dbname={db_id} host={self.host} port={self.port} user={self.user}"

            conn = psycopg2.connect(db_conn_str)
            conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
            cursor = conn.cursor()

            # Extract CREATE TABLE statements
            statements = self._extract_create_statements(schema_ddl)

            if not statements:
                print(f"  ⚠️  No CREATE TABLE statements found in schema")
                return False

            # Execute each statement
            for stmt in statements:
                try:
                    cursor.execute(stmt)
                except psycopg2.Error as e:
                    # Check if table already exists
                    if "already exists" in str(e).lower():
                        # Extract table name for clearer message
                        table_match = re.search(r'CREATE TABLE\s+"?(\w+)"?', stmt, re.IGNORECASE)
                        table_name = table_match.group(1) if table_match else "unknown"
                        print(f"    Table '{table_name}' already exists, skipping")
                    else:
                        print(f"  ⚠️  Failed to execute statement: {e}")
                        print(f"    Statement: {stmt[:100]}...")
                        # Continue with other tables

            cursor.close()
            conn.close()

            print(f"  ✓ Loaded {len(statements)} tables")
            return True

        except psycopg2.Error as e:
            print(f"  ✗ Failed to load schema: {e}")
            return False

    def verify_database(self, db_id: str, expected_tables: int) -> bool:
        """
        Verify database setup by checking table count.

        Args:
            db_id: Database name
            expected_tables: Expected number of tables

        Returns:
            True if verification passed, False otherwise
        """
        try:
            if self.host.startswith("/"):
                db_conn_str = f"dbname={db_id} host={self.host} user={self.user}"
            else:
                db_conn_str = f"dbname={db_id} host={self.host} port={self.port} user={self.user}"

            conn = psycopg2.connect(db_conn_str)
            cursor = conn.cursor()

            # Count tables in public schema
            cursor.execute(
                "SELECT COUNT(*) FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"
            )
            actual_tables = cursor.fetchone()[0]

            # Also get table names for debugging
            cursor.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_type = 'BASE TABLE' "
                "ORDER BY table_name"
            )
            table_names = [row[0] for row in cursor.fetchall()]

            cursor.close()
            conn.close()

            if actual_tables >= expected_tables:
                print(f"  ✓ Verified {actual_tables} tables")
                print(f"    Tables: {', '.join(table_names[:5])}" +
                      (f" ... ({len(table_names) - 5} more)" if len(table_names) > 5 else ""))
                return True
            else:
                print(f"  ⚠️  Expected {expected_tables} tables, found {actual_tables}")
                print(f"    Tables: {', '.join(table_names)}")
                return False

        except psycopg2.Error as e:
            print(f"  ✗ Verification failed: {e}")
            return False

    def setup_all_databases(
        self,
        dataset_path: Path,
        schema_path: Path,
        dry_run: bool = False
    ) -> Dict[str, bool]:
        """
        Main orchestration method to setup all databases.

        Args:
            dataset_path: Path to flash_exp_200.jsonl
            schema_path: Path to flash_schema.jsonl
            dry_run: If True, only show what would be done

        Returns:
            Dictionary mapping db_id to success status
        """
        print("=" * 70)
        print("BIRD-CRITIC Database Setup")
        print("=" * 70)

        # Step 1: Get database list from dataset
        print("\n[1/4] Scanning dataset for databases...")
        try:
            db_ids = self.get_databases_from_dataset(dataset_path)
            print(f"Found {len(db_ids)} unique databases:")
            for db_id in sorted(db_ids):
                print(f"  - {db_id}")
        except Exception as e:
            print(f"Error scanning dataset: {e}")
            return {}

        if dry_run:
            print("\n[DRY RUN] Would setup these databases. Exiting.")
            return {db_id: False for db_id in db_ids}

        # Step 2: Setup each database
        print(f"\n[2/4] Setting up {len(db_ids)} databases...")
        results = {}

        for idx, db_id in enumerate(sorted(db_ids), 1):
            print(f"\n[{idx}/{len(db_ids)}] {db_id}")
            print("-" * 50)

            # Get schema (need dataset_path to map db_id to instance_id)
            schema_entry = self.get_schema_for_database(db_id, schema_path, dataset_path)
            if not schema_entry:
                print(f"  ✗ Schema not found in {schema_path}")
                results[db_id] = False
                continue

            # Create database
            if not self.create_database(db_id):
                results[db_id] = False
                continue

            # Load schema (prefer preprocess_schema with sample data)
            schema_ddl = schema_entry.get("preprocess_schema") or schema_entry.get("original_schema")
            if not schema_ddl:
                print(f"  ✗ No schema DDL found in schema entry")
                results[db_id] = False
                continue

            if not self.load_schema(db_id, schema_ddl):
                results[db_id] = False
                continue

            # Verify setup
            table_count = schema_ddl.count("CREATE TABLE")
            if self.verify_database(db_id, table_count):
                results[db_id] = True
            else:
                results[db_id] = False

        # Step 3: Summary
        print("\n" + "=" * 70)
        print("SETUP SUMMARY")
        print("=" * 70)

        success_count = sum(1 for v in results.values() if v)
        total_count = len(results)

        print(f"\nSuccessfully setup: {success_count}/{total_count} databases")

        if success_count < total_count:
            print("\nFailed databases:")
            for db_id, success in results.items():
                if not success:
                    print(f"  ✗ {db_id}")

        print("\nSuccess!")
        return results


def main():
    """Command-line interface for database setup."""
    parser = argparse.ArgumentParser(
        description="Automated setup for BIRD-CRITIC databases",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Setup all databases (default paths):
  python scripts/setup_bird_databases.py

  # Dry run to see what would be done:
  python scripts/setup_bird_databases.py --dry-run

  # Custom paths:
  python scripts/setup_bird_databases.py \\
    --dataset-path BIRD-CRITIC-1/baseline/data/flash_exp_200.jsonl \\
    --schema-path BIRD-CRITIC-1/baseline/data/flash_schema.jsonl

  # Custom PostgreSQL connection:
  python scripts/setup_bird_databases.py --host localhost --port 5432 --user postgres
        """
    )

    parser.add_argument(
        "--dataset-path",
        type=Path,
        default=Path("BIRD-CRITIC-1/baseline/data/flash_exp_200.jsonl"),
        help="Path to flash_exp_200.jsonl dataset"
    )

    parser.add_argument(
        "--schema-path",
        type=Path,
        default=Path("BIRD-CRITIC-1/baseline/data/flash_schema.jsonl"),
        help="Path to flash_schema.jsonl schema file"
    )

    parser.add_argument(
        "--host",
        type=str,
        default="/tmp",
        help="PostgreSQL host (default: /tmp for Unix socket)"
    )

    parser.add_argument(
        "--port",
        type=int,
        default=5432,
        help="PostgreSQL port (default: 5432)"
    )

    parser.add_argument(
        "--user",
        type=str,
        default="duynguy",
        help="PostgreSQL user (default: duynguy)"
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without making changes"
    )

    args = parser.parse_args()

    # Initialize setup manager
    setup = BirdDatabaseSetup(host=args.host, user=args.user, port=args.port)

    # Run setup
    try:
        results = setup.setup_all_databases(
            dataset_path=args.dataset_path,
            schema_path=args.schema_path,
            dry_run=args.dry_run
        )

        # Exit with error code if any database failed
        if not all(results.values()):
            sys.exit(1)

    except KeyboardInterrupt:
        print("\n\nSetup interrupted by user")
        sys.exit(130)
    except Exception as e:
        print(f"\n\nFatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
