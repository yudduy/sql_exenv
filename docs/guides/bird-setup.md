# BIRD Dataset Setup Guide

Complete guide to setting up the BIRD Mini-Dev PostgreSQL databases for validating the Agentic DBA query optimization system.

---

## Prerequisites

### Required Software

1. **PostgreSQL 14.12+**
   ```bash
   # Ubuntu/Debian
   sudo apt update
   sudo apt install postgresql postgresql-contrib

   # macOS (Homebrew)
   brew install postgresql@14
   brew services start postgresql@14

   # Verify installation
   psql --version  # Should show PostgreSQL 14.12 or later
   ```

2. **Python 3.10+** with required packages
   ```bash
   pip install psycopg2-binary anthropic mcp pydantic pytest
   ```

3. **Disk Space**: At least 2GB free (1GB for databases, 1GB for working space)

---

## Quick Start

### Option 1: Automated Setup (Recommended)

```bash
# Run the automated setup script
./setup_bird_databases.sh

# This will:
# 1. Create PostgreSQL database 'bird_dev'
# 2. Import all 11 BIRD databases (tables in public schema)
# 3. Create indexes for performance
# 4. Verify data integrity
# 5. Run sample validation test
```

### Option 2: Manual Setup

Follow the steps below if you prefer manual control or troubleshooting.

---

## Manual Setup Steps

### Step 1: Create PostgreSQL Database

```bash
# Start PostgreSQL service (if not running)
sudo service postgresql start  # Linux
brew services start postgresql@14  # macOS

# Create database user (if needed)
createuser -s bird_user  # Superuser for testing

# Create database
createdb -O bird_user bird_dev

# Verify connection
psql -U bird_user -d bird_dev -c "SELECT version();"
```

### Step 2: Import BIRD Dataset

The BIRD Mini-Dev dataset contains all 11 databases merged into a single schema for easier management.

```bash
# Import the PostgreSQL dump
psql -U bird_user -d bird_dev -f ./mini_dev/minidev/MINIDEV_postgresql/BIRD_dev.sql

# This will take 2-5 minutes and creates ~170 tables
# Expected output: CREATE TABLE, INSERT, COPY commands
```

**Note**: The import may show warnings about owner 'xiaolongli' not existing. These are safe to ignore - tables will be owned by bird_user.

### Step 3: Verify Import

```bash
# Check database size
psql -U bird_user -d bird_dev -c "SELECT pg_size_pretty(pg_database_size('bird_dev'));"
# Expected: ~600-800 MB

# Count tables
psql -U bird_user -d bird_dev -c "SELECT count(*) FROM information_schema.tables WHERE table_schema='public';"
# Expected: ~170 tables

# List databases represented
psql -U bird_user -d bird_dev -c "
SELECT DISTINCT tablename
FROM pg_tables
WHERE schemaname='public'
ORDER BY tablename
LIMIT 20;
"
```

### Step 4: Sample Queries

Test with a BIRD query:

```bash
# Simple query from debit_card_specializing database
psql -U bird_user -d bird_dev << 'EOF'
EXPLAIN ANALYZE
SELECT CAST(SUM(CASE WHEN Currency = 'EUR' THEN 1 ELSE 0 END) AS REAL) /
       NULLIF(SUM(CASE WHEN Currency = 'CZK' THEN 1 ELSE 0 END), 0)
FROM customers;
EOF
```

Expected output: EXPLAIN plan showing costs and execution time

---

## Database Structure

### Tables by Domain

The BIRD_dev database contains tables from 11 distinct domains:

| Domain | Tables (Examples) | Purpose |
|--------|------------------|---------|
| **Financial** | account, client, district, loan, trans, card | Banking transactions |
| **Debit Cards** | customers, gasstations, products, transactions_1k | Card usage analysis |
| **Sports (Formula 1)** | races, drivers, circuits, results, lap_times | Racing analytics |
| **Sports (Football)** | match, player, team, player_attributes | European football stats |
| **Gaming** | cards, sets, legalities, rulings | Trading card games |
| **Education** | schools, frpm, satscores | California schools data |
| **Healthcare** | patient, examination, laboratory | Medical records |
| **Software Dev** | badges, comments, posts, users, votes | Stack Overflow-like community |
| **Superhero** | superhero, gender, colour, alignment, attribute | Comic book characters |
| **Student Clubs** | event, member, attendance, budget, income, expense | Student organizations |
| **Toxicology** | atom, bond, molecule, connected | Chemical structure analysis |

