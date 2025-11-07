#!/bin/bash
# Quick Test Environment Setup
# Creates minimal database and downloads BIRD-CRITIC Flash-Exp

set -e

echo "======================================"
echo "Agentic DBA Test Environment Setup"
echo "======================================"
echo

# Function to check command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Check Python
if ! command_exists python3; then
    echo "ERROR: python3 not found"
    exit 1
fi
echo "✓ Python 3 found: $(python3 --version)"

# Check pip
if ! command_exists pip; then
    echo "WARNING: pip not found, attempting to install..."
    python3 -m ensurepip || true
fi

# Install datasets library
echo
echo "Step 1: Installing datasets library..."
pip install -q datasets || echo "WARNING: datasets install failed"

# Download BIRD-CRITIC Flash-Exp
echo
echo "Step 2: Downloading BIRD-CRITIC Flash-Exp (200 tasks)..."
python3 << 'PYEOF'
import json
import sys

try:
    from datasets import load_dataset
    print("Loading dataset from Hugging Face...")

    # Load BIRD-CRITIC Flash-Exp
    ds = load_dataset("birdsql/bird-critic-1.0-flash-exp", split="train")
    print(f"✓ Loaded {len(ds)} tasks")

    # Convert to our format
    tasks = []
    for i, item in enumerate(ds):
        task = {
            "task_id": str(item.get("id", f"task_{i:03d}")),
            "db_id": item.get("db_id", "unknown"),
            "user_query": item.get("user_query", item.get("question", "")),
            "buggy_sql": item.get("buggy_sql", item.get("SQL", "")),
            "solution_sql": item.get("solution_sql", ""),
            "efficiency": item.get("efficiency", False)
        }
        tasks.append(task)

    # Save to JSON
    with open("bird_critic_flash_exp.json", "w") as f:
        json.dump(tasks, f, indent=2)

    print(f"✓ Saved {len(tasks)} tasks to bird_critic_flash_exp.json")
    sys.exit(0)

except Exception as e:
    print(f"ERROR: Failed to download dataset: {e}")
    print()
    print("Alternative: Download manually from:")
    print("  https://huggingface.co/datasets/birdsql/bird-critic-1.0-flash-exp")
    sys.exit(1)
PYEOF

echo

# Check PostgreSQL
echo "Step 3: Checking PostgreSQL..."
if command_exists psql; then
    echo "✓ PostgreSQL client found"

    # Try to connect
    if psql -l >/dev/null 2>&1; then
        echo "✓ PostgreSQL server is running"

        # Create test database
        echo
        echo "Step 4: Creating test database..."

        # Check if database exists
        if psql -lqt | cut -d \| -f 1 | grep -qw test_optimization; then
            echo "! Database 'test_optimization' already exists"
            read -p "Drop and recreate? (y/N): " -n 1 -r
            echo
            if [[ $REPLY =~ ^[Yy]$ ]]; then
                dropdb test_optimization || true
                createdb test_optimization
                echo "✓ Database recreated"
            fi
        else
            createdb test_optimization
            echo "✓ Database created"
        fi

        # Create test table
        echo "Creating test table with 100K rows..."
        psql test_optimization << 'SQL'
-- Large table for testing index optimization
CREATE TABLE IF NOT EXISTS users (
    user_id SERIAL PRIMARY KEY,
    name VARCHAR(100),
    email VARCHAR(100) UNIQUE,
    country VARCHAR(50),
    created_at TIMESTAMP DEFAULT NOW()
);

-- Check if already populated
DO $$
BEGIN
    IF (SELECT COUNT(*) FROM users) = 0 THEN
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

        RAISE NOTICE '✓ Inserted 100,000 rows';
    ELSE
        RAISE NOTICE '! Table already populated (% rows)', (SELECT COUNT(*) FROM users);
    END IF;
END $$;
SQL

        echo "✓ Test table ready"

        # Test query
        echo
        echo "Step 5: Testing query (should show Seq Scan)..."
        psql test_optimization -c "EXPLAIN SELECT * FROM users WHERE email = 'user50000@example.com';" | head -10

    else
        echo "ERROR: PostgreSQL server not running"
        echo "Start with: sudo service postgresql start"
        exit 1
    fi
else
    echo "ERROR: PostgreSQL not installed"
    echo "Install with: sudo apt-get install postgresql"
    exit 1
fi

# Summary
echo
echo "======================================"
echo "Setup Complete!"
echo "======================================"
echo
echo "Dataset:"
if [ -f "bird_critic_flash_exp.json" ]; then
    echo "  ✓ bird_critic_flash_exp.json ($(wc -l < bird_critic_flash_exp.json) lines)"
else
    echo "  ✗ bird_critic_flash_exp.json (download failed)"
fi
echo
echo "Database:"
echo "  ✓ test_optimization database with 100K rows"
echo "  Connection: postgresql://localhost/test_optimization"
echo
echo "Next Steps:"
echo "  1. Set API key: export ANTHROPIC_API_KEY='your-key'"
echo "  2. Run demo: python demo_agent.py"
echo "  3. Or test tool: python exev.py -q \"SELECT * FROM users WHERE email = 'user50000@example.com'\" -d postgresql://localhost/test_optimization --max-cost 1000"
echo
