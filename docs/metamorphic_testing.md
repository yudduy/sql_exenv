# SQL Correctness Validation

Technical documentation for metamorphic testing validators.

## Quick Reference

```python
from src.validators import TLPValidator, NoRECValidator

# TLP validation
tlp = TLPValidator()
result = await tlp.validate(
    query="SELECT * FROM users WHERE age > 25",
    db_connection="postgresql://localhost/mydb"
)

# NoREC validation
norec = NoRECValidator()
result = await norec.validate(query, db_connection)

# Check results
if not result.passed:
    for issue in result.issues:
        print(f"{issue.issue_type}: {issue.description}")
        print(f"Fix: {issue.suggested_fix}")
```

## How Validators Work

### TLP (Ternary Logic Partitioning)

Validates WHERE clauses using three-valued logic. The invariant:

```
RS(Q) = RS(Q_φ=TRUE) ⊎ RS(Q_φ=FALSE) ⊎ RS(Q_φ=NULL)
```

**Example:**
```sql
-- Original
SELECT * FROM users WHERE age > 25

-- Partitions (combined must equal original)
WHERE (age > 25) IS TRUE   -- Matches condition
WHERE (age > 25) IS FALSE  -- Doesn't match
WHERE (age > 25) IS NULL   -- NULL age values
```

**Limitations:**
- Requires WHERE clause
- Complex subqueries may not parse correctly
- Skips validation for queries without predicates (returns low confidence)

### NoREC (Non-optimizing Reference Engine)

Compares optimized vs non-optimized execution:

```sql
-- Optimized (may use indexes)
SELECT * FROM users WHERE age > 25

-- Non-optimized (forces table scan)
SELECT * FROM users WHERE (SELECT age > 25) = TRUE
```

Row counts must match. Differences indicate query planner bugs.

**Limitations:**
- Only checks row counts, not actual data
- May miss bugs that affect both queries identically

## Result Comparison

The `ResultComparator` handles:
- **NULL equality**: NULL == NULL for comparison
- **Float tolerance**: ε=1e-9 for approximate equality
- **Multiset semantics**: Preserves duplicates (UNION ALL)
- **Column order**: Normalizes before comparison

## Performance Impact

| Validator | Queries | Typical Overhead |
|-----------|---------|------------------|
| TLP | 4 (original + 3 partitions) | 3-4x |
| NoREC | 2 (optimized + non-optimized) | 2x |
| Combined | 6 | Up to 6x |

**Mitigation:**
- Validators run in parallel (async)
- Skip validation for simple queries (no WHERE)
- Use `validate_correctness=False` in production if needed

## Troubleshooting

**"PARTITION_MISMATCH error"**
```python
# Common causes:
# 1. Logic error in WHERE clause
WHERE age > 30 AND age < 25  # Impossible condition

# 2. Missing NULL handling
WHERE status = 'active'  # Misses NULL statuses
WHERE status = 'active' OR status IS NULL  # Fixed

# 3. Type coercion issues
WHERE price > '100'  # String comparison, not numeric
WHERE price > 100  # Fixed
```

**"OPTIMIZATION_BUG error"**
- Query planner incorrectly using an index
- Run `EXPLAIN` to see execution plan
- May indicate actual PostgreSQL bug (rare)
- Try query hints or rewriting

**"Low confidence validation"**
- Query has no WHERE clause (TLP not applicable)
- This is expected and safe
- NoREC may still validate these queries

## Integration with Agent

The agent validates correctness **before** optimizing:

```python
result = await agent.optimize_query(
    sql="SELECT * FROM users WHERE age > 25",
    db_connection="postgresql://localhost/mydb",
    validate_correctness=True  # Default
)

# Check validation
if 'validation' in result:
    print(f"Validated: {result['validation'].passed}")
    print(f"Method: {result['validation'].method}")
    print(f"Confidence: {result['validation'].confidence}")
```

If validation fails, optimization is skipped and issues are reported.

## Research Background

**Original Papers:**
- Rigger & Su (2020): "Finding Bugs in Database Systems via Query Partitioning" (OOPSLA 2020)
- Rigger & Su (2020): "Detecting Optimization Bugs via Non-optimizing Reference Engine Construction" (ESEC/FSE 2020)

**Implementation:**
- SQLancer: https://github.com/sqlancer/sqlancer
- Found 400+ bugs in PostgreSQL, MySQL, SQLite, CockroachDB

**Production Use:**
- CockroachDB uses metamorphic testing in CI/CD

## API Reference

### ValidationResult

```python
@dataclass
class ValidationResult:
    passed: bool              # True if validation passed
    confidence: float         # 0.0 to 1.0
    method: str              # "TLP", "NoREC", or "TLP+NoREC"
    issues: List[ValidationIssue]
    execution_time_ms: float
    queries_executed: int
    metadata: Dict[str, Any]
```

### ValidationIssue

```python
@dataclass
class ValidationIssue:
    issue_type: str          # "PARTITION_MISMATCH", "OPTIMIZATION_BUG", etc.
    description: str         # Human-readable description
    severity: str           # "ERROR", "WARNING", "INFO"
    evidence: Dict[str, Any] # Supporting data
    suggested_fix: str      # Actionable fix suggestion
```

### Validators

**TLPValidator**
- `validate(query, db_connection)` → ValidationResult
- `_extract_where_predicate(query)` → str
- `_partition_query(query, predicate, truth_value)` → str

**NoRECValidator**
- `validate(query, db_connection)` → ValidationResult
- `_generate_non_optimizable(query)` → str

**ResultComparator**
- `compare_result_sets(rs1, rs2)` → bool
- `multiset_union(result_sets)` → List
- `find_mismatched_rows(rs1, rs2, max_examples)` → Tuple

## Development Notes

**Adding New Validators:**

1. Inherit from `CorrectnessValidator`
2. Implement `async def validate()` method
3. Return `ValidationResult`
4. Add to `src/validators/__init__.py`

**Testing:**

```bash
# Run validator tests
pytest tests/test_validators.py -v

# Run specific test
pytest tests/test_validators.py::TestTLPValidator::test_predicate_extraction -v

# With coverage
pytest tests/test_validators.py --cov=src/validators
```

**Database Requirements:**

- PostgreSQL 12+ (TLP and NoREC tested)
- Active connection for validation
- Read permissions on queried tables
- No special extensions required

## Limitations

**Current Limitations:**
- PostgreSQL only (MySQL/SQLite planned)
- TLP requires WHERE clause
- NoREC only checks row counts
- No support for CTEs, window functions in partitioning

**Cannot Detect:**
- Schema design issues
- Missing JOIN conditions (if query executes)
- Business logic errors outside SQL
- All possible query bugs

**False Negatives:**
- Very rare
- Usually indicates data distribution hiding bug
- Or bug in non-validated part of query

## Further Reading

- README.md: Quick start and overview
- tests/test_validators.py: Usage examples
- SQLancer docs: https://github.com/sqlancer/sqlancer/wiki
- OOPSLA 2020 paper: https://doi.org/10.1145/3428279
