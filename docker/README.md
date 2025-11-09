# Docker Setup

PostgreSQL environment with 40,000 rows designed to demonstrate real optimization scenarios.

## Quick Start

```bash
docker-compose up -d
export DB_CONNECTION='postgresql://postgres:postgres@localhost/demo'
```

## Database Contents

- **users**: 10,000 rows (no email index for sequential scan demonstration)
- **orders**: 25,000 rows (no foreign keys for join optimization)
- **products**: 5,000 rows (no category index for filter optimization)

All tables have ANALYZE run for accurate cost estimation.

## Example Queries

`example_queries.sql` contains 8 queries demonstrating:
- Sequential scans requiring indexes
- Correlated subqueries needing rewrites
- OR conditions with multiple index scans
- Window functions with unindexed partitions
- Complex aggregations

## Cleanup

```bash
docker-compose down -v
```
