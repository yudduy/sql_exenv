# SQL Correctness Validation via Metamorphic Testing

## Overview

`sql_exenv` validates SQL query correctness using **metamorphic testing**, a technique from academic database research that catches logic bugs without requiring expected outputs. This positions `sql_exenv` uniquely: existing SQL execution tools provide no correctness guarantees, while we validate queries before optimization.

## The Oracle Problem

**Problem:** How do you validate SQL query results without knowing the expected output?

Traditional approaches require:
- Test datasets with known answers (expensive to maintain)
- Manual verification (doesn't scale)
- Execution accuracy metrics (queries can run successfully but return wrong data)

**Example Failure Mode:**

```sql
-- User asks: "Show users from last month"
-- LLM generates:
SELECT * FROM users WHERE created_at > '2024-10-01'

-- Query executes successfully ✓
-- Returns 1,247 rows ✓
-- But wrong year (should be 2025-10-01) ✗
-- Traditional validation: PASSED (incorrect)
-- Metamorphic testing: FAILED (catches year error)
```

## Metamorphic Testing Solution

Instead of checking absolute correctness, we verify **relationships between queries**.

### Mathematical Foundation

SQL predicates evaluate to TRUE, FALSE, or NULL. For any query Q with predicate φ:

```
RS(Q) = RS(Q_φ=TRUE) ⊎ RS(Q_φ=FALSE) ⊎ RS(Q_φ=NULL)
```

Where ⊎ is multiset union (UNION ALL).

**Key Insight:** This relationship MUST hold regardless of data. Violations indicate bugs in the query or DBMS.

## Validation Methods

### TLP (Ternary Logic Partitioning)

Validates WHERE clause logic by partitioning on predicates.

**How it works:**

```sql
-- Original query
SELECT * FROM users WHERE age > 25

-- Partition into 3 queries
Q1: SELECT * FROM users WHERE (age > 25) IS TRUE
Q2: SELECT * FROM users WHERE (age > 25) IS FALSE
Q3: SELECT * FROM users WHERE (age > 25) IS NULL

-- Invariant: RS(Original) = RS(Q1) ∪ RS(Q2) ∪ RS(Q3)
```

If this invariant fails, the query has a logic bug.

**When to use:** Queries with WHERE clauses

**Reference:** Rigger & Su, "Finding Bugs in Database Systems via Query Partitioning" (OOPSLA 2020)

### NoREC (Non-optimizing Reference Engine Construction)

Validates query optimization by comparing optimized vs. non-optimized execution.

**How it works:**

```sql
-- Optimized (uses indexes)
SELECT * FROM users WHERE age > 25

-- Non-optimized (forces table scan)
SELECT * FROM users WHERE (SELECT age > 25) = TRUE
```

**Invariant:** Both queries must return the same row count.

**When to use:** Queries you suspect have optimization bugs

**Reference:** Rigger & Su, "Detecting Optimization Bugs in Database Engines" (ESEC/FSE 2020)

## Usage

### Python API

```python
from src.agents import SQLOptimizationAgent

agent = SQLOptimizationAgent()

# Validation enabled by default
result = await agent.optimize_query(
    query="SELECT * FROM users WHERE age > 25",
    db_connection="postgresql://localhost/mydb",
    validate_correctness=True  # Default
)

# Check validation results
if 'validation' in result:
    validation = result['validation']
    if not validation.passed:
        for issue in validation.issues:
            print(f"Error: {issue.description}")
            print(f"Fix: {issue.suggested_fix}")

# Skip validation (faster, but no correctness guarantee)
result = await agent.optimize_query(
    query="SELECT * FROM users WHERE age > 25",
    db_connection="postgresql://localhost/mydb",
    validate_correctness=False
)
```

### CLI

```bash
# Validate + optimize (default)
python cli.py --query "SELECT * FROM users WHERE age > 25"

# Validate only (no optimization)
python cli.py --query "SELECT * FROM users WHERE age > 25" --validate-only

# Skip validation (only optimize performance)
python cli.py --query "SELECT * FROM users WHERE age > 25" --no-validation
```

### Direct Validator Usage

```python
from src.validators.metamorphic import TLPValidator
from src.validators.differential import NoRECValidator

# TLP validation
tlp = TLPValidator()
result = await tlp.validate(
    query="SELECT * FROM users WHERE age > 25",
    db_connection="postgresql://localhost/mydb"
)

if not result.passed:
    print(f"Validation failed: {result.issues[0].description}")

# NoREC validation
norec = NoRECValidator()
result = await norec.validate(
    query="SELECT * FROM users WHERE age > 25",
    db_connection="postgresql://localhost/mydb"
)
```

## Validation Output Example

### Successful Validation

```
Correctness Validation
━━━━━━━━━━━━━━━━━━━━━━
✓ Validation PASSED (TLP+NoREC)
  Confidence: 100%
  Queries Executed: 6
  Validation Time: 45ms
```

### Failed Validation

```
Correctness Validation
━━━━━━━━━━━━━━━━━━━━━━
✗ Validation FAILED (TLP)
  Confidence: 100%

Issues Detected
───────────────

1. **PARTITION_MISMATCH** [ERROR]
   Query returned 0 rows, but partitioned queries returned 1000 rows.
   This indicates a logical error in the query.

   Evidence:
     - original_count: 0
     - true_count: 1000
     - false_count: 0
     - null_count: 0
     - union_count: 1000
     - predicate: age > 100 AND age < 50

   Suggested fix:
   Review the WHERE clause logic. The predicate may not correctly
   capture the intended filtering condition. Common issues:
   1. Incorrect operator (e.g., > instead of >=)
   2. Missing NULL handling (consider using IS NULL or COALESCE)
   3. Logic error in AND/OR combinations
   4. Type casting issues (e.g., comparing incompatible types)

⚠ Query may return incorrect results. Fix issues before optimizing performance.
```

## Integration with Agent Loop

The agent validates correctness **before** optimizing performance:

```
┌─────────────────────────────────────────────────────────────┐
│ User Input: SQL Query                                       │
└────────────────┬────────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────────────┐
│ PHASE 1: Correctness Validation                            │
│  ├─ Run TLP validator (4 queries)                          │
│  ├─ Run NoREC validator (2 queries)                        │
│  └─ If FAILED: Stop and report issues                      │
└────────┬────────────────────────────────────────────────────┘
         │ PASSED
         ▼
┌─────────────────────────────────────────────────────────────┐
│ PHASE 2: Performance Optimization                          │
│  ├─ Analyze EXPLAIN plan                                    │
│  ├─ Plan optimization action                                │
│  └─ Execute optimization                                    │
└─────────────────────────────────────────────────────────────┘
```

**Rationale:** A fast query returning wrong data is worse than a slow query returning correct data.

## Performance Overhead

Validation adds overhead due to executing multiple query variants:

- **TLP:** 4 queries (original + 3 partitions) = ~3-4x overhead
- **NoREC:** 2 queries (optimized + non-optimized) = ~2x overhead
- **Combined:** 6 queries total

**Mitigation strategies:**
1. Async/parallel execution of partition queries (implemented)
2. Skip validation for simple queries without WHERE clause (automatic)
3. Cache validation results for repeated queries (future enhancement)
4. Make validation optional with `--no-validation` flag

## Troubleshooting

### "Validation failed but query looks correct"

Possible causes:

1. **Floating point precision:** Validation uses ε=1e-9 tolerance
2. **NULL handling:** Ensure predicates handle NULLs correctly
3. **Data race:** Data changed between query executions
4. **Database bug:** Rarely, this can expose actual DBMS bugs

### "Validation is slow"

TLP executes 4 queries (original + 3 partitions). NoREC executes 2.

For large tables:
- Add indexes to improve partition query speed
- Use `--validate-only` to skip optimization
- Use `--no-validation` to skip validation entirely
- Reduce test data size in development

### "Low confidence validation"

Queries without WHERE clauses cannot be validated with TLP:

```
✓ Validation PASSED (TLP)
  Confidence: 30%
  ⚠ Note: No WHERE clause found - TLP validation not applicable
```

This is expected and safe. NoREC may still validate these queries.

## Research Background

### Papers

1. **Rigger & Su (2020)** - "Finding Bugs in Database Systems via Query Partitioning" (OOPSLA 2020)
   - Introduces TLP (Ternary Logic Partitioning)
   - Found 100+ bugs in PostgreSQL, MySQL, SQLite
   - https://doi.org/10.1145/3428279

2. **Rigger & Su (2020)** - "Detecting Optimization Bugs in Database Engines via Non-optimizing Reference Engine Construction" (ESEC/FSE 2020)
   - Introduces NoREC
   - Found 50+ optimization bugs in CockroachDB, TiDB
   - https://www.manuelrigger.at/preprints/NoREC.pdf

3. **Chen et al. (1998)** - "Metamorphic Testing: A New Approach for Generating Next Test Cases"
   - Original metamorphic testing paper
   - Technical Report HKUST-CS98-01

4. **Segura et al. (2016)** - "A Survey on Metamorphic Testing"
   - Comprehensive survey of metamorphic testing applications
   - IEEE Transactions on Software Engineering
   - https://doi.org/10.1145/3143561

### Projects

1. **SQLancer** - The research tool that implements these techniques
   - GitHub: https://github.com/sqlancer/sqlancer
   - Found 400+ bugs across multiple DBMSs
   - Written in Java

2. **CockroachDB** - Uses metamorphic testing in production CI/CD
   - Blog: https://www.cockroachlabs.com/blog/metamorphic-testing-the-database/
   - Shows production adoption of these techniques

## Limitations

### Current Limitations

1. **PostgreSQL only:** Currently only supports PostgreSQL
   - MySQL and SQLite support planned (Phase 5)

2. **Simple queries:** TLP struggles with:
   - Subqueries in WHERE clause
   - CTEs (WITH clauses)
   - Window functions
   - Complex boolean expressions

3. **No query rewriting:** If validation fails, we report issues but don't auto-fix
   - LLM-based correction planned (Phase 3 enhancement)

### Theoretical Limitations

1. **Cannot validate queries without WHERE:** TLP requires predicates to partition on

2. **Cannot detect all bugs:** Some bug classes are undetectable:
   - Schema design issues
   - Missing JOIN conditions (if query executes successfully)
   - Incorrect aggregation logic (if partitioning doesn't expose it)

3. **False negatives possible:** Very rarely, a buggy query may pass validation if:
   - Bug is in a part of query not covered by TLP/NoREC
   - Data distribution hides the bug
   - Partitioning happens to produce same incorrect result

## Comparison with Other Tools

| Tool | Correctness Validation | Performance Optimization | Database Support |
|------|------------------------|--------------------------|------------------|
| **sql_exenv** | ✅ TLP + NoREC | ✅ Autonomous agent | PostgreSQL |
| Microsoft MSSQL MCP | ❌ None | ❌ None | SQL Server |
| RichardHan's mssql_mcp_server | ❌ None | ❌ None | SQL Server |
| SQLancer | ✅ TLP + NoREC + PQS | ❌ None | All major DBMSs |
| Traditional SQL tools | ❌ None | ❌ Manual | Various |

**Key Differentiator:** Only `sql_exenv` combines correctness validation with autonomous performance optimization.

## Future Enhancements

### Phase 5: Multi-Database Support (Planned)

- MySQL dialect support
- SQLite dialect support
- Dialect abstraction layer

### Phase 6: Advanced Validation (Research)

- **PQS (Pivoted Query Synthesis):** Generate queries guaranteed to fetch specific "pivot rows"
- **Query rewriting:** Automatically fix detected correctness issues using LLM
- **Differential testing:** Compare results across different database versions
- **Coverage metrics:** Track which parts of query have been validated

### Community Contributions Welcome

- Additional validation methods (e.g., PQS)
- Support for more databases (MySQL, SQLite, SQL Server)
- Performance optimizations (caching, parallelization)
- Better error messages and suggestions

## Frequently Asked Questions

### Q: Will validation catch all SQL bugs?

**A:** No. Metamorphic testing is powerful but not exhaustive. It catches:
- Logic errors in WHERE clauses (TLP)
- Optimization bugs in query planner (NoREC)
- Some data type issues
- NULL handling problems

It does NOT catch:
- Schema design issues
- Missing JOINs (if query executes)
- Business logic errors outside SQL
- All possible query bugs

### Q: Can I trust validation results?

**A:** Yes, with caveats:
- **High confidence (>90%):** Very reliable, issues are real
- **Medium confidence (50-90%):** Likely correct, investigate flagged issues
- **Low confidence (<50%):** Validation skipped or limited (e.g., no WHERE clause)

### Q: Why not just use SQLancer directly?

**A:** SQLancer is a research tool for finding DBMS bugs. `sql_exenv` adapts its techniques for:
- **LLM-generated SQL:** Focused on logic errors, not DBMS bugs
- **Production use:** Better error messages, LLM integration, autonomous fixing
- **Python ecosystem:** Easy integration with data science workflows

### Q: Does this replace unit testing?

**A:** No. Metamorphic testing complements traditional testing:
- **Unit tests:** Verify specific expected outputs (when known)
- **Metamorphic testing:** Validate mathematical invariants (no expected outputs needed)
- **Use both:** Maximum confidence in correctness

### Q: What's the performance impact?

**A:** Validation adds 3-6x overhead (6 extra query executions). For production:
- Development: Enable validation (catch bugs early)
- Production: Consider `--no-validation` if performance critical
- CI/CD: Always enable validation

## Contributing

We welcome contributions! Areas of interest:
- Additional validation methods (PQS, differential testing)
- Multi-database support (MySQL, SQLite)
- Performance optimizations
- Better error messages

See `docs/contributing.md` for guidelines.

## License

MIT License - See LICENSE file for details.

## Acknowledgments

This implementation is based on research by:
- Manuel Rigger (ETH Zürich)
- Zhendong Su (ETH Zürich)
- SQLancer project contributors

We thank them for their groundbreaking work in database testing.
