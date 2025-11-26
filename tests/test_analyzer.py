import json
import os
import sys

# Ensure src on path
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from analyzer import ExplainAnalyzer


def test_analyzer_parses_parallel_seq_scan_table_name():
    fixture = os.path.join(os.path.dirname(__file__), "fixtures", "gather_parallel_seq_scan.json")
    with open(fixture) as f:
        plan = json.load(f)

    analyzer = ExplainAnalyzer(custom_thresholds={"seq_scan_min_rows": 1, "seq_scan_min_cost": 1.0})
    result = analyzer.analyze(plan)

    assert result["bottlenecks"], "Analyzer failed to find any bottlenecks"

    b0 = result["bottlenecks"][0]
    assert b0["node_type"] == "Seq Scan"
    assert b0["table"] == "orders"

    sug = b0.get("suggestion", "")
    assert "orders" in sug
    assert "o_custkey" in sug
    assert "o_orderstatus" in sug
