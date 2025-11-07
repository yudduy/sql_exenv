"""
Integration tests for database setup and multi-query support.

Tests:
1. Database setup script functionality
2. Multi-query task support in agent
3. Preprocess and cleanup SQL execution
"""

import asyncio
import json
import os
import sys
from pathlib import Path

import psycopg2
import pytest

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.setup_bird_databases import BirdDatabaseSetup
from src.agentic_dba.agent import BIRDCriticTask, SQLOptimizationAgent


class TestDatabaseSetup:
    """Test database setup automation."""

    @pytest.fixture
    def setup_manager(self):
        """Create database setup manager."""
        return BirdDatabaseSetup(host="/tmp", user="duynguy")

    def test_extract_databases_from_dataset(self, setup_manager):
        """Test extracting unique database IDs from dataset."""
        dataset_path = Path("BIRD-CRITIC-1/baseline/data/flash_exp_200.jsonl")

        if not dataset_path.exists():
            pytest.skip("Dataset not found")

        db_ids = setup_manager.get_databases_from_dataset(dataset_path)

        # Verify we found the expected databases
        assert len(db_ids) == 12, f"Expected 12 databases, found {len(db_ids)}"

        # Verify specific known databases
        expected_dbs = {'financial', 'codebase_community', 'student_club'}
        assert expected_dbs.issubset(db_ids), f"Missing expected databases: {expected_dbs - db_ids}"

    def test_get_schema_for_database(self, setup_manager):
        """Test loading schema from JSONL file."""
        schema_path = Path("BIRD-CRITIC-1/baseline/data/flash_schema.jsonl")
        dataset_path = Path("BIRD-CRITIC-1/baseline/data/flash_exp_200.jsonl")

        if not schema_path.exists():
            pytest.skip("Schema file not found")

        # Test loading financial database schema
        schema_entry = setup_manager.get_schema_for_database("financial", schema_path, dataset_path)

        assert schema_entry is not None, "Schema not found for 'financial' database"
        assert "preprocess_schema" in schema_entry or "original_schema" in schema_entry
        assert "CREATE TABLE" in (schema_entry.get("preprocess_schema") or schema_entry.get("original_schema"))

    def test_extract_create_statements(self, setup_manager):
        """Test parsing CREATE TABLE statements from schema DDL."""
        schema_ddl = """
        CREATE TABLE "users" (
            id bigint NOT NULL,
            name text NULL,
            PRIMARY KEY (id)
        );

        First 3 rows:
        id  name
        1   Alice

        CREATE TABLE "orders" (
            order_id bigint NOT NULL,
            user_id bigint NULL,
            PRIMARY KEY (order_id)
        );
        """

        statements = setup_manager._extract_create_statements(schema_ddl)

        assert len(statements) == 2, f"Expected 2 statements, got {len(statements)}"
        assert "users" in statements[0].lower()
        assert "orders" in statements[1].lower()

    def test_create_database_idempotent(self, setup_manager):
        """Test database creation is idempotent."""
        test_db = "test_bird_setup_idempotent"

        try:
            # Create database first time
            result1 = setup_manager.create_database(test_db)
            assert result1 is True

            # Create database second time (should succeed with "already exists" message)
            result2 = setup_manager.create_database(test_db)
            assert result2 is True

        finally:
            # Cleanup test database
            try:
                conn = psycopg2.connect(setup_manager.admin_conn_str)
                conn.set_isolation_level(psycopg2.extensions.ISOLATION_LEVEL_AUTOCOMMIT)
                cursor = conn.cursor()
                cursor.execute(f'DROP DATABASE IF EXISTS "{test_db}"')
                cursor.close()
                conn.close()
            except Exception as e:
                print(f"Warning: Cleanup failed: {e}")

    def test_verify_database(self, setup_manager):
        """Test database verification checks table count."""
        # Use existing 'financial' database if available
        db_id = "financial"

        try:
            # Verify database exists and has tables
            result = setup_manager.verify_database(db_id, expected_tables=1)

            # Result should be boolean
            assert isinstance(result, bool)

            # If financial database doesn't exist, this test will fail gracefully
        except psycopg2.OperationalError:
            pytest.skip(f"Database '{db_id}' not available for testing")


