#!/bin/bash
set -e

export TEST_DB_URL="postgresql:///tpch_test?host=/tmp"
export ANTHROPIC_API_KEY="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"

echo "=== Running test 06 query directly ==="
python3 exev.py \
  -q "SELECT * FROM lineitem ORDER BY l_comment LIMIT 100;" \
  -d "$TEST_DB_URL" \
  --real \
  -o verify_06.json

echo ""
echo "=== Model 1 Bottlenecks ===" 
python3 -c "
import json
d = json.load(open('verify_06.json'))
for i, b in enumerate(d['technical_analysis']['bottlenecks'][:3], 1):
    print(f\"{i}. [{b['severity']}] {b['node_type']} on {b.get('table', 'N/A')}")
    print(f\"   {b['suggestion']}\")
"

echo ""
echo "=== Model 2 Final Suggestion ==="
python3 -c "
import json
d = json.load(open('verify_06.json'))
print(d['feedback']['suggestion'])
"

echo ""
echo "=== Check for 'l_comment' in suggestion ==="
python3 -c "
import json
d = json.load(open('verify_06.json'))
suggestion = d['feedback']['suggestion']
has_l_comment = 'l_comment' in suggestion
has_lineitem = 'lineitem' in suggestion
print(f'Has l_comment: {has_l_comment}')
print(f'Has lineitem: {has_lineitem}')
if has_l_comment and has_lineitem:
    print('✅ TEST 06 WOULD PASS')
else:
    print('❌ TEST 06 WOULD FAIL')
"
