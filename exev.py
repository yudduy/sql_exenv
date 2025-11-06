#!/usr/bin/env python3
"""
exev: Production-style CLI for Agentic DBA optimization and proof

Usage:
  python exev.py \
    -q "SELECT * FROM users WHERE email='alice@example.com'" \
    -d postgresql://user:pass@localhost/db \
    --max-cost 1000 \
    --max-time-ms 60000 \
    --analyze-cost-threshold 10000000 \
    --use-hypopg

Notes:
- Uses MockTranslator by default (no API key needed). Pass --real to use real LLM.
- Prints a concise, production-style analysis with optional HypoPG proof.
"""

import argparse
import asyncio
import json
import os
import sys
from typing import Any, Dict

# Ensure src on path
ROOT = os.path.abspath(os.path.dirname(__file__))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from agentic_dba.mcp_server import QueryOptimizationTool


def fmt_cost(v: Any) -> str:
    try:
        return f"{float(v):,.2f}"
    except Exception:
        return str(v)


def fmt_pct(before: float, after: float) -> str:
    try:
        if before == 0:
            return "0.0%"
        delta = (after - before) / before * 100.0
        return f"{delta:.1f}%"
    except Exception:
        return "N/A"


async def run(args: argparse.Namespace) -> int:
    constraints: Dict[str, Any] = {}
    if args.max_cost is not None:
        constraints["max_cost"] = float(args.max_cost)
    if args.max_time_ms is not None:
        constraints["max_time_ms"] = int(args.max_time_ms)
    if args.analyze_cost_threshold is not None:
        constraints["analyze_cost_threshold"] = float(args.analyze_cost_threshold)
    if args.use_hypopg:
        constraints["use_hypopg"] = True

    tool = QueryOptimizationTool(use_mock_translator=not args.real)

    print("Analyzing Query...\n")
    result = await tool.optimize_query(
        sql_query=args.query,
        db_connection_string=args.db,
        constraints=constraints or {"max_cost": 1000.0},
    )

    print("[ANALYSIS COMPLETE]\n")
    if not result.get("success", False):
        fb = result.get("feedback", {})
        print(
            f"> Status:         ERROR ({fb.get('reason', result.get('error', 'Unknown error'))})"
        )
        return 1

    fb = result.get("feedback", {})
    tech = result.get("technical_analysis", {})
    total_cost = tech.get("total_cost")
    max_cost = constraints.get("max_cost")
    bottlenecks = tech.get("bottlenecks", [])
    top = bottlenecks[0] if bottlenecks else {}

    status = fb.get("status", "unknown").upper()
    reason = fb.get("reason", "")
    suggestion = fb.get("suggestion", "")

    status_line = f"> Status:         {status}"
    if total_cost is not None and max_cost is not None and status != "PASS":
        status_line += f" (Cost {fmt_cost(total_cost)} exceeds limit {fmt_cost(max_cost)})"
    print(status_line)

    bn_line = None
    if top:
        bn_line = f"> Bottleneck:     {top.get('node_type', 'Unknown')} on '{top.get('table', 'N/A')}'"
        if top.get("rows"):
            bn_line += f" ({top['rows']:,} rows)"
    print(bn_line or f"> Reason:         {reason}")

    print(f"> Suggestion:     {suggestion}\n")

    if args.use_hypopg and result.get("hypopg_proof"):
        proof = result["hypopg_proof"]
        print("Running HypoPG Proof...\n")
        print("[HYPOTHETICAL PROOF]\n")
        print(f"> Before Cost:    {fmt_cost(proof.get('before_cost'))}")
        print(f"> After Cost:     {fmt_cost(proof.get('after_cost'))}")
        print(f"> Improvement:    {fmt_pct(proof.get('before_cost', 0.0), proof.get('after_cost', 0.0))}\n")

        if args.output:
            out = {
                "explain_plan_dry": result.get("explain_plan_dry"),
                "explain_plan_after": proof.get("explain_plan_after"),
                "feedback": fb,
                "technical_analysis": tech,
            }
            with open(args.output, "w") as f:
                json.dump(out, f, indent=2)
            print(f"(View full plans in {args.output})")

    return 0


def main() -> None:
    p = argparse.ArgumentParser(description="Agentic DBA production CLI (exev)")
    p.add_argument("-q", "--query", required=True, help="SQL query to analyze")
    p.add_argument("-d", "--db", required=True, help="PostgreSQL connection string")
    p.add_argument("--max-cost", type=float, default=1000.0, help="Maximum acceptable plan cost")
    p.add_argument("--max-time-ms", type=int, default=60000, help="Statement timeout for ANALYZE")
    p.add_argument(
        "--analyze-cost-threshold",
        type=float,
        default=10_000_000.0,
        help="Only run ANALYZE if estimated cost is at or below this threshold",
    )
    p.add_argument("--use-hypopg", action="store_true", help="Run HypoPG proof step")
    p.add_argument("--real", action="store_true", help="Use real LLM translator (requires API key)")
    p.add_argument("-o", "--output", help="Write full JSON output to this file")

    args = p.parse_args()
    rc = asyncio.run(run(args))
    sys.exit(rc)


if __name__ == "__main__":
    main()
