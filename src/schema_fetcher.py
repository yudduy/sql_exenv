"""
PostgreSQL Schema Fetcher

Extracts schema metadata for SQL optimization agent.
Fetches only the tables referenced in the SQL query to minimize context window usage.
"""

from typing import List, Set, Optional
import psycopg2
import sqlparse
from sqlparse.sql import IdentifierList, Identifier
from sqlparse.tokens import Keyword


class SchemaFetcher:
    """
    Fetch schema metadata from PostgreSQL for SQL optimization.

    Provides minimal, context-window-optimized schema information by:
    1. Parsing SQL to extract table names
    2. Fetching only relevant table schemas
    3. Formatting in compact representation
    """

    def __init__(self, db_connection: str, schema: str = 'public'):
        """
        Initialize schema fetcher.

        Args:
            db_connection: PostgreSQL connection string
            schema: Database schema to query (default: 'public')
        """
        self.db_connection = db_connection
        self.schema = schema

    def fetch_schema_for_query(self, sql: str) -> str:
        """
        Extract and fetch schema for tables referenced in SQL query.

        Args:
            sql: SQL query to analyze

        Returns:
            Minimal schema string optimized for LLM context window
        """
        try:
            # Extract table names from SQL
            table_names = self._extract_table_names(sql)

            if not table_names:
                return ""

            # Fetch schema for each table
            schema_parts = []
            for table in table_names:
                try:
                    schema_part = self._fetch_table_schema(table)
                    if schema_part:
                        schema_parts.append(schema_part)
                except Exception as e:
                    # Continue with other tables if one fails
                    schema_parts.append(f"TABLE {table}: (error fetching schema: {str(e)})")

            # Format as compact string
            return "\n\n".join(schema_parts)

        except Exception as e:
            # Return empty string on error - optimization can continue without schema
            return f"Schema fetch error: {str(e)}"

    def _extract_table_names(self, sql: str) -> List[str]:
        """
        Extract table names from SQL query using sqlparse.

        Handles:
        - Simple SELECT FROM
        - JOINs (INNER, LEFT, RIGHT, FULL)
        - Subqueries
        - CTEs (WITH clauses)
        - Schema-qualified names (public.users -> users)

        Args:
            sql: SQL query string

        Returns:
            List of unique table names (without schema prefix)
        """
        try:
            # Parse SQL
            parsed = sqlparse.parse(sql)
            if not parsed:
                return []

            tables: Set[str] = set()

            # Process each statement
            for statement in parsed:
                tables.update(self._extract_from_statement(statement))

            # Return as sorted list (deterministic order for testing)
            return sorted(list(tables))

        except Exception:
            # If parsing fails, return empty list
            return []

    def _extract_from_statement(self, statement) -> Set[str]:
        """
        Extract table names from a single SQL statement.

        Args:
            statement: sqlparse Statement object

        Returns:
            Set of table names
        """
        tables: Set[str] = set()
        from_seen = False

        for token in statement.tokens:
            # Skip whitespace and newlines
            if token.is_whitespace:
                continue

            # Handle CTEs (WITH clause)
            if token.ttype is Keyword and token.value.upper() == 'WITH':
                # Extract tables from CTE definitions
                tables.update(self._extract_from_cte(statement))

            # Look for FROM keyword
            if token.ttype is Keyword and token.value.upper() == 'FROM':
                from_seen = True
                continue

            # Look for JOIN keywords
            if token.ttype is Keyword and 'JOIN' in token.value.upper():
                from_seen = True
                continue

            # Extract identifiers after FROM or JOIN
            if from_seen:
                # Check if this is a keyword that ends the FROM clause
                if token.ttype is Keyword and token.value.upper() in ('WHERE', 'GROUP', 'ORDER', 'LIMIT', 'HAVING', 'UNION'):
                    from_seen = False
                    continue

                if isinstance(token, IdentifierList):
                    for identifier in token.get_identifiers():
                        table = self._extract_table_name(identifier)
                        if table:
                            tables.add(table)
                    from_seen = False
                elif isinstance(token, Identifier):
                    table = self._extract_table_name(token)
                    if table:
                        tables.add(table)
                    from_seen = False
                elif token.ttype is None and not token.is_group:
                    # Plain token (simple table name without alias)
                    table = self._clean_table_name(token.value)
                    if table and not self._is_keyword(table):
                        tables.add(table)
                        from_seen = False

            # Handle subqueries recursively
            if token.is_group:
                tables.update(self._extract_from_statement(token))

        return tables

    def _extract_from_cte(self, statement) -> Set[str]:
        """
        Extract table names from CTE (WITH clause).

        Args:
            statement: sqlparse Statement object

        Returns:
            Set of table names from CTE definitions
        """
        tables: Set[str] = set()

        # Find the WITH clause and extract tables from its subqueries
        for token in statement.tokens:
            if token.is_group:
                # Recursively extract from nested groups
                tables.update(self._extract_from_statement(token))

        return tables

    def _extract_table_name(self, identifier) -> Optional[str]:
        """
        Extract clean table name from identifier.

        Args:
            identifier: sqlparse Identifier object

        Returns:
            Clean table name without schema prefix or alias
        """
        # Get the real name (first part before alias)
        name = identifier.get_real_name()

        if not name:
            # Fallback to full value
            name = str(identifier.get_name())

        return self._clean_table_name(name)

    def _clean_table_name(self, name: str) -> Optional[str]:
        """
        Clean table name by removing schema prefix, quotes, etc.

        Args:
            name: Raw table name string

        Returns:
            Cleaned table name or None if invalid
        """
        if not name:
            return None

        # Remove quotes
        name = name.strip('"').strip("'").strip('`')

        # Remove schema prefix (public.users -> users)
        if '.' in name:
            parts = name.split('.')
            name = parts[-1]  # Take last part

        # Remove whitespace
        name = name.strip()

        # Filter out SQL keywords and empty strings
        if not name or self._is_keyword(name):
            return None

        return name

    def _is_keyword(self, word: str) -> bool:
        """
        Check if word is a SQL keyword.

        Args:
            word: Word to check

        Returns:
            True if word is a SQL keyword
        """
        keywords = {
            'SELECT', 'FROM', 'WHERE', 'JOIN', 'INNER', 'LEFT', 'RIGHT', 'FULL',
            'OUTER', 'ON', 'AS', 'AND', 'OR', 'NOT', 'NULL', 'TRUE', 'FALSE',
            'ORDER', 'BY', 'GROUP', 'HAVING', 'LIMIT', 'OFFSET', 'UNION', 'ALL',
            'DISTINCT', 'CASE', 'WHEN', 'THEN', 'ELSE', 'END', 'WITH'
        }
        return word.upper() in keywords

    def _fetch_table_schema(self, table_name: str) -> str:
        """
        Fetch schema for a single table from PostgreSQL.

        Fetches:
        - Column names and data types
        - Existing indexes
        - Foreign key relationships

        Args:
            table_name: Name of table to fetch schema for

        Returns:
            Formatted schema string in minimal format
        """
        try:
            conn = psycopg2.connect(self.db_connection)

            with conn:
                with conn.cursor() as cur:
                    # Fetch columns
                    columns = self._fetch_columns(cur, table_name)

                    # Fetch indexes
                    indexes = self._fetch_indexes(cur, table_name)

                    # Fetch foreign keys
                    foreign_keys = self._fetch_foreign_keys(cur, table_name)

            conn.close()

            # Format schema in minimal representation
            return self._format_schema(table_name, columns, indexes, foreign_keys)

        except Exception as e:
            # Return minimal error info
            return f"TABLE {table_name}: (error: {str(e)})"

    def _fetch_columns(self, cursor, table_name: str) -> List[tuple]:
        """
        Fetch column information from information_schema.

        Args:
            cursor: psycopg2 cursor
            table_name: Table name

        Returns:
            List of (column_name, data_type, is_nullable, full_type) tuples
        """
        query = """
            SELECT
                c.column_name,
                c.data_type,
                c.is_nullable,
                CASE
                    WHEN c.character_maximum_length IS NOT NULL
                    THEN c.data_type || '(' || c.character_maximum_length || ')'
                    WHEN c.numeric_precision IS NOT NULL
                    THEN c.data_type || '(' || c.numeric_precision ||
                         COALESCE(',' || c.numeric_scale, '') || ')'
                    ELSE c.data_type
                END as full_type
            FROM information_schema.columns c
            WHERE c.table_schema = %s
              AND c.table_name = %s
            ORDER BY c.ordinal_position;
        """

        cursor.execute(query, (self.schema, table_name))
        return cursor.fetchall()

    def _fetch_indexes(self, cursor, table_name: str) -> List[tuple]:
        """
        Fetch index information from pg_indexes.

        Args:
            cursor: psycopg2 cursor
            table_name: Table name

        Returns:
            List of (index_name, index_definition) tuples
        """
        query = """
            SELECT
                indexname,
                indexdef
            FROM pg_indexes
            WHERE schemaname = %s
              AND tablename = %s
            ORDER BY indexname;
        """

        cursor.execute(query, (self.schema, table_name))
        return cursor.fetchall()

    def _fetch_foreign_keys(self, cursor, table_name: str) -> List[tuple]:
        """
        Fetch foreign key relationships from information_schema.

        Args:
            cursor: psycopg2 cursor
            table_name: Table name

        Returns:
            List of (column_name, referenced_table, referenced_column) tuples
        """
        query = """
            SELECT
                kcu.column_name,
                rel_tco.table_name AS referenced_table,
                rel_kcu.column_name AS referenced_column
            FROM information_schema.table_constraints tco
            JOIN information_schema.key_column_usage kcu
              ON tco.constraint_name = kcu.constraint_name
              AND tco.table_schema = kcu.table_schema
            JOIN information_schema.referential_constraints rco
              ON tco.constraint_name = rco.constraint_name
              AND tco.table_schema = rco.constraint_schema
            JOIN information_schema.table_constraints rel_tco
              ON rco.unique_constraint_name = rel_tco.constraint_name
              AND rco.unique_constraint_schema = rel_tco.table_schema
            JOIN information_schema.key_column_usage rel_kcu
              ON rel_tco.constraint_name = rel_kcu.constraint_name
              AND rel_tco.table_schema = rel_kcu.table_schema
            WHERE tco.constraint_type = 'FOREIGN KEY'
              AND kcu.table_schema = %s
              AND kcu.table_name = %s
            ORDER BY kcu.column_name;
        """

        cursor.execute(query, (self.schema, table_name))
        return cursor.fetchall()

    def _format_schema(
        self,
        table_name: str,
        columns: List[tuple],
        indexes: List[tuple],
        foreign_keys: List[tuple]
    ) -> str:
        """
        Format schema in minimal representation for LLM.

        Format:
        TABLE table_name:
          column1: type, column2: type, column3: type
        INDEXES:
          idx_name ON (column)
        FOREIGN KEYS:
          fk_column -> referenced_table(referenced_column)

        Args:
            table_name: Table name
            columns: List of column tuples
            indexes: List of index tuples
            foreign_keys: List of foreign key tuples

        Returns:
            Formatted schema string
        """
        parts = []

        # Table and columns (compact single-line format)
        if columns:
            col_strs = []
            for col_name, data_type, is_nullable, full_type in columns:
                # Use short type representation
                type_str = self._shorten_type(full_type or data_type)
                col_strs.append(f"{col_name}: {type_str}")

            parts.append(f"TABLE {table_name}:")
            parts.append(f"  {', '.join(col_strs)}")
        else:
            parts.append(f"TABLE {table_name}:")
            parts.append(f"  (no columns found)")

        # Indexes (compact format)
        if indexes:
            parts.append("INDEXES:")
            for idx_name, idx_def in indexes:
                # Extract just the indexed columns from definition
                # "CREATE INDEX idx_name ON table(col)" -> "idx_name ON (col)"
                if 'ON' in idx_def:
                    # Simple extraction: take part after "ON table_name"
                    try:
                        on_part = idx_def.split(' ON ')[1]
                        # Remove schema prefix if present
                        if '(' in on_part:
                            on_part = on_part[on_part.index('('):]
                        parts.append(f"  {idx_name} ON {on_part}")
                    except:
                        # Fallback to index name only
                        parts.append(f"  {idx_name}")
                else:
                    parts.append(f"  {idx_name}")
        else:
            parts.append("INDEXES: None")

        # Foreign keys
        if foreign_keys:
            parts.append("FOREIGN KEYS:")
            for fk_col, ref_table, ref_col in foreign_keys:
                parts.append(f"  {fk_col} -> {ref_table}({ref_col})")
        else:
            parts.append("FOREIGN KEYS: None")

        return "\n".join(parts)

    def _shorten_type(self, type_str: str) -> str:
        """
        Shorten PostgreSQL type names for compact representation.

        Args:
            type_str: Full type string

        Returns:
            Shortened type string
        """
        # Map verbose types to short versions
        type_map = {
            'integer': 'int',
            'bigint': 'bigint',
            'smallint': 'smallint',
            'character varying': 'varchar',
            'timestamp without time zone': 'timestamp',
            'timestamp with time zone': 'timestamptz',
            'double precision': 'float8',
            'real': 'float4',
        }

        # Check for exact match
        for long_type, short_type in type_map.items():
            if type_str.startswith(long_type):
                # Preserve length specifiers: character varying(255) -> varchar(255)
                return type_str.replace(long_type, short_type)

        return type_str
