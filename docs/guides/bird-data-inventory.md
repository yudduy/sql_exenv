# BIRD Mini-Dev Dataset Inventory

**Generated**: 2025-11-06
**Source**: bird-bench/mini_dev (GitHub) + Alibaba OSS
**Purpose**: SQL query optimization validation for Agentic DBA system

---

## Overview

The BIRD (BIg Bench for LaRge-scale Database Grounded Text-to-SQL) Mini-Dev dataset is a curated subset of 500 high-quality text-to-SQL pairs designed for efficient development and testing of SQL query generation and optimization models.

### Key Statistics

- **Total Examples**: 500 PostgreSQL query pairs
- **Databases**: 11 distinct databases across various domains
- **Difficulty Levels**: Simple (30%), Moderate (50%), Challenging (20%)
- **Data Size**: ~1GB total (800MB compressed)

---

## Dataset Structure

```
mini_dev/minidev/
├── MINIDEV/
│   ├── dev_databases/              # 11 SQLite databases
│   │   ├── california_schools/
│   │   ├── card_games/
│   │   ├── codebase_community/
│   │   ├── debit_card_specializing/
│   │   ├── european_football_2/
│   │   ├── financial/
│   │   ├── formula_1/
│   │   ├── student_club/
│   │   ├── superhero/
│   │   ├── thrombosis_prediction/
│   │   └── toxicology/
│   ├── mini_dev_postgresql.json    # Question-SQL pairs
│   ├── mini_dev_postgresql_gold.sql # Gold standard queries
│   └── dev_tables.json             # Table schema metadata
├── MINIDEV_postgresql/
│   └── BIRD_dev.sql                # PostgreSQL dump (all databases)
└── MINIDEV_mysql/
    └── BIRD_dev.sql                # MySQL dump (all databases)
```

---

## Databases and Query Distribution

| Database                   | Queries | Domain                | Complexity Range    |
|----------------------------|---------|----------------------|---------------------|
| california_schools         | 30      | Education            | Simple - Moderate   |
| card_games                 | 52      | Gaming/Trading Cards | Simple - Challenging|
| codebase_community         | 49      | Software Development | Moderate - Challenging|
| debit_card_specializing    | 30      | Finance/Transactions | Simple - Moderate   |
| european_football_2        | 51      | Sports               | Moderate - Challenging|
| financial                  | 32      | Finance              | Simple - Moderate   |
| formula_1                  | 66      | Sports/Racing        | Moderate - Challenging|
| student_club               | 48      | Education            | Simple - Challenging|
| superhero                  | 52      | Entertainment        | Simple - Moderate   |
| thrombosis_prediction      | 50      | Healthcare           | Moderate - Challenging|
| toxicology                 | 40      | Healthcare           | Moderate - Challenging|

---

## Difficulty Distribution

- **Simple** (148 queries, 29.6%): Basic SELECT queries, simple joins, basic aggregations
- **Moderate** (250 queries, 50.0%): Multiple joins, subqueries, window functions
- **Challenging** (102 queries, 20.4%): Complex nested queries, multiple CTEs, advanced aggregations

---

## Data Format

### Query Pair JSON Structure

Each entry in `mini_dev_postgresql.json` contains:

```json
{
  "question_id": 1471,
  "db_id": "debit_card_specializing",
  "question": "What is the ratio of customers who pay in EUR against customers who pay in CZK?",
  "evidence": "ratio = count(Currency = 'EUR') / count(Currency = 'CZK')",
  "SQL": "SELECT CAST(SUM(CASE WHEN Currency = 'EUR' THEN 1 ELSE 0 END) AS REAL) / NULLIF(SUM(CASE WHEN Currency = 'CZK' THEN 1 ELSE 0 END), 0) FROM customers",
  "difficulty": "simple"
}
```

**Fields**:
- `question_id`: Unique identifier
- `db_id`: Database name
- `question`: Natural language question
- `evidence`: Additional context/reasoning hints
- `SQL`: Gold standard PostgreSQL query
- `difficulty`: simple | moderate | challenging

---

## Database Schema Information

Each database folder contains:
1. **SQLite database file** (`<db_name>.sqlite`) - Original data
2. **database_description/** folder with CSV schema files:
   - One CSV per table describing columns, types, and relationships
   - Example: `customers.csv`, `transactions_1k.csv`, etc.

### PostgreSQL Schema

The `BIRD_dev.sql` file contains:
- CREATE DATABASE statements for all 11 databases
- CREATE TABLE statements with proper types
- INSERT statements with sample data
- Indexes and constraints

---

## Files Locations

### Key Data Files

| File | Path | Size | Purpose |
|------|------|------|---------|
| PostgreSQL JSON | `MINIDEV/mini_dev_postgresql.json` | 277KB | Questions & SQL queries |
| PostgreSQL Dump | `MINIDEV_postgresql/BIRD_dev.sql` | 955MB | Full database setup |
| Gold SQL | `MINIDEV/mini_dev_postgresql_gold.sql` | 107KB | Reference queries |
| Table Metadata | `MINIDEV/dev_tables.json` | 155KB | Schema information |

### Database Files

All SQLite databases are in: `MINIDEV/dev_databases/<db_name>/<db_name>.sqlite`

---

## Integration with Agentic DBA

### Validation Approach

1. **Setup**: Import PostgreSQL databases from `BIRD_dev.sql`
2. **Test Queries**: Use queries from `mini_dev_postgresql.json`
3. **Optimization**: Run `optimize_postgres_query()` on each query
4. **Validation**: Compare:
   - Cost reduction vs. baseline
   - Suggestion accuracy (valid SQL)
   - Execution time improvements
   - False positive rate (flagging already-optimal queries)

### Expected Use Cases

| Query Type | Count | Optimization Potential |
|------------|-------|----------------------|
| Sequential scans | ~150 | High (index suggestions) |
| Nested loops | ~80 | Moderate (join reordering) |
| Aggregations | ~120 | Low-Moderate (grouping optimization) |
| CTEs/Subqueries | ~100 | High (materialization hints) |
| Simple lookups | ~50 | Low (already optimal) |

---

## Next Steps

1. **Import databases** into PostgreSQL using `BIRD_dev.sql`
2. **Create test harness** (`bird_validator.py`) to run validation
3. **Implement metrics**:
   - Query cost reduction %
   - Suggestion validity (parseable SQL)
   - False positive rate
   - Iteration count to optimization
4. **Run validation** on all 500 queries
5. **Generate report** with accuracy, performance, and error analysis

---

## References

- **BIRD Paper**: https://arxiv.org/abs/2305.03111
- **Leaderboard**: https://bird-bench.github.io/
- **Mini-Dev Repo**: https://github.com/bird-bench/mini_dev
- **HuggingFace Dataset**: https://huggingface.co/datasets/birdsql/bird_mini_dev
- **Download Link**: https://bird-bench.oss-cn-beijing.aliyuncs.com/minidev.zip

---

## License

CC BY-SA 4.0 (Creative Commons Attribution-ShareAlike 4.0)
