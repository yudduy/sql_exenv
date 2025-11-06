import os
import sys
import time
import random
import string
import pytest
import psycopg2
import asyncio

# Ensure src on path
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from agentic_dba.mcp_server import QueryOptimizationTool


def _rand_suffix(n: int = 6) -> str:
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=n))


def _skip_if_no_db():
    db = os.getenv("TEST_DB_URL")
    if not db:
        pytest.skip("TEST_DB_URL not set; skipping DB integration tests")
    return db


@pytest.mark.integration
def test_dry_run_plan_present_without_analyze():
    db = _skip_if_no_db()
    tool = QueryOptimizationTool(use_mock_translator=True)

    # Force ANALYZE to be skipped by setting analyze_cost_threshold to 0
    constraints = {
        "max_cost": 1000.0,
        "analyze_cost_threshold": 0.0,
    }
    result = asyncio.run(
        tool.optimize_query(
            sql_query="SELECT 1",
            db_connection_string=db,
            constraints=constraints,
        )
    )

    assert result["success"] is True
    assert "explain_plan_dry" in result
    assert "explain_plan" in result
    # With threshold=0, we should not have an analyze plan
    assert "explain_plan_analyze" not in result


@pytest.mark.integration
def test_hypopg_proof_block_present_when_index_suggested():
    db = _skip_if_no_db()

    # Check HypoPG availability; skip if not creatable
    try:
        conn = psycopg2.connect(db)
        cur = conn.cursor()
        cur.execute("CREATE EXTENSION IF NOT EXISTS hypopg")
        conn.commit()
    except Exception:
        pytest.skip("HypoPG extension not available or insufficient privileges")
    finally:
        try:
            conn.close()
        except Exception:
            pass

    # Create a small table to trigger Seq Scan and filter; keep rows small but lower threshold
    tbl = f"exev_test_{_rand_suffix()}"
    try:
        conn = psycopg2.connect(db)
        cur = conn.cursor()
        cur.execute(f"CREATE TABLE {tbl} (id int, email text)")
        cur.execute(f"INSERT INTO {tbl} VALUES (1, 'a'), (2, 'b'), (3, 'c')")
        conn.commit()

        tool = QueryOptimizationTool(
            use_mock_translator=True,
            analyzer_thresholds={"seq_scan_min_rows": 1}
        )
        result = asyncio.run(
            tool.optimize_query(
                sql_query=f"SELECT * FROM {tbl} WHERE email='a'",
                db_connection_string=db,
                constraints={"use_hypopg": True, "max_time_ms": 5000},
            )
        )

        assert result["success"] is True
        # We only assert that proof block exists; actual improvement may be zero on tiny tables
        assert "hypopg_proof" in result
        proof = result["hypopg_proof"]
        assert "before_cost" in proof and "after_cost" in proof

    finally:
        try:
            cur.execute(f"DROP TABLE IF EXISTS {tbl}")
            conn.commit()
            conn.close()
        except Exception:
            pass