### Schema Notes

- All tables are in the `public` schema
- Tables from different domains may have overlapping names (e.g., multiple tables named "users")
- Use table prefixes in queries if needed: `SELECT * FROM users` (there are multiple users tables)
- Foreign keys are defined but may reference tables across domains

---

## Connection String Format

For Python code using psycopg2:

```python
# Standard format
conn_string = "postgresql://bird_user:password@localhost:5432/bird_dev"

# Without password (trust authentication)
conn_string = "postgresql://bird_user@localhost/bird_dev"

# Unix socket (default on Linux)
conn_string = "postgresql:///bird_dev"

# Verify in Python
import psycopg2
conn = psycopg2.connect(conn_string)
cursor = conn.cursor()
cursor.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema='public'")
print(f"Tables: {cursor.fetchone()[0]}")
conn.close()
```

---

## Troubleshooting

### Issue: "connection refused"

```bash
# Check if PostgreSQL is running
sudo service postgresql status  # Linux
brew services list  # macOS

# Start if stopped
sudo service postgresql start  # Linux
brew services start postgresql@14  # macOS

# Check port (default 5432)
sudo netstat -tulpn | grep 5432  # Linux
lsof -i :5432  # macOS
```

### Issue: "database does not exist"

```bash
# List existing databases
psql -l

# Create if missing
createdb bird_dev
```

### Issue: "permission denied"

```bash
# Ensure user has necessary privileges
sudo -u postgres psql -c "ALTER USER bird_user WITH SUPERUSER;"

# Or create with proper privileges
sudo -u postgres createuser -s bird_user
```

### Issue: Import fails with "owner does not exist"

This is expected. The original dump references user 'xiaolongli'. Tables will be owned by your user. Either:

1. **Ignore warnings** (recommended): Tables will work fine with your ownership
2. **Create dummy user**: `createuser xiaolongli` before import
3. **Modify dump**: `sed 's/xiaolongli/bird_user/g' BIRD_dev.sql > BIRD_dev_fixed.sql`

### Issue: Import is slow (>10 minutes)

This is normal for large datasets. To speed up:

```bash
# Disable fsync during import (CAUTION: only for test databases)
psql -U bird_user -d bird_dev -c "ALTER SYSTEM SET fsync=off;"
sudo service postgresql restart

# After import, re-enable
psql -U bird_user -d bird_dev -c "ALTER SYSTEM RESET fsync;"
sudo service postgresql restart
```

---

## Performance Optimization

### Create Indexes

The imported dump may not include all optimal indexes. Create additional ones:

```sql
-- Example: Index for common query patterns
CREATE INDEX idx_customers_currency ON customers(Currency);
CREATE INDEX idx_users_email ON users(email);  -- If users table exists
CREATE INDEX idx_transactions_date ON transactions_1k(Date);

-- Analyze tables for query planner
ANALYZE;
```

### Configure PostgreSQL

For testing/development, adjust PostgreSQL settings:

```bash
# Edit postgresql.conf
sudo nano /etc/postgresql/14/main/postgresql.conf  # Linux
nano /usr/local/var/postgresql@14/postgresql.conf  # macOS

# Recommended settings for development
shared_buffers = 256MB
effective_cache_size = 1GB
work_mem = 16MB
maintenance_work_mem = 128MB

# Restart PostgreSQL
sudo service postgresql restart
```

---

## Validation Testing

### Step 1: Load BIRD Test Queries

```python
import json

# Load the 500 test queries
with open('./mini_dev/minidev/MINIDEV/mini_dev_postgresql.json') as f:
    queries = json.load(f)

print(f"Loaded {len(queries)} test queries")
print(f"First query: {queries[0]['question']}")
print(f"SQL: {queries[0]['SQL']}")
```

### Step 2: Run Sample Validation

