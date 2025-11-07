# Dataset Setup Guide

**Date**: November 7, 2025
**Status**: ⚠️ **DATASETS NOT YET DOWNLOADED**

---

## Dataset Overview

The Agentic DBA project targets TWO different benchmarks:

### 1. BIRD Mini-Dev (Phase 1 Validation) ✅ Design Complete

- **Purpose**: Text-to-SQL generation and query correctness
- **Tasks**: 500 PostgreSQL query pairs
- **Use Case**: Validate tool can analyze queries (exev.py)
- **Status**: Phase 1 was built with this in mind, but **dataset not downloaded**

### 2. BIRD-CRITIC (Phase 2 Target) 🎯 **PRIMARY FOCUS**

- **Purpose**: SQL debugging and efficiency optimization
- **Tasks**: 600 real-world SQL issues (200 Flash-Exp, 530 PostgreSQL, 570 Open)
- **Use Case**: Autonomous agent optimization benchmark
- **Status**: Phase 2 agent built for this, but **dataset not downloaded**
- **Leaderboard**: Current SOTA 34.5% → Our target: 45-50%

---

## ⚠️ Current Situation

**Neither dataset is currently available in the repository.**

Both need to be downloaded and set up before testing can proceed.

---

## Recommended: BIRD-CRITIC Setup (Phase 2)

### Option A: Hugging Face Datasets (Easiest)

```bash
# Install datasets library
pip install datasets

# Download Flash-Exp (200 PostgreSQL tasks)
python3 << 'EOF'
from datasets import load_dataset

# Load BIRD-CRITIC Flash-Exp
ds = load_dataset("birdsql/bird-critic-1.0-flash-exp")
print(f"Loaded {len(ds['train'])} tasks")

# Save to JSON for our runner
import json
tasks = []
for item in ds['train']:
    tasks.append({
        "task_id": item.get("id", ""),
        "db_id": item.get("db_id", ""),
        "user_query": item.get("user_query", ""),
        "buggy_sql": item.get("buggy_sql", ""),
        "solution_sql": item.get("solution_sql", ""),
        "efficiency": item.get("efficiency", False)
    })

with open("bird_critic_flash_exp.json", "w") as f:
    json.dump(tasks, f, indent=2)

print("✓ Saved to bird_critic_flash_exp.json")
EOF
```

### Option B: GitHub Repository

```bash
# Clone BIRD-CRITIC repository
git clone https://github.com/bird-bench/BIRD-CRITIC-1.git

# Files available:
# - bird-critic-1.0-flash-exp (200 tasks, PostgreSQL only)
# - bird-critic-1.0-postgresql (530 tasks)
# - bird-critic-1.0-open (570 tasks, multi-dialect)

cd BIRD-CRITIC-1
# Follow their README for database setup
```

### Option C: Direct Download

```bash
# Download from Hugging Face (no git clone)
wget https://huggingface.co/datasets/birdsql/bird-critic-1.0-flash-exp/resolve/main/train.json -O bird_critic_flash.json
```

---

## Database Setup for BIRD-CRITIC

### PostgreSQL Database

BIRD-CRITIC tasks use multiple databases. You need to:

1. **Option 1: Docker (Recommended)**
   ```bash
   # Use official BIRD-CRITIC Docker image
   docker run -d --name bird-critic-postgres \
     -e POSTGRES_PASSWORD=birdcritpass \
     -p 5432:5432 \
     birdsql/bird-critic-db:latest

   # Connection string
   export DB_CONNECTION='postgresql://postgres:birdcritpass@localhost:5432/bird_critic'
   ```

2. **Option 2: Manual Setup**
   ```bash
   # Download database dumps from BIRD-CRITIC repo
   git clone https://github.com/bird-bench/BIRD-CRITIC-1.git
   cd BIRD-CRITIC-1/databases

   # Import databases
   for db in *.sql; do
       createdb $(basename $db .sql)
       psql $(basename $db .sql) < $db
   done
   ```

3. **Option 3: Request Access**
   ```bash
   # Email BIRD team for full dataset access
   # (test cases not included in public release to prevent data leakage)
   echo "bird.bench25@gmail.com" | xclip -selection clipboard
   # Email them requesting full BIRD-CRITIC dataset with test cases
   ```

---

## Alternative: BIRD Mini-Dev Setup (Phase 1)

If you want to test Phase 1 validation first:

### Download BIRD Mini-Dev

```bash
# Option 1: Hugging Face
pip install datasets
python3 << 'EOF'
from datasets import load_dataset
ds = load_dataset("birdsql/bird_mini_dev")
print(ds)
# Save tasks to JSON as needed
EOF

# Option 2: Direct download (800MB)
wget https://bird-bench.oss-cn-beijing.aliyuncs.com/minidev.zip
unzip minidev.zip
mv minidev mini_dev

# Option 3: Google Drive
# Manual download: https://drive.google.com/file/d/13VLWIwpw5E3d5DUkMvzw7hvHE67a4XkG/view
```

### Import PostgreSQL Databases

```bash
# Located in: mini_dev/MINIDEV_postgresql/BIRD_dev.sql
createdb bird_dev
psql bird_dev < mini_dev/MINIDEV_postgresql/BIRD_dev.sql

# This creates 11 databases with sample data
# Total size: ~1GB
```

---

