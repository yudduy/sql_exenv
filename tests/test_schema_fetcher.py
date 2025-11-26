"""
TDD Tests for Schema Fetcher

Tests for automatic PostgreSQL schema metadata fetching.
Following TDD: Write tests FIRST, then implement.
"""

from unittest.mock import MagicMock, patch

import psycopg2
import pytest


class TestSchemaFetcherInit:
    """Test schema fetcher initialization."""

    def test_init_with_connection_string(self):
        """Should initialize with connection string."""
        from src.schema_fetcher import SchemaFetcher

        fetcher = SchemaFetcher("postgresql://localhost:5432/testdb")
        assert fetcher.db_connection == "postgresql://localhost:5432/testdb"
        assert fetcher.schema == 'public'

    def test_init_with_custom_schema(self):
        """Should accept custom schema name."""
        from src.schema_fetcher import SchemaFetcher

        fetcher = SchemaFetcher("postgresql://localhost:5432/testdb", schema='myschema')
        assert fetcher.schema == 'myschema'


class TestTableNameExtraction:
    """Test SQL table name extraction using sqlparse."""

    def test_extract_simple_select(self):
        """Should extract table from simple SELECT."""
        from src.schema_fetcher import SchemaFetcher

        fetcher = SchemaFetcher("postgresql://localhost:5432/testdb")
        tables = fetcher._extract_table_names("SELECT * FROM users")

        assert tables == ['users']

    def test_extract_table_with_schema(self):
        """Should extract table name without schema prefix."""
        from src.schema_fetcher import SchemaFetcher

        fetcher = SchemaFetcher("postgresql://localhost:5432/testdb")
        tables = fetcher._extract_table_names("SELECT * FROM public.users")

        assert 'users' in tables

    def test_extract_join_query(self):
        """Should extract multiple tables from JOIN."""
        from src.schema_fetcher import SchemaFetcher

        fetcher = SchemaFetcher("postgresql://localhost:5432/testdb")
        tables = fetcher._extract_table_names(
            "SELECT * FROM users u JOIN orders o ON u.id = o.user_id"
        )

        assert set(tables) == {'users', 'orders'}

    def test_extract_left_join(self):
        """Should extract tables from LEFT JOIN."""
        from src.schema_fetcher import SchemaFetcher

        fetcher = SchemaFetcher("postgresql://localhost:5432/testdb")
        tables = fetcher._extract_table_names(
            "SELECT * FROM users u LEFT JOIN orders o ON u.id = o.user_id"
        )

        assert set(tables) == {'users', 'orders'}

    def test_extract_multiple_joins(self):
        """Should extract tables from multiple JOINs."""
        from src.schema_fetcher import SchemaFetcher

        fetcher = SchemaFetcher("postgresql://localhost:5432/testdb")
        tables = fetcher._extract_table_names(
            """SELECT * FROM users u
               JOIN orders o ON u.id = o.user_id
               JOIN products p ON o.product_id = p.id"""
        )

        assert set(tables) == {'users', 'orders', 'products'}

    def test_extract_subquery(self):
        """Should extract tables from nested subqueries."""
        from src.schema_fetcher import SchemaFetcher

        fetcher = SchemaFetcher("postgresql://localhost:5432/testdb")
        tables = fetcher._extract_table_names(
            "SELECT * FROM (SELECT * FROM users WHERE active=true) u"
        )

        assert 'users' in tables

    def test_extract_cte_with_clause(self):
        """Should extract tables from CTEs (WITH clauses)."""
        from src.schema_fetcher import SchemaFetcher

        fetcher = SchemaFetcher("postgresql://localhost:5432/testdb")
        tables = fetcher._extract_table_names(
            "WITH active_users AS (SELECT * FROM users WHERE active=true) SELECT * FROM active_users"
        )

        assert 'users' in tables

    def test_extract_table_with_alias(self):
        """Should extract table name ignoring alias."""
        from src.schema_fetcher import SchemaFetcher

        fetcher = SchemaFetcher("postgresql://localhost:5432/testdb")
        tables = fetcher._extract_table_names("SELECT * FROM users AS u")

        assert 'users' in tables
        assert 'u' not in tables

    def test_extract_no_duplicates(self):
        """Should not return duplicate table names."""
        from src.schema_fetcher import SchemaFetcher

        fetcher = SchemaFetcher("postgresql://localhost:5432/testdb")
        tables = fetcher._extract_table_names(
            "SELECT * FROM users u1 JOIN users u2 ON u1.manager_id = u2.id"
        )

        assert tables.count('users') == 1


