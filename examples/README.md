# SQL Optimization Examples

This directory contains a complete, isolated testing environment for experimenting with the SQL optimization tool. It includes sample schemas, realistic data, and various query patterns that demonstrate common optimization opportunities.

## Purpose

- **Learning**: Understand how the AI agent identifies and fixes SQL performance issues
- **Testing**: Try out optimization strategies on realistic data patterns
- **Development**: Test new optimization features in a controlled environment
- **Demonstration**: Show the tool's capabilities with practical examples

## Directory Structure

```
examples/
├── README.md                 # This file - usage instructions
├── schemas/                  # Database schema definitions
│   ├── setup.sql            # Creates tables and sample data
│   └── teardown.sql         # Removes all tables (cleanup)
├── queries/                  # Sample SQL queries for testing
│   ├── sample_queries.sql   # 8 diverse optimization examples
│   └── test_queries.sql     # 3 focused test scenarios
├── scripts/                  # Utility scripts
│   ├── setup_database.py    # Python database setup helper
│   └── run_examples.py      # Example CLI launcher
└── .env.example             # Environment variables template
```

## Quick Start

### 1. Set Up Database

**Option A: Python Script (Recommended)**
```bash
# Create a fresh database
createdb sql_examples

# Run the setup script
python scripts/setup_database.py --dbname sql_examples --user postgres
```

**Option B: Direct psql**
```bash
# Create database
createdb sql_examples

# Run setup directly
psql -d sql_examples -f schemas/setup.sql
```

### 2. Configure Environment

```bash
# Copy environment template
cp .env.example .env

# Edit with your database connection
echo "DB_CONNECTION=postgresql://localhost/sql_examples" >> .env
```

### 3. Run Optimization Examples

```bash
# Interactive mode - try your own queries
python scripts/run_examples.py --interactive

# Analyze sample queries
python scripts/run_examples.py --file queries/sample_queries.sql

# Run specific test scenarios
python scripts/run_examples.py --file queries/test_queries.sql
```

## Sample Schema Overview

The example database models an e-commerce system with four main tables:

### Tables

- **`customers`** - Customer information with geographic data
- **`products`** - Product catalog with categories and pricing
- **`orders`** - Order records with status and dates
- **`order_items`** - Line items connecting orders and products

### Data Characteristics

- **10 customers** across different cities and countries
- **15 products** in various categories with different price points
- **20 orders** with different statuses and dates
- **20 order items** showing realistic purchase patterns

### Built-in Optimization Challenges

The schema and data are designed to trigger common optimization scenarios:

1. **Missing Indexes**: Queries filtering on non-indexed columns
2. **Sequential Scans**: Large table scans without proper indexes
3. **Correlated Subqueries**: Performance-heavy correlated subqueries
4. **JOIN Patterns**: Complex multi-table joins with aggregations
5. **Window Functions**: Ranking and analytical queries
6. **OR Conditions**: Queries with complex WHERE clauses

## Query Examples

### Sample Queries (`sample_queries.sql`)

1. **Complex JOIN with Aggregation** - Multiple joins, grouping, and filtering
2. **Subquery Optimization** - Correlated subqueries that could be JOINs
3. **Nested Subqueries** - Multiple levels of subquery nesting
4. **Window Functions** - Ranking and analytical operations
5. **DISTINCT with JOINs** - Expensive DISTINCT operations
6. **Correlated Subquery Performance** - Classic performance anti-patterns
7. **Complex WHERE Clauses** - OR conditions and multiple filters
8. **Multiple Aggregations** - Complex analytics in single query

### Test Queries (`test_queries.sql`)

1. **Simple Join with Filters** - Basic optimization scenario
2. **Sequential Scan Challenge** - Multi-table join performance test
3. **Window Functions with CTE** - Common table expression optimization

## Usage Patterns

### Interactive Exploration
```bash
# Start interactive mode
python scripts/run_examples.py --interactive

# Try queries like:
SELECT * FROM customers WHERE country = 'USA' AND total_spent > 1000;
```

### Batch Analysis
```bash
# Analyze all sample queries
python scripts/run_examples.py --file queries/sample_queries.sql --output results.json

# Use real LLM for detailed analysis
python scripts/run_examples.py --file queries/test_queries.sql --real --model claude-3-5-sonnet-20241022
```

### Custom Testing
```bash
# Test your own query file
python scripts/run_examples.py --file my_queries.sql --max-cost 500

# Enable HypoPG proof (requires extension)
python scripts/run_examples.py --interactive --use-hypopg
```

## Advanced Configuration

### Environment Variables

Create a `.env` file with these settings:

```bash
# Database connection
DB_CONNECTION=postgresql://localhost/sql_examples

# Claude API (for real optimization suggestions)
ANTHROPIC_API_KEY=your_api_key_here

# Optimization thresholds
MAX_COST=1000
MAX_TIME_MS=60000
ANALYZE_COST_THRESHOLD=10000000
```

### CLI Options

```bash
# Safety thresholds
--max-cost 1000              # Maximum acceptable plan cost
--max-time-ms 60000          # Statement timeout for ANALYZE
--analyze-cost-threshold 10000000  # Skip ANALYZE for expensive plans

# Features
--use-hypopg                 # Enable hypothetical index proof
--real                       # Use real LLM instead of mock
--model claude-3-5-sonnet-20241022  # Specify Claude model

# Output
--output results.json        # Save detailed results
--verbose                    # Show detailed progress
```

## Experimentation Ideas

### 1. Index Impact Analysis
```sql
-- Query without index
SELECT * FROM orders WHERE amount > 1000;

-- Create index and compare
CREATE INDEX idx_orders_amount ON orders(amount);
-- Run the same query again to see improvement
```

### 2. Query Rewrite Testing
```sql
-- Correlated subquery (slow)
SELECT c.name, (SELECT COUNT(*) FROM orders o WHERE o.customer_id = c.id) as order_count
FROM customers c;

-- JOIN rewrite (faster)
SELECT c.name, COUNT(o.id) as order_count
FROM customers c
LEFT JOIN orders o ON c.id = o.customer_id
GROUP BY c.id, c.name;
```

### 3. HypoPG Validation
```bash
# Test index suggestions without creating them
python scripts/run_examples.py --interactive --use-hypopg

# The tool will show "before/after" cost comparisons
```

## Understanding Output

The optimization tool provides several types of feedback:

### Status Indicators
- **PASS** - Query meets performance criteria
- **WARNING** - Minor optimization opportunities
- **FAIL** - Significant performance issues detected

### Common Suggestions
- **CREATE INDEX** - Add indexes on frequently filtered columns
- **REWRITE QUERY** - Restructure subqueries as JOINs
- **ADD PARTITION** - Partition large tables by date/range
- **OPTIMIZE JOIN ORDER** - Reorder JOIN operations

### Cost Analysis
```
Before:  Cost=15,432.12  Time=234ms
After:   Cost=1,234.56   Time=45ms
Improvement: 92% cost reduction
```

## Cleanup

When you're done testing, clean up the database:

```bash
# Remove all tables and data
python scripts/setup_database.py --teardown --dbname sql_examples --user postgres

# Or drop the entire database
dropdb sql_examples
```

## Contributing

To add new examples:

1. Create new SQL files in `queries/`
2. Update schema in `schemas/setup.sql` if needed
3. Add documentation to this README
4. Test with the example scripts

## Related Documentation

- [Main README](../README.md) - Core tool documentation
- [CLI Usage](../cli.py) - Command-line interface details
- [Architecture](../docs/architecture.md) - System design overview

---

**Happy Query Optimizing!**
