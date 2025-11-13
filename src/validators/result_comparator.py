"""
Result set comparison utilities for metamorphic testing.

Provides functions to compare SQL query results with proper handling of:
- NULL values (NULL == NULL for comparison purposes)
- Floating point values (approximate equality)
- Column order normalization
- Duplicate rows (multiset semantics)

Based on SQLancer's comparison logic.
"""

from typing import List, Tuple, Any, Optional
from collections import Counter
import decimal


class ResultComparator:
    """
    Compares SQL result sets for equality in metamorphic testing.

    Uses multiset semantics (UNION ALL) rather than set semantics (UNION)
    to preserve duplicate rows as they appear in SQL results.
    """

    def __init__(self, float_tolerance: float = 1e-9):
        """
        Initialize comparator with floating point tolerance.

        Args:
            float_tolerance: Epsilon for floating point comparisons
        """
        self.float_tolerance = float_tolerance

    def compare_result_sets(
        self,
        rs1: List[Any],
        rs2: List[Any],
    ) -> bool:
        """
        Compare two result sets for equality.

        Args:
            rs1: First result set (list of rows)
            rs2: Second result set (list of rows)

        Returns:
            True if result sets are equal, False otherwise

        Example:
            ```python
            comparator = ResultComparator()
            rows1 = [(1, 'Alice'), (2, 'Bob')]
            rows2 = [(2, 'Bob'), (1, 'Alice')]
            assert comparator.compare_result_sets(rows1, rows2) == True
            ```
        """
        # Quick check: different lengths means different results
        if len(rs1) != len(rs2):
            return False

        # Empty result sets are equal
        if len(rs1) == 0:
            return True

        # Normalize both result sets for comparison
        normalized1 = self._normalize_result_set(rs1)
        normalized2 = self._normalize_result_set(rs2)

        # Compare as multisets (count occurrences of each row)
        return Counter(normalized1) == Counter(normalized2)

    def multiset_union(self, result_sets: List[List[Any]]) -> List[Any]:
        """
        Perform multiset union (UNION ALL) on result sets.

        Important: This is UNION ALL, not UNION. Duplicates are preserved.

        Args:
            result_sets: List of result sets to union

        Returns:
            Combined result set with all rows from all inputs

        Example:
            ```python
            comparator = ResultComparator()
            rs1 = [(1, 'A')]
            rs2 = [(1, 'A'), (2, 'B')]
            result = comparator.multiset_union([rs1, rs2])
            assert len(result) == 3  # Duplicates preserved
            ```
        """
        combined = []
        for rs in result_sets:
            combined.extend(rs)
        return combined

    def _normalize_result_set(self, rows: List[Any]) -> List[Tuple]:
        """
        Normalize result set for comparison.

        Converts rows to tuples with normalized values:
        - Floats rounded to tolerance
        - Decimals converted to float then rounded
        - NULLs preserved as None
        - Strings trimmed of whitespace

        Args:
            rows: List of rows (each row can be tuple, list, or dict-like)

        Returns:
            List of normalized tuples suitable for comparison
        """
        normalized = []

        for row in rows:
            normalized_row = []

            # Handle different row formats (tuple, list, asyncpg.Record, etc.)
            if hasattr(row, 'values'):
                # Dict-like or Record object
                values = row.values()
            elif hasattr(row, '__iter__') and not isinstance(row, (str, bytes)):
                # Tuple or list
                values = row
            else:
                # Single value
                values = [row]

            for value in values:
                normalized_value = self._normalize_value(value)
                normalized_row.append(normalized_value)

            normalized.append(tuple(normalized_row))

        return normalized

    def _normalize_value(self, value: Any) -> Any:
        """
        Normalize a single value for comparison.

        Args:
            value: Value to normalize

        Returns:
            Normalized value suitable for comparison
        """
        # NULL handling
        if value is None:
            return None

        # Float handling (approximate equality)
        if isinstance(value, float):
            # Round to tolerance for comparison
            return round(value / self.float_tolerance) * self.float_tolerance

        # Decimal handling (convert to float then round)
        if isinstance(value, decimal.Decimal):
            float_value = float(value)
            return round(float_value / self.float_tolerance) * self.float_tolerance

        # String handling (trim whitespace)
        if isinstance(value, str):
            return value.strip()

        # Bytes handling (keep as-is for now)
        if isinstance(value, bytes):
            return value

        # Boolean handling
        if isinstance(value, bool):
            return value

        # Integer handling
        if isinstance(value, int):
            return value

        # Default: return as-is
        return value

    def get_row_count_diff(
        self,
        rs1: List[Any],
        rs2: List[Any],
    ) -> int:
        """
        Get difference in row counts between two result sets.

        Args:
            rs1: First result set
            rs2: Second result set

        Returns:
            Absolute difference in row counts
        """
        return abs(len(rs1) - len(rs2))

    def find_mismatched_rows(
        self,
        rs1: List[Any],
        rs2: List[Any],
        max_examples: int = 5,
    ) -> Tuple[List[Tuple], List[Tuple]]:
        """
        Find rows that appear in one result set but not the other.

        Args:
            rs1: First result set
            rs2: Second result set
            max_examples: Maximum number of example mismatches to return

        Returns:
            Tuple of (rows only in rs1, rows only in rs2)
        """
        normalized1 = self._normalize_result_set(rs1)
        normalized2 = self._normalize_result_set(rs2)

        counter1 = Counter(normalized1)
        counter2 = Counter(normalized2)

        # Find rows unique to each set
        only_in_1 = []
        only_in_2 = []

        for row, count in counter1.items():
            diff = count - counter2.get(row, 0)
            if diff > 0:
                only_in_1.extend([row] * min(diff, max_examples - len(only_in_1)))
                if len(only_in_1) >= max_examples:
                    break

        for row, count in counter2.items():
            diff = count - counter1.get(row, 0)
            if diff > 0:
                only_in_2.extend([row] * min(diff, max_examples - len(only_in_2)))
                if len(only_in_2) >= max_examples:
                    break

        return only_in_1[:max_examples], only_in_2[:max_examples]


# Example usage
if __name__ == "__main__":
    # Example: Compare result sets with NULL and float values
    comparator = ResultComparator()

    # Test case 1: Identical results
    rs1 = [(1, 'Alice', 3.14159), (2, 'Bob', None)]
    rs2 = [(2, 'Bob', None), (1, 'Alice', 3.14159)]
    print(f"Test 1 (identical): {comparator.compare_result_sets(rs1, rs2)}")  # True

    # Test case 2: Different results
    rs3 = [(1, 'Alice'), (2, 'Bob')]
    rs4 = [(1, 'Alice'), (3, 'Charlie')]
    print(f"Test 2 (different): {comparator.compare_result_sets(rs3, rs4)}")  # False

    # Test case 3: Multiset union
    rs5 = [(1, 'A')]
    rs6 = [(1, 'A'), (2, 'B')]
    union = comparator.multiset_union([rs5, rs6])
    print(f"Test 3 (union): {len(union)} rows")  # 3 rows

    # Test case 4: Find mismatched rows
    only1, only2 = comparator.find_mismatched_rows(rs3, rs4)
    print(f"Test 4 (mismatches): only in rs3={only1}, only in rs4={only2}")