class TestSchemaFetching:
    """Test PostgreSQL schema metadata fetching."""

    @pytest.fixture
    def mock_connection(self):
        """Mock psycopg2 connection and cursor."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        return mock_conn, mock_cursor

    def test_fetch_table_columns(self, mock_connection):
        """Should fetch table columns with data types."""
        from src.schema_fetcher import SchemaFetcher

        mock_conn, mock_cursor = mock_connection

        # Mock responses: first for columns, second for indexes, third for foreign keys
        mock_cursor.fetchall.side_effect = [
            [
                ('id', 'integer', 'NO', 'integer'),
                ('email', 'character varying', 'NO', 'character varying(255)'),
                ('created_at', 'timestamp without time zone', 'YES', 'timestamp'),
            ],
            [],  # no indexes
            []   # no foreign keys
        ]

        fetcher = SchemaFetcher("postgresql://localhost:5432/testdb")

        with patch('psycopg2.connect', return_value=mock_conn):
            schema = fetcher._fetch_table_schema('users')

            # Verify query was executed
            assert mock_cursor.execute.called

            # Verify schema contains table name and columns
            assert 'users' in schema.lower()
            assert 'email' in schema
            assert 'varchar(255)' in schema or 'character varying(255)' in schema

    def test_fetch_table_indexes(self, mock_connection):
        """Should fetch existing indexes for table."""
        from src.schema_fetcher import SchemaFetcher

        mock_conn, mock_cursor = mock_connection

        # Mock responses: first for columns, second for indexes
        mock_cursor.fetchall.side_effect = [
            [('id', 'integer', 'NO', 'integer')],  # columns
            [('idx_users_email', 'CREATE INDEX idx_users_email ON users USING btree (email)')],  # indexes
            []  # foreign keys
        ]

        fetcher = SchemaFetcher("postgresql://localhost:5432/testdb")

        with patch('psycopg2.connect', return_value=mock_conn):
            schema = fetcher._fetch_table_schema('users')

            # Should include index information
            assert 'INDEXES' in schema or 'INDEX' in schema
            assert 'idx_users_email' in schema

    def test_fetch_no_indexes(self, mock_connection):
        """Should handle tables with no indexes."""
        from src.schema_fetcher import SchemaFetcher

        mock_conn, mock_cursor = mock_connection

        # Mock responses: columns but no indexes
        mock_cursor.fetchall.side_effect = [
            [('id', 'integer', 'NO', 'integer')],
            [],  # no indexes
            []   # no foreign keys
        ]

        fetcher = SchemaFetcher("postgresql://localhost:5432/testdb")

        with patch('psycopg2.connect', return_value=mock_conn):
            schema = fetcher._fetch_table_schema('users')

            # Should indicate no indexes
            assert 'None' in schema or 'no indexes' in schema.lower()

    def test_fetch_foreign_keys(self, mock_connection):
        """Should fetch foreign key relationships."""
        from src.schema_fetcher import SchemaFetcher

        mock_conn, mock_cursor = mock_connection

        # Mock responses
        mock_cursor.fetchall.side_effect = [
            [('id', 'integer', 'NO', 'integer'), ('user_id', 'integer', 'NO', 'integer')],
            [],  # no indexes
            [('user_id', 'users', 'id')]  # foreign key
        ]

        fetcher = SchemaFetcher("postgresql://localhost:5432/testdb")

        with patch('psycopg2.connect', return_value=mock_conn):
            schema = fetcher._fetch_table_schema('orders')

            # Should show FK relationship
            assert 'user_id' in schema
            assert 'users' in schema


class TestSchemaFormat:
    """Test minimal schema format for context window optimization."""

    @pytest.fixture
    def mock_connection(self):
        """Mock psycopg2 connection."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        # Default mock response
        mock_cursor.fetchall.side_effect = [
            [('id', 'integer', 'NO', 'integer'), ('name', 'varchar', 'NO', 'varchar(100)')],
            [],  # no indexes
            []   # no foreign keys
        ]

        return mock_conn, mock_cursor

    def test_minimal_format_is_compact(self, mock_connection):
        """Schema should use minimal format to reduce tokens."""
        from src.schema_fetcher import SchemaFetcher

        mock_conn, mock_cursor = mock_connection

        fetcher = SchemaFetcher("postgresql://localhost:5432/testdb")

        with patch('psycopg2.connect', return_value=mock_conn):
            schema = fetcher._fetch_table_schema('users')

            # Should be compact (no verbose CREATE TABLE syntax)
            assert 'CREATE TABLE' not in schema

            # Should contain essential info
            assert 'TABLE' in schema or 'users' in schema
            assert 'id' in schema

    def test_format_includes_data_types(self, mock_connection):
        """Should include data types in compact format."""
        from src.schema_fetcher import SchemaFetcher

        mock_conn, mock_cursor = mock_connection

        fetcher = SchemaFetcher("postgresql://localhost:5432/testdb")

        with patch('psycopg2.connect', return_value=mock_conn):
            schema = fetcher._fetch_table_schema('users')

            # Should show data types
            assert 'integer' in schema.lower() or 'int' in schema.lower()
            assert 'varchar' in schema.lower()

    def test_format_is_readable(self, mock_connection):
        """Format should be LLM-readable."""
        from src.schema_fetcher import SchemaFetcher

        mock_conn, mock_cursor = mock_connection

        fetcher = SchemaFetcher("postgresql://localhost:5432/testdb")

        with patch('psycopg2.connect', return_value=mock_conn):
            schema = fetcher._fetch_table_schema('users')

            # Should have structure (not just JSON dump)
            assert '\n' in schema  # Multi-line
            assert ':' in schema or '=' in schema  # Key-value pairs


