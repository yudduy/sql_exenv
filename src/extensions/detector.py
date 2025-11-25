"""Extension detection for PostgreSQL.

Detects available extensions to enable conditional features like hypopg
for virtual index testing.
"""

import psycopg2
from typing import Dict, Optional


class ExtensionDetector:
    """Detect available PostgreSQL extensions."""

    # Only include extensions we actually use
    SUPPORTED_EXTENSIONS = ["hypopg"]

    def detect(self, connection_string: str) -> Dict[str, Optional[str]]:
        """
        Check which extensions are available and loaded.

        Returns dict of extension_name -> version (or None if not installed/loaded).
        Handles permission errors gracefully by returning empty dict.
        """
        extensions: Dict[str, Optional[str]] = {}

        try:
            conn = psycopg2.connect(connection_string)
        except Exception:
            # Can't connect - return empty (no extensions available)
            return extensions

        try:
            with conn.cursor() as cur:
                # Check which extensions are available
                try:
                    cur.execute("""
                        SELECT name, installed_version
                        FROM pg_available_extensions
                        WHERE name = ANY(%s)
                    """, (self.SUPPORTED_EXTENSIONS,))

                    for name, version in cur.fetchall():
                        extensions[name] = version
                except Exception:
                    # Permission denied or table doesn't exist
                    # Default to no extensions found
                    pass

                # Verify hypopg is actually usable (not just installed)
                if extensions.get("hypopg"):
                    try:
                        cur.execute("SELECT hypopg_reset()")
                    except Exception:
                        # Extension installed but not loaded
                        extensions["hypopg"] = None
        finally:
            conn.close()

        return extensions

    def has_hypopg(self, extensions: Dict[str, Optional[str]]) -> bool:
        """Check if hypopg is available and loaded."""
        return extensions.get("hypopg") is not None
