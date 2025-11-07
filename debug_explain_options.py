#!/usr/bin/env python3
"""Debug script to test different EXPLAIN options with HypoPG"""

import os
import sys
import psycopg2
import json

TEST_DB_URL = os.getenv("TEST_DB_URL")
if not TEST_DB_URL:
    print("ERROR: TEST_DB_URL environment variable not set")
    sys.exit(1)

query = "SELECT * FROM orders WHERE o_custkey = 123 AND o_orderstatus = 'F'"

try:
    conn = psycopg2.connect(TEST_DB_URL)
    conn.autocommit = True
    cursor = conn.cursor()
    
    # Reset and create hypothetical index
    cursor.execute("SELECT hypopg_reset()")
    cursor.execute("SELECT * FROM hypopg_create_index('CREATE INDEX ON public.orders(o_custkey, o_orderstatus)')")
    result = cursor.fetchone()
    print(f"Created index: {result}\n")
    
    # Check that index exists
    cursor.execute("SELECT * FROM hypopg()")
    indexes = cursor.fetchall()
    print(f"Hypothetical indexes: {indexes}\n")
    
    # Test 1: Simple EXPLAIN (like manual test)
    print("=" * 60)
    print("Test 1: Simple EXPLAIN (no options)")
    print("=" * 60)
    cursor.execute(f"EXPLAIN {query}")
    rows = cursor.fetchall()
    for row in rows:
        print(row[0])
    print()
    
    # Test 2: EXPLAIN with FORMAT JSON only
    print("=" * 60)
    print("Test 2: EXPLAIN (FORMAT JSON)")
    print("=" * 60)
    cursor.execute(f"EXPLAIN (FORMAT JSON) {query}")
    plan = cursor.fetchone()[0]
    cost = plan[0]['Plan']['Total Cost']
    print(f"Cost: {cost}")
    print(f"Node Type: {plan[0]['Plan']['Node Type']}")
    print()
    
    # Test 3: EXPLAIN with ANALYZE false explicitly
    print("=" * 60)
    print("Test 3: EXPLAIN (ANALYZE false, FORMAT JSON)")
    print("=" * 60)
    cursor.execute(f"EXPLAIN (ANALYZE false, FORMAT JSON) {query}")
    plan = cursor.fetchone()[0]
    cost = plan[0]['Plan']['Total Cost']
    print(f"Cost: {cost}")
    print(f"Node Type: {plan[0]['Plan']['Node Type']}")
    print()
    
    # Test 4: EXPLAIN with all our options
    print("=" * 60)
    print("Test 4: EXPLAIN (ANALYZE false, COSTS true, VERBOSE true, BUFFERS true, FORMAT JSON)")
    print("=" * 60)
    explain_query = f"""
    EXPLAIN (
        ANALYZE false,
        COSTS true,
        VERBOSE true,
        BUFFERS true,
        FORMAT JSON
    )
    {query}
    """
    cursor.execute(explain_query)
    plan = cursor.fetchone()[0]
    cost = plan[0]['Plan']['Total Cost']
    print(f"Cost: {cost}")
    print(f"Node Type: {plan[0]['Plan']['Node Type']}")
    print()
    
    # Test 5: Check if hypopg.enabled is on
    print("=" * 60)
    print("Test 5: Check hypopg.enabled setting")
    print("=" * 60)
    try:
        cursor.execute("SHOW hypopg.enabled")
        setting = cursor.fetchone()
        print(f"hypopg.enabled = {setting[0]}")
    except Exception as e:
        print(f"Could not check hypopg.enabled: {e}")
    
    conn.close()
    
except Exception as e:
    print(f"\nERROR: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