class TestFetchSchemaForQuery:
    """Test end-to-end schema fetching for SQL query."""

    @pytest.fixture
    def mock_connection(self):
        """Mock psycopg2 connection."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        # Mock responses for multiple tables
        mock_cursor.fetchall.side_effect = [
            # users table
            [('id', 'integer', 'NO', 'integer'), ('email', 'varchar', 'NO', 'varchar(255)')],
            [],  # no indexes
            [],  # no FKs
            # orders table
            [('id', 'integer', 'NO', 'integer'), ('user_id', 'integer', 'NO', 'integer')],
            [],  # no indexes
            [('user_id', 'users', 'id')]  # FK
        ]

        return mock_conn, mock_cursor

    def test_fetch_for_simple_query(self, mock_connection):
        """Should fetch schema for simple query."""
        from src.schema_fetcher import SchemaFetcher

        mock_conn, mock_cursor = mock_connection

        fetcher = SchemaFetcher("postgresql://localhost:5432/testdb")

        with patch('psycopg2.connect', return_value=mock_conn):
            schema = fetcher.fetch_schema_for_query("SELECT * FROM users")

            assert 'users' in schema
            assert schema is not None
            assert len(schema) > 0

    def test_fetch_for_join_query(self, mock_connection):
        """Should fetch schema for all tables in JOIN."""
        from src.schema_fetcher import SchemaFetcher

        mock_conn, mock_cursor = mock_connection

        fetcher = SchemaFetcher("postgresql://localhost:5432/testdb")

        with patch('psycopg2.connect', return_value=mock_conn):
            schema = fetcher.fetch_schema_for_query(
                "SELECT * FROM users u JOIN orders o ON u.id = o.user_id"
            )

            # Should include both tables
            assert 'users' in schema
            assert 'orders' in schema

    def test_handles_table_not_found(self):
        """Should handle gracefully when table doesn't exist."""
        from src.schema_fetcher import SchemaFetcher

        fetcher = SchemaFetcher("postgresql://localhost:5432/testdb")

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_cursor.fetchall.return_value = []  # Empty result

        with patch('psycopg2.connect', return_value=mock_conn):
            # Should not crash
            schema = fetcher.fetch_schema_for_query("SELECT * FROM nonexistent_table")

            # Should return something (even if minimal)
            assert schema is not None


class TestErrorHandling:
    """Test error handling for database connection issues."""

    def test_handles_connection_error(self):
        """Should handle database connection errors gracefully."""
        from src.schema_fetcher import SchemaFetcher

        fetcher = SchemaFetcher("postgresql://invalid:5432/testdb")

        with patch('psycopg2.connect', side_effect=psycopg2.OperationalError("Connection failed")):
            # Should not crash, should return empty or error message
            try:
                schema = fetcher.fetch_schema_for_query("SELECT * FROM users")
                # If it returns something, it should be a string
                assert isinstance(schema, str)
            except psycopg2.OperationalError:
                # Or it can raise the error for the caller to handle
                pass

    def test_handles_invalid_sql(self):
        """Should handle invalid SQL gracefully."""
        from src.schema_fetcher import SchemaFetcher

        fetcher = SchemaFetcher("postgresql://localhost:5432/testdb")

        # Invalid SQL should not crash the parser
        schema = fetcher.fetch_schema_for_query("INVALID SQL SYNTAX ;;;")

        # Should return something (even empty string is fine)
        assert isinstance(schema, str)
