#!/usr/bin/env python3
"""Debug script to test HypoPG functionality"""

import os
import sys
import psycopg2

TEST_DB_URL = os.getenv("TEST_DB_URL")
if not TEST_DB_URL:
    print("ERROR: TEST_DB_URL environment variable not set")
    sys.exit(1)

print(f"Connecting to: {TEST_DB_URL}\n")

try:
    conn = psycopg2.connect(TEST_DB_URL)
    conn.autocommit = True
    cursor = conn.cursor()
    
    # 1. Check if HypoPG extension exists
    print("1. Checking if hypopg extension exists...")
    cursor.execute("SELECT 1 FROM pg_extension WHERE extname='hypopg'")
    exists = cursor.fetchone()
    if exists:
        print("   ✓ hypopg extension is installed\n")
    else:
        print("   ✗ hypopg extension NOT found")
        print("   Attempting to create extension...")
        try:
            cursor.execute("CREATE EXTENSION hypopg")
            print("   ✓ hypopg extension created\n")
        except Exception as e:
            print(f"   ✗ Failed to create extension: {e}\n")
            sys.exit(1)
    
    # 2. Test hypopg_create_index with different DDL variants
    print("2. Testing hypopg_create_index()...")
    
    ddl_variants = [
        "CREATE INDEX ON public.orders(o_custkey, o_orderstatus)",
        "CREATE INDEX ON orders(o_custkey, o_orderstatus)",
        "CREATE INDEX ON public.orders USING btree (o_custkey, o_orderstatus)",
        "CREATE INDEX idx_test ON orders(o_custkey, o_orderstatus)",
    ]
    
    for i, ddl in enumerate(ddl_variants, 1):
        print(f"\n   Variant {i}: {ddl}")
        try:
            cursor.execute("SELECT hypopg_reset()")
            cursor.execute("SELECT hypopg_create_index(%s)", (ddl,))
            result = cursor.fetchone()
            print(f"   ✓ Success: {result}")
            
            # Check if it was actually created
            cursor.execute("SELECT count(*) FROM hypopg_list_indexes()")
            count = cursor.fetchone()[0]
            print(f"   ✓ Hypothetical indexes count: {count}")
            
            if count > 0:
                cursor.execute("SELECT indexrelid, indrelid::regclass::text, indexname FROM hypopg_list_indexes()")
                indexes = cursor.fetchall()
                print(f"   ✓ Created indexes: {indexes}")
                break
        except Exception as e:
            print(f"   ✗ Failed: {e}")
    
    # 3. Test EXPLAIN with hypothetical index
    print("\n3. Testing EXPLAIN with hypothetical index...")
    query = "SELECT * FROM orders WHERE o_custkey = 123 AND o_orderstatus = 'F'"
    
    # Before
    cursor.execute("SELECT hypopg_reset()")
    cursor.execute(f"EXPLAIN (FORMAT JSON) {query}")
    before_plan = cursor.fetchone()[0]
    before_cost = before_plan[0]['Plan']['Total Cost']
    print(f"   Before cost: {before_cost}")
    
    # Create hypothetical index
    cursor.execute("SELECT hypopg_create_index(%s)", ("CREATE INDEX ON public.orders(o_custkey, o_orderstatus)",))
    idx_result = cursor.fetchone()
    print(f"   Created index: {idx_result}")
    
    # After
    cursor.execute(f"EXPLAIN (FORMAT JSON) {query}")
    after_plan = cursor.fetchone()[0]
    after_cost = after_plan[0]['Plan']['Total Cost']
    print(f"   After cost:  {after_cost}")
    print(f"   Improvement: {((after_cost - before_cost) / before_cost * 100):.1f}%")
    
    if after_cost < before_cost:
        print("\n✓ HypoPG is working correctly!")
    else:
        print("\n✗ HypoPG index not being used by planner")
        print("\nAfter plan:")
        import json
        print(json.dumps(after_plan[0]['Plan'], indent=2))
    
    conn.close()
    
except Exception as e:
    print(f"\nERROR: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
