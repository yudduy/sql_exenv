# Detailed Analysis of 3 Smoke Test Failures

## Summary
- **Success Rate:** 70% (7/10 tasks)
- **Failures:** 3 tasks - All fixable with agent improvements
- **Potential:** Can reach 80-90% with targeted fixes

---

## Task 3: ALTER TYPE ENUM Modification (FIXABLE)

### Details
- **DB:** european_football_2
- **Category:** Management
- **Type:** Multi-statement DDL sequence

### Issue SQL (4 statements):
```sql
1. ALTER TYPE buildupplayspeedclass RENAME TO buildupplayspeedclass_old;
2. CREATE TYPE buildupplayspeedclass AS ENUM ('Slow', 'Balanced', 'Fast', 'Very Fast');
3. ALTER TABLE Team_Attributes ALTER COLUMN ... SET DATA TYPE buildupplayspeedclass ...;
4. DROP TYPE buildupplayspeedclass_old;
```

### What Happened
1. Preprocess SQL creates enum `buildupplayspeedclass_enum`
2. Agent receives issue_sql trying to rename `buildupplayspeedclass`
3. Conflict: Names don't match (buildupplayspeedclass vs buildupplayspeedclass_enum)
4. Agent tries ALTER TYPE but gets syntax error

### Root Cause
**Multi-Statement DDL Handling:** Agent currently optimizes queries one-at-a-time, but this task requires executing ALL 4 statements as a sequence.

### Fix Strategy (Medium Complexity)
```python
# In agent.py solve_task():
if len(current_queries) > 1 and task.category == "Management":
    # Management tasks with multiple statements: execute as batch
    print(f"Executing {len(current_queries)} DDL statements as sequence...")
    for idx, stmt in enumerate(current_queries, 1):
        try:
            await self._execute_ddl(stmt, db_connection_string)
            print(f"  ✓ Statement {idx}/{len(current_queries)}")
        except Exception as e:
            print(f"  ✗ Statement {idx} failed: {e}")
            # Continue or fail based on error type
```

**Expected Impact:** +10% success rate (affects ~20 multi-DDL tasks)

---

## Task 5: UPDATE...RETURNING with JOIN (FIXABLE)

### Details
- **DB:** debit_card_specializing
- **Category:** Management
- **Type:** PostgreSQL-specific syntax limitation

### Issue SQL:
```sql
UPDATE transactions_1k
SET Amount = 100
FROM ( SELECT TransactionID FROM transactions_1k ... FOR UPDATE ) sub
RETURNING transactions_1k.TransactionID, customers.Segment;
```

### What Happened
User wants to JOIN customers table in RETURNING clause, but:
1. Agent added `JOIN customers ON ...` 
2. PostgreSQL doesn't allow this syntax in UPDATE statements
3. Error: "invalid reference to FROM-clause entry"

### Root Cause
**PostgreSQL Limitation:** Cannot use explicit JOIN in UPDATE's FROM clause when RETURNING references the joined table.

### Correct Solution
```sql
-- Option 1: Use subquery in RETURNING
UPDATE transactions_1k t
SET Amount = 100
WHERE TransactionID IN (...)
RETURNING TransactionID, (SELECT Segment FROM customers WHERE CustomerID = t.CustomerID);

-- Option 2: Use CTE
WITH updated AS (
    UPDATE transactions_1k
    SET Amount = 100
    RETURNING TransactionID, CustomerID
)
SELECT u.TransactionID, c.Segment
FROM updated u
JOIN customers c ON u.CustomerID = c.CustomerID;
```

### Fix Strategy (Low Complexity)
Add PostgreSQL-specific pattern to agent's planning rules:

```python
# In _build_planning_prompt():
"""
PostgreSQL UPDATE...RETURNING Limitations:
- Cannot use explicit JOIN in FROM clause with RETURNING
- Solutions:
  1. Use subquery in RETURNING: (SELECT col FROM table WHERE ...)
  2. Use CTE: WITH updated AS (UPDATE ... RETURNING ...) SELECT ... FROM updated JOIN ...
"""
```