## Quick Start: Minimal Testing Setup

**For immediate testing without large downloads:**

### Create Synthetic Test Database

```bash
# 1. Start PostgreSQL
sudo service postgresql start

# 2. Create test database
createdb test_optimization

# 3. Create sample table
psql test_optimization << 'EOF'
-- Large table for testing index optimization
CREATE TABLE users (
    user_id SERIAL PRIMARY KEY,
    name VARCHAR(100),
    email VARCHAR(100),
    country VARCHAR(50),
    created_at TIMESTAMP DEFAULT NOW()
);

-- Insert 100K rows
INSERT INTO users (name, email, country)
SELECT
    'User ' || i,
    'user' || i || '@example.com',
    CASE (i % 5)
        WHEN 0 THEN 'USA'
        WHEN 1 THEN 'UK'
        WHEN 2 THEN 'Canada'
        WHEN 3 THEN 'Australia'
        ELSE 'Other'
    END
FROM generate_series(1, 100000) AS i;

-- Analyze for accurate stats
ANALYZE users;
EOF

# 4. Test query (should trigger seq scan)
psql test_optimization -c "EXPLAIN ANALYZE SELECT * FROM users WHERE email = 'user50000@example.com';"
```

### Run Demo

```bash
export ANTHROPIC_API_KEY='sk-ant-api03-...'
export DB_CONNECTION='postgresql://localhost/test_optimization'

# Test Phase 1 tool
python exev.py \
  -q "SELECT * FROM users WHERE email = 'user50000@example.com'" \
  -d "$DB_CONNECTION" \
  --max-cost 1000

# Test Phase 2 agent
python demo_agent.py
```

**Expected Cost**: $0.05

---

## Configuration for Our Agent

### bird_critic_runner.py Configuration

```python
# When you have the dataset:
python -m agentic_dba.bird_critic_runner \
  --dataset ./bird_critic_flash_exp.json \
  --db-connection postgresql://localhost/bird_critic_db \
  --limit 5 \
  --output results.json
```

### Expected File Structure

```
exev_dba/
├── bird_critic_flash_exp.json     # 200 tasks (download needed)
├── bird_critic_postgresql.json    # 530 tasks (optional)
├── mini_dev/                       # BIRD Mini-Dev (optional)
│   └── MINIDEV_postgresql/
│       └── BIRD_dev.sql
└── src/agentic_dba/
    ├── agent.py
    └── bird_critic_runner.py
```

---

## What We Built For

**Phase 2 Agent (`agent.py` + `bird_critic_runner.py`) is specifically designed for:**

### BIRD-CRITIC Format

```json
{
  "task_id": "001",
  "db_id": "ecommerce",
  "user_query": "Get all orders from US customers in 2024",
  "buggy_sql": "SELECT * FROM orders o JOIN users u ON o.user_id = u.id WHERE u.country = 'USA'",
  "solution_sql": "SELECT o.* FROM orders o JOIN users u ON o.user_id = u.id WHERE u.country = 'USA' AND o.year = 2024",
  "efficiency": true
}
```

**Key fields our agent uses:**
- `task_id`: Tracking
- `db_id`: Database selection
- `buggy_sql`: Query to optimize
- `user_query`: Context for agent
- `efficiency`: Boolean flag for optimization tasks

---

## Recommended Next Steps

### Priority 1: Quick Demo (10 minutes, $0.05)

1. Create synthetic test database (script above)
2. Run `demo_agent.py`
3. Validate agent works end-to-end

### Priority 2: BIRD-CRITIC Flash-Exp (1 hour, ~$1)

1. Download Flash-Exp dataset (200 tasks)
2. Set up PostgreSQL databases
3. Run on 5 tasks: `--limit 5`
4. Analyze results

### Priority 3: Full Evaluation (1 week, ~$24)

1. Download full PostgreSQL dataset (530 tasks)
2. Run complete evaluation
3. Submit to leaderboard

---

## Status Check Commands

```bash
# Check if datasets exist
ls -lh bird_critic*.json 2>/dev/null || echo "BIRD-CRITIC not downloaded"
ls -lh mini_dev/ 2>/dev/null || echo "BIRD Mini-Dev not downloaded"

# Check PostgreSQL
psql -l | grep bird || echo "BIRD databases not set up"

# Check dependencies
python -c "from datasets import load_dataset; print('✓ datasets library available')" 2>/dev/null || echo "datasets library not installed"
```

---

## Summary

| Dataset | Purpose | Status | Priority |
|---------|---------|--------|----------|
| **BIRD-CRITIC Flash** | Agent testing (200 tasks) | ❌ Not downloaded | 🔴 HIGH |
| **BIRD-CRITIC Full** | Full evaluation (530 tasks) | ❌ Not downloaded | 🟡 MEDIUM |
| **BIRD Mini-Dev** | Phase 1 validation (500 queries) | ❌ Not downloaded | 🟢 LOW |
| **Synthetic DB** | Quick demo/testing | ❌ Not created | 🔴 HIGH |

---

## Contact

For dataset access issues:
- **BIRD-CRITIC**: bird.bench25@gmail.com
- **BIRD Mini-Dev**: https://github.com/bird-bench/mini_dev

---

**Bottom Line**: We need to download BIRD-CRITIC and set up PostgreSQL to run real tests. The synthetic database approach is fastest for initial validation.

