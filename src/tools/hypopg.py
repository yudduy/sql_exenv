"""Hypothetical index testing via hypopg extension.

Allows testing index effectiveness without creating real indexes.
Turns 10-minute blocking operations into 10ms CPU checks.
"""

import psycopg2
from dataclasses import dataclass
from typing import Optional, Dict, Any, List


@dataclass
class HypoIndexResult:
    """Result of testing a hypothetical index."""

    index_def: str
    would_be_used: bool
    cost_before: float
    cost_after: float
    improvement_pct: float
    plan_snippet: str  # Relevant part of EXPLAIN showing index usage
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "index_def": self.index_def,
            "would_be_used": self.would_be_used,
            "cost_before": self.cost_before,
            "cost_after": self.cost_after,
            "improvement_pct": self.improvement_pct,
            "plan_snippet": self.plan_snippet,
            "error": self.error,
        }


class HypoPGTool:
    """Test indexes without creating them using hypopg extension."""

    # Minimum improvement threshold to consider index worthwhile
    MIN_IMPROVEMENT_PCT = 10.0

    def __init__(self, connection_string: str):
        self.connection_string = connection_string

    def test_index(self, query: str, index_def: str) -> HypoIndexResult:
        """
        Test if a proposed index would be used and its impact.

        Args:
            query: The SQL query to optimize
            index_def: CREATE INDEX statement to test

        Returns:
            HypoIndexResult with cost comparison and usage info
        """
        try:
            conn = psycopg2.connect(self.connection_string)
        except Exception as e:
            return HypoIndexResult(
                index_def=index_def,
                would_be_used=False,
                cost_before=0,
                cost_after=0,
                improvement_pct=0,
                plan_snippet="",
                error=f"Connection failed: {e}",
            )

        hypo_oid = None
        try:
            with conn.cursor() as cur:
                # Get baseline cost
                cur.execute(f"EXPLAIN (FORMAT JSON) {query}")
                baseline = cur.fetchone()[0][0]
                cost_before = baseline["Plan"]["Total Cost"]

                # Create hypothetical index
                cur.execute(f"SELECT * FROM hypopg_create_index($${index_def}$$)")
                result = cur.fetchone()
                if result:
                    hypo_oid = result[0]
                else:
                    return HypoIndexResult(
                        index_def=index_def,
                        would_be_used=False,
                        cost_before=cost_before,
                        cost_after=cost_before,
                        improvement_pct=0,
                        plan_snippet="",
                        error="Failed to create hypothetical index",
                    )

                # Get cost with hypothetical index
                cur.execute(f"EXPLAIN (FORMAT JSON) {query}")
                with_index = cur.fetchone()[0][0]
                cost_after = with_index["Plan"]["Total Cost"]

                # Check if index is used (look for hypopg index reference)
                plan_str = str(with_index)
                would_be_used = "hypo" in plan_str.lower()

                # Extract relevant plan snippet
                plan_snippet = self._extract_index_usage(with_index)

                # Calculate improvement
                if cost_before > 0:
                    improvement = ((cost_before - cost_after) / cost_before) * 100
                else:
                    improvement = 0

                return HypoIndexResult(
                    index_def=index_def,
                    would_be_used=would_be_used,
                    cost_before=cost_before,
                    cost_after=cost_after,
                    improvement_pct=improvement,
                    plan_snippet=plan_snippet,
                )

        except Exception as e:
            return HypoIndexResult(
                index_def=index_def,
                would_be_used=False,
                cost_before=0,
                cost_after=0,
                improvement_pct=0,
                plan_snippet="",
                error=str(e),
            )
        finally:
            # Always clean up hypothetical index
            if hypo_oid is not None:
                try:
                    with conn.cursor() as cur:
                        cur.execute(f"SELECT hypopg_drop_index({hypo_oid})")
                except Exception:
                    pass  # Best effort cleanup
            conn.close()

    def is_worthwhile(self, result: HypoIndexResult) -> bool:
        """Check if the index test result indicates worthwhile improvement."""
        return (
            result.error is None
            and result.would_be_used
            and result.improvement_pct >= self.MIN_IMPROVEMENT_PCT
        )

    def _extract_index_usage(self, plan: dict) -> str:
        """Extract the part of the plan showing index usage."""
        nodes = self._find_index_nodes(plan.get("Plan", {}))
        return "; ".join(nodes) if nodes else "No index usage detected"

    def _find_index_nodes(self, node: dict, results: Optional[List[str]] = None) -> List[str]:
        """Recursively find index-related nodes in the plan."""
        if results is None:
            results = []

        node_type = node.get("Node Type", "")
        if "Index" in node_type:
            index_name = node.get("Index Name", "N/A")
            results.append(f"{node_type}: {index_name}")

        # Recurse into child plans
        for child in node.get("Plans", []):
            self._find_index_nodes(child, results)

        return results

    def reset(self) -> bool:
        """Reset all hypothetical indexes. Returns True on success."""
        try:
            conn = psycopg2.connect(self.connection_string)
            with conn.cursor() as cur:
                cur.execute("SELECT hypopg_reset()")
            conn.close()
            return True
        except Exception:
            return False