```bash
# Test the optimization tool with a BIRD query
python3 << 'EOF'
import asyncio
from mcp_server import QueryOptimizationTool
import json

async def test_bird_query():
    # Load first BIRD query
    with open('./mini_dev/minidev/MINIDEV/mini_dev_postgresql.json') as f:
        queries = json.load(f)

    first_query = queries[0]

    print(f"Testing query: {first_query['question']}")
    print(f"Database: {first_query['db_id']}")
    print()

    # Create tool (use mock translator for testing without API key)
    tool = QueryOptimizationTool(use_mock_translator=True)

    # Run optimization
    result = await tool.optimize_query(
        sql_query=first_query['SQL'],
        db_connection_string="postgresql:///bird_dev",
        constraints={"max_cost": 1000.0}
    )

    print("Result:")
    print(json.dumps(result['feedback'], indent=2))

asyncio.run(test_bird_query())
EOF
```

### Step 3: Run Full Validation Suite

```bash
# Run the comprehensive BIRD validator
python bird_validator.py --database bird_dev --limit 10 --mock-translator

# This will:
# - Test first 10 queries from BIRD dataset
# - Run optimization analysis on each
# - Generate metrics report
# - Save results to bird_validation_results.json
```

---

## Dataset Queries

### Example Queries by Difficulty

**Simple** (148 queries):
```sql
-- Ratio calculation (debit_card_specializing)
SELECT CAST(SUM(CASE WHEN Currency = 'EUR' THEN 1 ELSE 0 END) AS REAL) /
       NULLIF(SUM(CASE WHEN Currency = 'CZK' THEN 1 ELSE 0 END), 0)
FROM customers;
```

**Moderate** (250 queries):
```sql
-- Multi-table join with aggregation (formula_1)
SELECT d.forename, d.surname, COUNT(*) as wins
FROM drivers d
JOIN results r ON d.driverid = r.driverid
WHERE r.position = 1
GROUP BY d.driverid, d.forename, d.surname
ORDER BY wins DESC
LIMIT 10;
```

**Challenging** (102 queries):
```sql
-- Nested subqueries with CTEs (codebase_community)
WITH post_stats AS (
  SELECT owneruserid, COUNT(*) as post_count,
         AVG(score) as avg_score
  FROM posts
  WHERE posttypeid = 1
  GROUP BY owneruserid
)
SELECT u.displayname, ps.post_count, ps.avg_score,
       RANK() OVER (ORDER BY ps.post_count DESC) as rank
FROM users u
JOIN post_stats ps ON u.id = ps.owneruserid
WHERE ps.post_count > 100
ORDER BY rank
LIMIT 20;
```

---

## Next Steps

1. **Verify Setup**: Run `python test_bird_setup.py` to validate configuration
2. **Create Baseline**: Run optimizer on all queries to establish baseline metrics
3. **Analyze Results**: Review bottlenecks, suggestions, and false positives
4. **Iterate**: Refine Model 1 thresholds and Model 2 prompts based on results
5. **Document Findings**: Generate comprehensive validation report

---

## Maintenance

### Backup Database

```bash
# Dump database
pg_dump -U bird_user bird_dev > bird_dev_backup.sql

# Restore if needed
psql -U bird_user -d bird_dev_new -f bird_dev_backup.sql
```

### Reset Database

```bash
# Drop and recreate
dropdb bird_dev
createdb bird_dev
psql -U bird_user -d bird_dev -f ./mini_dev/minidev/MINIDEV_postgresql/BIRD_dev.sql
```

### Update Statistics

```bash
# After making schema changes
psql -U bird_user -d bird_dev -c "ANALYZE VERBOSE;"
```

---

## Resources

- **BIRD Paper**: https://arxiv.org/abs/2305.03111
- **Dataset Homepage**: https://bird-bench.github.io/
- **PostgreSQL Documentation**: https://www.postgresql.org/docs/14/
- **psycopg2 Documentation**: https://www.psycopg.org/docs/

---

## Support

If you encounter issues:
1. Check the Troubleshooting section above
2. Review PostgreSQL logs: `tail -f /var/log/postgresql/postgresql-14-main.log`
3. Test connection: `psql -U bird_user -d bird_dev -c "\\dt"`
4. Verify Python packages: `pip list | grep -E "(psycopg2|anthropic|mcp)"`
