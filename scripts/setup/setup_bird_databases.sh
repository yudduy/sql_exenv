#!/bin/bash
#
# BIRD Dataset PostgreSQL Setup Script
#
# This script automates the setup of BIRD Mini-Dev PostgreSQL databases
# for validating the Agentic DBA query optimization system.
#
# Usage: ./setup_bird_databases.sh [options]
# Options:
#   --user USER       PostgreSQL user (default: bird_user)
#   --database DB     Database name (default: bird_dev)
#   --skip-create    Skip database creation (use existing)
#   --help           Show this help message
#

set -e  # Exit on error

# Color output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Default configuration
PG_USER="${PG_USER:-bird_user}"
PG_DATABASE="${PG_DATABASE:-bird_dev}"
SKIP_CREATE=false
SQL_DUMP="./mini_dev/minidev/MINIDEV_postgresql/BIRD_dev.sql"
JSON_DATA="./mini_dev/minidev/MINIDEV/mini_dev_postgresql.json"

# Parse command-line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --user)
            PG_USER="$2"
            shift 2
            ;;
        --database)
            PG_DATABASE="$2"
            shift 2
            ;;
        --skip-create)
            SKIP_CREATE=true
            shift
            ;;
        --help)
            head -n 15 "$0" | tail -n 12
            exit 0
            ;;
        *)
            echo -e "${RED}Error: Unknown option $1${NC}"
            exit 1
            ;;
    esac
done

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}BIRD Dataset PostgreSQL Setup${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Step 1: Check prerequisites
echo -e "${YELLOW}Step 1: Checking prerequisites...${NC}"

if ! command -v psql &> /dev/null; then
    echo -e "${RED}Error: PostgreSQL (psql) not found${NC}"
    echo "Install PostgreSQL 14+:"
    echo "  Ubuntu/Debian: sudo apt install postgresql postgresql-contrib"
    echo "  macOS: brew install postgresql@14"
    exit 1
fi

if ! command -v createdb &> /dev/null; then
    echo -e "${RED}Error: PostgreSQL client tools not found${NC}"
    exit 1
fi

PSQL_VERSION=$(psql --version | awk '{print $3}' | cut -d. -f1)
if [ "$PSQL_VERSION" -lt 14 ]; then
    echo -e "${YELLOW}Warning: PostgreSQL version $PSQL_VERSION < 14 (recommended: 14+)${NC}"
fi

echo -e "${GREEN}✓ PostgreSQL $(psql --version | awk '{print $3}') found${NC}"

# Check if SQL dump exists
if [ ! -f "$SQL_DUMP" ]; then
    echo -e "${RED}Error: SQL dump not found at $SQL_DUMP${NC}"
    echo "Run download_bird_data.py first or ensure mini_dev/minidev/ exists"
    exit 1
fi

echo -e "${GREEN}✓ SQL dump found ($(du -h $SQL_DUMP | cut -f1))${NC}"

# Check if JSON data exists
if [ ! -f "$JSON_DATA" ]; then
    echo -e "${YELLOW}Warning: JSON data not found at $JSON_DATA${NC}"
else
    QUERY_COUNT=$(python3 -c "import json; print(len(json.load(open('$JSON_DATA'))))")
    echo -e "${GREEN}✓ JSON data found ($QUERY_COUNT queries)${NC}"
fi

echo ""

# Step 2: Check PostgreSQL service
echo -e "${YELLOW}Step 2: Checking PostgreSQL service...${NC}"

if pg_isready -q; then
    echo -e "${GREEN}✓ PostgreSQL is running${NC}"
else
    echo -e "${YELLOW}PostgreSQL is not running. Attempting to start...${NC}"

    # Try to start PostgreSQL (OS-specific)
    if [[ "$OSTYPE" == "linux-gnu"* ]]; then
        sudo service postgresql start || echo -e "${RED}Could not start PostgreSQL. Start manually: sudo service postgresql start${NC}"
    elif [[ "$OSTYPE" == "darwin"* ]]; then
        brew services start postgresql@14 || echo -e "${RED}Could not start PostgreSQL. Start manually: brew services start postgresql@14${NC}"
    fi

    sleep 2

    if pg_isready -q; then
        echo -e "${GREEN}✓ PostgreSQL started${NC}"
    else
        echo -e "${RED}Error: PostgreSQL is not running${NC}"
        echo "Start it manually and re-run this script"
        exit 1
    fi
fi

echo ""

# Step 3: Create database and user
if [ "$SKIP_CREATE" = false ]; then
    echo -e "${YELLOW}Step 3: Creating database and user...${NC}"

    # Check if user exists
    if psql -lqt | cut -d \| -f 1 | grep -qw "$PG_USER" 2>/dev/null; then
        echo -e "${GREEN}✓ User $PG_USER already exists${NC}"
    else
        echo "Creating user $PG_USER..."
        createuser -s "$PG_USER" 2>/dev/null || echo -e "${YELLOW}User may already exist or need sudo${NC}"
    fi

    # Check if database exists
    if psql -lqt | cut -d \| -f 1 | grep -qw "$PG_DATABASE" 2>/dev/null; then
        echo -e "${YELLOW}Database $PG_DATABASE already exists${NC}"
        read -p "Drop and recreate? (y/N): " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            echo "Dropping database $PG_DATABASE..."
            dropdb "$PG_DATABASE" 2>/dev/null || true
            echo "Creating database $PG_DATABASE..."
            createdb -O "$PG_USER" "$PG_DATABASE"
            echo -e "${GREEN}✓ Database recreated${NC}"
        else
            echo -e "${YELLOW}Using existing database${NC}"
        fi
    else
        echo "Creating database $PG_DATABASE..."
        createdb -O "$PG_USER" "$PG_DATABASE"
        echo -e "${GREEN}✓ Database created${NC}"
    fi
else
    echo -e "${YELLOW}Step 3: Skipping database creation (--skip-create)${NC}"
fi

echo ""

# Step 4: Import SQL dump
echo -e "${YELLOW}Step 4: Importing BIRD dataset (this may take 2-5 minutes)...${NC}"

# Get initial table count
INITIAL_TABLES=$(psql -U "$PG_USER" -d "$PG_DATABASE" -tAc "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'" 2>/dev/null || echo "0")

echo "Initial tables: $INITIAL_TABLES"
echo "Importing SQL dump..."

# Import with progress indicator
psql -U "$PG_USER" -d "$PG_DATABASE" -f "$SQL_DUMP" 2>&1 | \
    grep -E "(CREATE TABLE|INSERT|COPY|ERROR)" | \
    while read line; do
        if [[ $line == *"ERROR"* ]]; then
            echo -e "${RED}  $line${NC}"
        elif [[ $line == *"CREATE TABLE"* ]]; then
            TABLE_NAME=$(echo $line | sed 's/.*CREATE TABLE public\.\([^ ]*\).*/\1/')
            echo -e "${GREEN}  ✓ Created table: $TABLE_NAME${NC}"
        fi
    done

# Get final table count
FINAL_TABLES=$(psql -U "$PG_USER" -d "$PG_DATABASE" -tAc "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'")

echo ""
echo -e "${GREEN}✓ Import complete${NC}"
echo "  Tables created: $(($FINAL_TABLES - $INITIAL_TABLES))"
echo "  Total tables: $FINAL_TABLES"

echo ""

# Step 5: Verify import
echo -e "${YELLOW}Step 5: Verifying import...${NC}"

# Check database size
DB_SIZE=$(psql -U "$PG_USER" -d "$PG_DATABASE" -tAc "SELECT pg_size_pretty(pg_database_size('$PG_DATABASE'))")
echo "  Database size: $DB_SIZE"

# Check row counts for sample tables
echo "  Sample table row counts:"
for table in customers account users drivers; do
    ROW_COUNT=$(psql -U "$PG_USER" -d "$PG_DATABASE" -tAc "SELECT count(*) FROM $table" 2>/dev/null || echo "N/A")
    if [ "$ROW_COUNT" != "N/A" ]; then
        echo "    - $table: $ROW_COUNT rows"
    fi
done

echo ""

# Step 6: Create additional indexes
echo -e "${YELLOW}Step 6: Creating additional indexes for performance...${NC}"

psql -U "$PG_USER" -d "$PG_DATABASE" << 'EOF'
-- Create common indexes (if tables exist)
DO $$
BEGIN
    -- Customers table
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name='customers') THEN
        CREATE INDEX IF NOT EXISTS idx_customers_currency ON customers(Currency);
        RAISE NOTICE 'Created index on customers(Currency)';
    END IF;

    -- Transactions table
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name='transactions_1k') THEN
        CREATE INDEX IF NOT EXISTS idx_transactions_date ON transactions_1k(Date);
        RAISE NOTICE 'Created index on transactions_1k(Date)';
    END IF;

    -- Users table (might exist in multiple databases)
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name='users') THEN
        CREATE INDEX IF NOT EXISTS idx_users_id ON users(id);
        RAISE NOTICE 'Created index on users(id)';
    END IF;
