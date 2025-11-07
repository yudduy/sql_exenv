"""
Model 1: PostgreSQL EXPLAIN Plan Analyzer

This module parses EXPLAIN JSON output and identifies performance bottlenecks
programmatically. It serves as the "technical analysis" layer that precedes
natural language translation (Model 2).
"""

import json
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
import re
try:
    import sqlparse
except Exception:
    sqlparse = None


class Severity(Enum):
    """Bottleneck severity levels."""
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


@dataclass
class Bottleneck:
    """Represents a detected performance bottleneck."""
    node_type: str
    severity: Severity
    reason: str
    suggestion: str
    cost: Optional[float] = None
    table: Optional[str] = None
    rows: Optional[int] = None
    cost_percentage: Optional[float] = None


class ExplainAnalyzer:
    """
    Analyzes PostgreSQL EXPLAIN plans to identify bottlenecks.
    
    Detection rules:
    - Sequential Scans on large tables (>10k rows)
    - High-cost nodes (>70% of total cost)
    - Severe planner estimate errors (actual/estimated > 5x)
    - Nested Loop Joins on large result sets
    - Sort operations spilling to disk
    """
    
    # Configuration thresholds
    THRESHOLDS = {
        'seq_scan_min_rows': 10000,
        'cost_significance_ratio': 0.7,
        'estimate_error_ratio': 5.0,
        'nested_loop_max_rows': 1000,
    }
    
    def __init__(self, custom_thresholds: Optional[Dict[str, float]] = None):
        """
        Initialize analyzer with optional custom thresholds.
        
        Args:
            custom_thresholds: Override default detection thresholds
        """
        if custom_thresholds:
            self.THRESHOLDS.update(custom_thresholds)
    
    def analyze(self, explain_output: str | dict) -> Dict[str, Any]:
        """
        Main analysis entry point.
        
        Args:
            explain_output: Either JSON string or parsed dict from EXPLAIN
        
        Returns:
            Analysis dict containing:
            - total_cost: Total query cost
            - execution_time_ms: Actual execution time
            - bottlenecks: List of Bottleneck objects
            - summary: Human-readable summary
        """
        # Parse if string
        if isinstance(explain_output, str):
            plan_data = json.loads(explain_output)
        else:
            plan_data = explain_output
        
        # Handle both list and dict formats
        if isinstance(plan_data, list):
            root = plan_data[0]
        else:
            root = plan_data
        
        # Extract top-level metrics
        plan = root['Plan']
        total_cost = plan.get('Total Cost', 0)
        execution_time = root.get('Execution Time', 0)
        planning_time = root.get('Planning Time', 0)
        
        # Traverse plan tree and collect bottlenecks
        bottlenecks = []
        self._traverse_plan(plan, total_cost, bottlenecks)
        
        # Sort by severity
        bottlenecks.sort(key=lambda b: (
            {'HIGH': 0, 'MEDIUM': 1, 'LOW': 2}[b.severity.value],
            -(b.cost or 0)
        ))
        
        return {
            'total_cost': total_cost,
            'execution_time_ms': execution_time,
            'planning_time_ms': planning_time,
            'bottlenecks': [self._bottleneck_to_dict(b) for b in bottlenecks],
            'summary': self._generate_summary(bottlenecks, total_cost),
            'optimization_priority': self._get_priority(bottlenecks)
        }
    
    def _traverse_plan(
        self,
        node: Dict,
        total_cost: float,
        bottlenecks: List[Bottleneck]
    ) -> None:
        """
        Recursively traverse plan tree and detect bottlenecks.
        
        Args:
            node: Current plan node
            total_cost: Total query cost (for percentage calculations)
            bottlenecks: List to append detected bottlenecks
        """
        node_type = node.get('Node Type', 'Unknown')

        if node_type in ('Gather', 'Gather Merge'):
            if 'Plans' in node:
                for child in node['Plans']:
                    self._traverse_plan(child, total_cost, bottlenecks)
            return

        # Detection Rule 1: Sequential Scans on large tables
        if node_type in ('Seq Scan', 'Parallel Seq Scan'):
            self._check_seq_scan(node, bottlenecks)

        # Detection Rule 2: High-cost nodes
        self._check_high_cost(node, total_cost, bottlenecks)
        
        # Detection Rule 3: Planner estimate errors
        self._check_estimate_error(node, bottlenecks)
        
        # Detection Rule 4: Nested Loop Joins on large sets
        if 'Nested Loop' in node_type:
            self._check_nested_loop(node, bottlenecks)

        # Join key index suggestions
        if 'Join' in node_type or 'Nested Loop' in node_type:
            self._check_join_indexes(node, bottlenecks)
        
        # Detection Rule 5: Sort operations
        if node_type == 'Sort':
            self._check_sort(node, bottlenecks)
        
        # Recurse into child plans
        if 'Plans' in node:
            for child in node['Plans']:
                self._traverse_plan(child, total_cost, bottlenecks)
    
    def _check_seq_scan(self, node: Dict, bottlenecks: List[Bottleneck]) -> None:
        """Detect problematic sequential scans."""
        table = node.get('Relation Name', 'unknown_table')
        rows_actual = node.get('Actual Rows', node.get('Plan Rows', 0))
        
        if rows_actual > self.THRESHOLDS['seq_scan_min_rows']:
            filter_str = node.get('Filter', '')
            cols, conj = self._extract_columns_from_filter(filter_str)
            if cols:
                if conj == 'AND' and len(cols) > 1:
                    idx_cols = ', '.join(cols)
                    suggestion = f'CREATE INDEX idx_{table}_composite ON {table}({idx_cols});'
                elif conj == 'OR' and len(cols) > 1:
                    parts = [f'CREATE INDEX idx_{table}_{c} ON {table}({c});' for c in cols]
                    suggestion = ' '.join(parts)
                else:
                    suggestion = f'CREATE INDEX idx_{table}_{cols[0]} ON {table}({cols[0]});'
            else:
                col = self._extract_column_from_filter(filter_str)
                suggestion = f'CREATE INDEX idx_{table}_{col} ON {table}({col});' if col else f'CREATE INDEX ON {table}(...);'

            bottlenecks.append(Bottleneck(
                node_type='Seq Scan',
                table=table,
                rows=rows_actual,
                cost=node.get('Total Cost'),
                severity=Severity.HIGH,
                reason=f'Sequential scan on {table} with {rows_actual:,} rows',
                suggestion=suggestion
            ))
    
    def _check_high_cost(
        self,
        node: Dict,
        total_cost: float,
        bottlenecks: List[Bottleneck]
    ) -> None:
        """Detect nodes consuming significant query cost."""
        node_type = node.get('Node Type', '')
        if node_type in ('Gather', 'Gather Merge'):
            return
        node_cost = node.get('Total Cost', 0)
        
        if total_cost > 0:
            cost_pct = (node_cost / total_cost)
            if cost_pct > self.THRESHOLDS['cost_significance_ratio']:
                bottlenecks.append(Bottleneck(
                    node_type=node.get('Node Type'),
                    cost=node_cost,
                    cost_percentage=cost_pct * 100,
                    severity=Severity.MEDIUM,
                    reason=f'Node accounts for {cost_pct*100:.1f}% of total query cost',
                    suggestion='Review this operation - it dominates query execution time'
                ))
    
    def _check_estimate_error(self, node: Dict, bottlenecks: List[Bottleneck]) -> None:
        """Detect severe planner estimate errors."""
        rows_estimated = node.get('Plan Rows', 0)
        rows_actual = node.get('Actual Rows', 0)
        
        if rows_estimated > 0 and rows_actual > 0:
            error_ratio = rows_actual / rows_estimated
            if error_ratio > self.THRESHOLDS['estimate_error_ratio']:
                bottlenecks.append(Bottleneck(
                    node_type=node.get('Node Type'),
                    severity=Severity.LOW,
                    reason=f'Planner underestimated rows by {error_ratio:.1f}x ({rows_estimated} est. → {rows_actual} actual)',
                    suggestion=f'Run ANALYZE on {node.get("Relation Name", "involved tables")}'
                ))
    
    def _check_nested_loop(self, node: Dict, bottlenecks: List[Bottleneck]) -> None:
        """Detect inefficient nested loop joins."""
        rows_actual = node.get('Actual Rows', 0)
        
        if rows_actual > self.THRESHOLDS['nested_loop_max_rows']:
            bottlenecks.append(Bottleneck(
                node_type='Nested Loop',
                rows=rows_actual,
                severity=Severity.MEDIUM,
                reason=f'Nested Loop on {rows_actual:,} rows - likely inefficient',
                suggestion='Consider adding indexes on join columns or forcing hash/merge join'
            ))
    
    def _check_sort(self, node: Dict, bottlenecks: List[Bottleneck]) -> None:
        """Detect sort operations, especially those spilling to disk."""
        sort_method = node.get('Sort Method', '')
        
        if 'external' in sort_method.lower() or 'disk' in sort_method.lower():
            bottlenecks.append(Bottleneck(
                node_type='Sort',
                severity=Severity.MEDIUM,
                reason='Sort operation spilled to disk',
                suggestion='Increase work_mem or add index on sort columns'
            ))

    def _check_join_indexes(self, node: Dict, bottlenecks: List[Bottleneck]) -> None:
        cond_text = node.get('Join Filter') or node.get('Hash Cond') or node.get('Merge Cond')
        if not cond_text:
            return
        plans = node.get('Plans') or []
        inner = plans[1] if isinstance(plans, list) and len(plans) >= 2 else (plans[0] if plans else None)
        if not inner:
            return
        inner_rel, inner_alias = self._find_base_relation(inner)
        if not inner_rel:
            return
        inner_cols = self._extract_columns_for_alias(cond_text, inner_alias)
        if not inner_cols:
            return
        if self._subtree_uses_index(inner):
            return
        idx_cols = ', '.join(inner_cols)
        bottlenecks.append(Bottleneck(
            node_type=node.get('Node Type'),
            table=inner_rel,
            severity=Severity.MEDIUM,
            reason='Join on columns likely benefits from index on inner relation',
            suggestion=f'CREATE INDEX idx_{inner_rel}_join ON {inner_rel}({idx_cols});'
        ))
    
    def _extract_column_from_filter(self, filter_str: str) -> str:
        """
        Simple heuristic to extract column name from filter condition.
        
        Example: "(email = 'test'::text)" -> "email"
        
        In production, use proper SQL parsing (e.g., sqlparse library).
        """
        if not filter_str:
            return 'id'
        parts = filter_str.replace('(', '').replace(')', '').split()
        if parts:
            return parts[0].strip('\'"')
        return 'id'

    def _extract_columns_from_filter(self, filter_str: str) -> Tuple[List[str], str]:
        if not filter_str:
            return ([], '')
        conj = 'AND' if ' AND ' in filter_str else ('OR' if ' OR ' in filter_str else '')
        cols: List[str] = []
        for m in re.finditer(r'([a-zA-Z_][\w\.]*)\s*=\s*', filter_str):
            col = m.group(1)
            if '.' in col:
                col = col.split('.')[-1]
            if col not in cols:
                cols.append(col)
        return (cols, conj)

    def _extract_columns_for_alias(self, cond_text: str, alias: Optional[str]) -> List[str]:
        if not cond_text:
            return []
        if alias:
            cols: List[str] = []
            for m in re.finditer(r'\b' + re.escape(alias) + r'\.([a-zA-Z_][\w]*)\b', cond_text):
                c = m.group(1)
                if c not in cols:
                    cols.append(c)
            return cols
        cols: List[str] = []
        for m in re.finditer(r'([a-zA-Z_][\w\.]*)\s*=\s*([a-zA-Z_][\w\.]*)', cond_text):
            left = m.group(1)
            if '.' in left:
                left = left.split('.')[-1]
            if left not in cols:
                cols.append(left)
        return cols

    def _find_base_relation(self, node: Dict) -> Tuple[Optional[str], Optional[str]]:
        if 'Relation Name' in node:
            return node.get('Relation Name'), node.get('Alias')
        for ch in node.get('Plans', []) or []:
            rel, al = self._find_base_relation(ch)
            if rel:
                return rel, al
        return None, None

    def _subtree_uses_index(self, node: Dict) -> bool:
        nt = node.get('Node Type', '')
        if 'Index Scan' in nt or 'Bitmap Index Scan' in nt or 'Index Only Scan' in nt:
            return True
        for ch in node.get('Plans', []) or []:
            if self._subtree_uses_index(ch):
                return True
        return False

    def _bottleneck_to_dict(self, bottleneck: Bottleneck) -> Dict:
        """Convert Bottleneck dataclass to dict for JSON serialization."""
        return {
            'node_type': bottleneck.node_type,
            'severity': bottleneck.severity.value,
            'reason': bottleneck.reason,
            'suggestion': bottleneck.suggestion,
            'cost': bottleneck.cost,
            'table': bottleneck.table,
            'rows': bottleneck.rows,
            'cost_percentage': bottleneck.cost_percentage
        }
    
    def _generate_summary(self, bottlenecks: List[Bottleneck], total_cost: float) -> str:
        """Generate human-readable summary of analysis."""
        if not bottlenecks:
            return f"No significant bottlenecks detected. Query cost: {total_cost:.2f}"
        
        high = [b for b in bottlenecks if b.severity == Severity.HIGH]
        medium = [b for b in bottlenecks if b.severity == Severity.MEDIUM]
        
        parts = []
        if high:
            parts.append(f"{len(high)} HIGH severity issue(s)")
        if medium:
            parts.append(f"{len(medium)} MEDIUM severity issue(s)")
        
        return f"Found {len(bottlenecks)} bottleneck(s): {', '.join(parts)}. Total cost: {total_cost:.2f}"
    
    def _get_priority(self, bottlenecks: List[Bottleneck]) -> str:
        """Determine overall optimization priority."""
        if not bottlenecks:
            return "LOW"
        if any(b.severity == Severity.HIGH for b in bottlenecks):
            return "HIGH"
        if any(b.severity == Severity.MEDIUM for b in bottlenecks):
            return "MEDIUM"
        return "LOW"


# Example usage
if __name__ == "__main__":
    # Sample EXPLAIN output (from real PostgreSQL)
    sample_explain = [{
        "Plan": {
            "Node Type": "Seq Scan",
            "Relation Name": "users",
            "Startup Cost": 0.00,
            "Total Cost": 55072.45,
            "Plan Rows": 100000,
            "Plan Width": 244,
            "Actual Startup Time": 0.015,
            "Actual Total Time": 245.123,
            "Actual Rows": 100000,
            "Actual Loops": 1,
            "Filter": "(email = 'test@example.com'::text)",
            "Rows Removed by Filter": 99999
        },
        "Planning Time": 0.123,
        "Execution Time": 245.456
    }]
    
    analyzer = ExplainAnalyzer()
    result = analyzer.analyze(sample_explain)
    
    print("Analysis Result:")
    print(json.dumps(result, indent=2))