class TestMultiQuerySupport:
    """Test multi-query task support in agent."""

    @pytest.fixture
    def agent(self):
        """Create SQL optimization agent."""
        return SQLOptimizationAgent(
            max_iterations=3,
            timeout_per_task_seconds=30,
            use_extended_thinking=False  # Disable for faster tests
        )

    def test_task_with_issue_sql_array(self, agent):
        """Test BIRDCriticTask supports issue_sql array."""
        task = BIRDCriticTask(
            task_id="multi_test",
            db_id="test_db",
            user_query="Test multi-query",
            issue_sql=[
                "CREATE TABLE test (id int);",
                "INSERT INTO test VALUES (1);"
            ]
        )

        # Verify attributes exist
        assert task.issue_sql is not None
        assert len(task.issue_sql) == 2
        assert task.issue_sql[0] == "CREATE TABLE test (id int);"

    def test_task_with_preprocess_sql(self, agent):
        """Test BIRDCriticTask supports preprocess_sql setup queries."""
        task = BIRDCriticTask(
            task_id="setup_test",
            db_id="test_db",
            user_query="Test setup queries",
            issue_sql=["SELECT * FROM test_table;"],
            preprocess_sql=[
                "DROP TABLE IF EXISTS test_table;",
                "CREATE TABLE test_table (id int);"
            ]
        )

        # Verify attributes exist
        assert task.preprocess_sql is not None
        assert len(task.preprocess_sql) == 2

    def test_task_with_cleanup_sql(self, agent):
        """Test BIRDCriticTask supports clean_up_sql teardown queries."""
        task = BIRDCriticTask(
            task_id="cleanup_test",
            db_id="test_db",
            user_query="Test cleanup queries",
            issue_sql=["SELECT * FROM test_table;"],
            clean_up_sql=["DROP TABLE IF EXISTS test_table;"]
        )

        # Verify attributes exist
        assert task.clean_up_sql is not None
        assert len(task.clean_up_sql) == 1

    def test_backward_compatibility_buggy_sql(self, agent):
        """Test backward compatibility with buggy_sql single query."""
        task = BIRDCriticTask(
            task_id="legacy_test",
            db_id="test_db",
            user_query="Legacy single query",
            buggy_sql="SELECT * FROM users;"
        )

        # Verify both fields work
        assert task.buggy_sql == "SELECT * FROM users;"
        assert task.issue_sql is None  # New field should be None for legacy tasks

    def test_agent_handles_multi_query_task(self, agent):
        """
        Test agent can process multi-query tasks.

        This is a smoke test - actual execution requires a database.
        """
        task = BIRDCriticTask(
            task_id="integration_test",
            db_id="financial",
            user_query="Test multi-query optimization",
            issue_sql=[
                "SELECT * FROM account WHERE account_id = 1;",
                "SELECT * FROM loan WHERE account_id = 1;"
            ],
            preprocess_sql=None,
            clean_up_sql=None
        )

        # Verify task structure is valid
        assert task.issue_sql is not None
        assert len(task.issue_sql) == 2

        # Note: Full execution test requires database connection
        # See test_bird_critic_runner_test.py for end-to-end tests


class TestRealWorldMultiQueryTask:
    """Test with actual BIRD-CRITIC multi-query task."""

    def test_load_multi_query_task_from_dataset(self):
        """Test loading a real multi-query task from dataset."""
        dataset_path = Path("BIRD-CRITIC-1/baseline/data/flash_exp_200.jsonl")

        if not dataset_path.exists():
            pytest.skip("Dataset not found")

        # Find a multi-query task (instance_id=2 is a known multi-query task)
        multi_query_task = None
        with open(dataset_path, 'r') as f:
            for line in f:
                task_data = json.loads(line)
                if task_data.get("instance_id") == 2:
                    multi_query_task = task_data
                    break

        assert multi_query_task is not None, "Multi-query task not found in dataset"

        # Verify structure
        assert "issue_sql" in multi_query_task
        assert isinstance(multi_query_task["issue_sql"], list)
        assert len(multi_query_task["issue_sql"]) > 1, "Expected multiple queries"

        # Verify preprocess_sql exists
        assert "preprocess_sql" in multi_query_task
        assert isinstance(multi_query_task["preprocess_sql"], list)

        print(f"\nMulti-query task found:")
        print(f"  DB: {multi_query_task['db_id']}")
        print(f"  Queries: {len(multi_query_task['issue_sql'])}")
        print(f"  Setup queries: {len(multi_query_task['preprocess_sql'])}")

    def test_create_bird_critic_task_from_dataset(self):
        """Test creating BIRDCriticTask from dataset JSON."""
        dataset_path = Path("BIRD-CRITIC-1/baseline/data/flash_exp_200.jsonl")

        if not dataset_path.exists():
            pytest.skip("Dataset not found")

        # Load first task
        with open(dataset_path, 'r') as f:
            task_data = json.loads(f.readline())

        # Create BIRDCriticTask from JSON
        task = BIRDCriticTask(
            task_id=str(task_data.get("instance_id")),
            db_id=task_data["db_id"],
            user_query=task_data.get("query", ""),
            issue_sql=task_data.get("issue_sql"),
            buggy_sql=task_data.get("issue_sql", [None])[0] if task_data.get("issue_sql") else None,
            solution_sql=task_data.get("solution_sql"),
            efficiency=task_data.get("efficiency", False),
            preprocess_sql=task_data.get("preprocess_sql"),
            clean_up_sql=task_data.get("clean_up_sql")
        )

        # Verify task created successfully
        assert task.task_id is not None
        assert task.db_id is not None
        assert task.issue_sql is not None or task.buggy_sql is not None


if __name__ == "__main__":
    # Run tests with pytest
    pytest.main([__file__, "-v", "-s"])