END $$;

-- Analyze all tables for query planner
ANALYZE;
EOF

echo -e "${GREEN}✓ Indexes created and statistics updated${NC}"

echo ""

# Step 7: Test connection
echo -e "${YELLOW}Step 7: Testing database connection...${NC}"

TEST_QUERY="SELECT count(*) as table_count FROM information_schema.tables WHERE table_schema='public'"
TABLE_COUNT=$(psql -U "$PG_USER" -d "$PG_DATABASE" -tAc "$TEST_QUERY")

if [ "$TABLE_COUNT" -gt 0 ]; then
    echo -e "${GREEN}✓ Connection successful ($TABLE_COUNT tables accessible)${NC}"
else
    echo -e "${RED}Error: No tables found${NC}"
    exit 1
fi

# Test a sample query
echo ""
echo "Running sample BIRD query..."
SAMPLE_QUERY="SELECT CAST(SUM(CASE WHEN Currency = 'EUR' THEN 1 ELSE 0 END) AS REAL) / NULLIF(SUM(CASE WHEN Currency = 'CZK' THEN 1 ELSE 0 END), 0) as ratio FROM customers"
RESULT=$(psql -U "$PG_USER" -d "$PG_DATABASE" -tAc "$SAMPLE_QUERY" 2>/dev/null || echo "ERROR")

if [ "$RESULT" != "ERROR" ]; then
    echo -e "${GREEN}✓ Sample query executed successfully${NC}"
    echo "  Result: $RESULT"
else
    echo -e "${YELLOW}⚠ Sample query failed (table may not exist)${NC}"
fi

echo ""

# Step 8: Summary
echo -e "${BLUE}========================================${NC}"
echo -e "${GREEN}Setup Complete!${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""
echo "Database: $PG_DATABASE"
echo "User: $PG_USER"
echo "Tables: $FINAL_TABLES"
echo "Size: $DB_SIZE"
echo ""
echo "Connection string for Python:"
echo "  postgresql://$PG_USER@localhost/$PG_DATABASE"
echo ""
echo "Next steps:"
echo "  1. Run validation: python bird_validator.py --database $PG_DATABASE --user $PG_USER"
echo "  2. Test optimization: python test_bird_setup.py"
echo "  3. View data: psql -U $PG_USER -d $PG_DATABASE"
echo ""
echo -e "${GREEN}Happy optimizing!${NC}"