**Expected Impact:** +5% success rate (affects ~10 UPDATE...RETURNING tasks)

---

## Task 9: Aggregate in WHERE Clause (EASILY FIXABLE)

### Details
- **DB:** student_club
- **Category:** Query
- **Type:** Basic SQL syntax error

### Issue SQL:
```sql
WITH CTE AS (
    SELECT link_to_event, COUNT(link_to_member) AS count 
    FROM attendance 
    GROUP BY link_to_event
)
SELECT CTE.link_to_event, CTE.count AS new
FROM budget
JOIN CTE ON budget.link_to_event = CTE.link_to_event
WHERE budget.count != CTE.count;  -- ERROR: "count" is column from aggregation
```

### What Happened
- Query tries to use aggregate result in WHERE clause
- SQL requires HAVING for aggregate filters, or reference CTE column

### Root Cause
**Basic SQL Error:** Agent didn't detect that `budget.count` doesn't exist - should be `CTE.count`.

### Correct Solution
```sql
-- Fix: Reference CTE column correctly (no WHERE needed since comparing columns)
SELECT CTE.link_to_event, CTE.count AS new_count, budget.count AS old_count
FROM budget
JOIN CTE ON budget.link_to_event = CTE.link_to_event
WHERE budget.count != CTE.count;  -- This works if budget has 'count' column

-- OR if budget doesn't have count column, just comparing to CTE:
SELECT CTE.link_to_event, CTE.count
FROM CTE
WHERE CTE.count > 0;  -- This works since CTE.count is a column
```

### Fix Strategy (Very Low Complexity)
Add to correctness validation in `_analyze_query()`:

```python
# In _analyze_query():
if "aggregate functions are not allowed in WHERE" in str(error):
    return {
        "success": True,
        "feedback": {
            "status": "fail",
            "reason": "CRITICAL: Aggregate in WHERE clause. Use HAVING or reference CTE columns.",
            "suggestion": "REWRITE query: move aggregate to HAVING or fix column reference",
            "priority": "CRITICAL"
        }
    }
```

**Expected Impact:** +5% success rate (affects ~10 aggregate filter tasks)

---

## Overall Fix Priority

| Fix | Complexity | Impact | Tasks Affected | Priority |
|-----|-----------|--------|----------------|----------|
| **Multi-DDL Sequencing** | Medium | +10% | ~20 Management | HIGH |
| **Aggregate in WHERE** | Very Low | +5% | ~10 Query | HIGH |
| **UPDATE...RETURNING** | Low | +5% | ~10 Management | MEDIUM |

**Total Potential:** 70% → 90% success rate (+20 points)

---

## Implementation Plan

### Quick Wins (30 minutes)
1. Add aggregate-in-WHERE detection to correctness check
2. Add UPDATE...RETURNING pattern to planning prompt

### Medium Fix (1 hour)
3. Implement multi-statement DDL batch execution for Management tasks

### Expected Results After Fixes
- Current: 70% (7/10)
- After Quick Wins: 80% (8/10)  
- After Medium Fix: 90% (9/10)

**Final projected success on 200 tasks: 75-85% (150-170 tasks)**

---

## Recommendation

**Path 1: Fix now, then full eval**
- Implement 3 fixes (~1.5 hours)
- Re-run smoke test (expect 90%)
- Run full 200-task eval (expect 75-85%)
- **Cost:** +$1 smoke test + $20 full eval = $21 total

**Path 2: Run full eval now, fix later**
- Run 200 tasks with current 70% agent
- Analyze failures systematically
- Implement fixes for next iteration
- **Cost:** $20 now, potential $20 later = $40 total

**Recommendation:** **Path 1** - Fix now since issues are clear and fixes are straightforward.
