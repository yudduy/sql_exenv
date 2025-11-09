# SQL Execution Environment (sql_exenv)

Autonomous PostgreSQL query optimization system that translates EXPLAIN plans into actionable feedback for AI agents.

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## Overview

sql_exenv bridges the gap between PostgreSQL's technical execution metrics and AI agent decision-making. Instead of manually analyzing EXPLAIN plans and guessing at optimizations, sql_exenv automatically detects bottlenecks, translates them into natural language feedback, and runs an autonomous optimization loop with correctness guarantees. It handles everything from missing indexes to query rewrites while maintaining safety controls for production environments.

## Architecture

```
┌─────────────┐
│ SQL Query   │
└──────┬──────┘
       │
       ▼
┌─────────────────────────────────────┐
│  Analyzer                           │
│  (Technical bottleneck detection)   │
└──────┬──────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────┐
│  Semanticizer                       │
│  (Natural language translation)     │
└──────┬──────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────┐
│  ReAct Agent                        │
│  (Autonomous optimization loop)     │
└──────┬──────────────────────────────┘
       │
       ▼
┌─────────────┐
│ Optimized   │
│ Query       │
└─────────────┘
```

## Installation

```bash
git clone https://github.com/yudduy/sql_exenv.git
cd sql_exenv
pip install -r requirements.txt
```

## Quick Start

### Database Setup

Start PostgreSQL with sample data using Docker:

```bash
docker-compose up -d
export DB_CONNECTION='postgresql://postgres:postgres@localhost:5432/demo'
```

The database includes 10k users, 25k orders, and 5k products with intentional performance issues for demonstration.

### Run Optimization

Set your API key (if not already done):

```bash
export ANTHROPIC_API_KEY='your-key'
```

Launch chat mode:

```bash
python cli.py
```

Or analyze a single query:

```bash
python cli.py --query "SELECT * FROM users WHERE email='user5000@example.com'"
```

Run autonomous optimization demo:

```bash
python run_agent.py
```

See `docker/example_queries.sql` for 8 queries covering sequential scans, correlated subqueries, window functions, and complex aggregations.

## Python API

```python
from agent import SQLOptimizationAgent

agent = SQLOptimizationAgent()
result = await agent.optimize_query(
    sql="SELECT * FROM users WHERE email='user@example.com'",
    db_connection="postgresql://postgres:postgres@localhost:5432/demo",
    max_cost=10000.0,
    max_time_ms=30000
)

print(f"Success: {result['success']}")
print(f"Final query: {result['final_query']}")
print(f"Actions taken: {len(result['actions'])}")
```

The agent automatically fetches table schemas from the database for all tables referenced in the query. This provides the LLM with column names, data types, existing indexes, and foreign key relationships to make informed optimization decisions. Schema fetching can be disabled with `auto_fetch_schema=False` if needed.

## How It Works

### Two-Stage Pipeline

The **Analyzer** parses PostgreSQL EXPLAIN JSON output and identifies bottlenecks programmatically: sequential scans on large tables, high-cost operations, planner estimate errors, and inefficient joins. It operates deterministically using rule-based detection.

The **Semanticizer** translates technical analysis into natural language feedback using Claude. It provides actionable suggestions like CREATE INDEX statements or query rewrites, assigns priority levels, and determines pass/fail status based on cost constraints.

### Autonomous Agent

The ReAct-style optimization loop uses Claude Sonnet to iteratively improve queries. Each iteration analyzes the execution plan, plans an optimization action, executes DDL or rewrites the query, validates the improvement, and repeats until the query is optimized or reaches max iterations. The agent includes stagnation detection to avoid infinite loops.

### Schema Awareness

The agent automatically extracts table names from the SQL query using sqlparse and fetches metadata from PostgreSQL information_schema. This includes column definitions, existing indexes, and foreign key relationships. The schema representation is minimized to reduce context window usage while preserving all information needed for optimization decisions.

### Safety Features

sql_exenv uses a two-phase EXPLAIN strategy: it estimates cost first, then runs ANALYZE only if safe. Statement timeouts prevent runaway queries, cost thresholds gate expensive operations, and HypoPG enables hypothetical index validation without actual DDL impact.

## Architecture Details

## Project Structure

```
sql_exenv/
├── docker/                  # Database setup
│   ├── init.sql            # Sample schema with 40k rows
│   ├── example_queries.sql # 8 queries demonstrating optimizations
│   └── README.md           # Docker setup guide
│
├── src/                     # Core system
│   ├── __init__.py          # Package initialization
│   ├── analyzer.py          # EXPLAIN plan analysis
│   ├── semanticizer.py      # Semantic translation
│   ├── agent.py             # Autonomous optimization agent
│   ├── schema_fetcher.py    # Automatic schema introspection
│   └── actions.py           # Action definitions
│
├── tests/                   # Test suite
│   ├── test_analyzer.py    # Analyzer unit tests
│   ├── test_agent.py        # Agent TDD tests
│   ├── test_e2e.py          # End-to-end tests
│   └── test_edge_cases.py  # Edge case tests
│
├── cli.py                   # Chat-based CLI
├── run_agent.py             # Autonomous agent demo
├── docker-compose.yml       # PostgreSQL setup
├── pyproject.toml           # Package configuration
├── requirements.txt         # Dependencies
└── README.md
```

## Testing

```bash
# Run all tests
pytest

# With coverage
pytest --cov=src --cov-report=html

# Specific test file
pytest tests/test_analyzer.py -v
```

## Safety

Two-phase EXPLAIN strategy ensures safe analysis:

1. **Phase 1**: `EXPLAIN (FORMAT JSON)` estimates cost without execution
2. **Phase 2**: `EXPLAIN (ANALYZE, FORMAT JSON)` runs full analysis with timeout protection only if estimated cost is below threshold

Recommended production settings: `max_time_ms: 60000`, `analyze_cost_threshold: 10000000`

## HypoPG Integration

HypoPG enables risk-free index validation by creating hypothetical indexes without disk usage, re-running EXPLAIN to capture the optimized plan, and reporting cost improvement percentage.

Requires PostgreSQL extension: `CREATE EXTENSION IF NOT EXISTS hypopg`

## Configuration

```bash
export ANTHROPIC_API_KEY="your-key-here"
export DB_CONNECTION="postgresql://localhost:5432/mydb"
```

All EXPLAIN operations are read-only and execute no user queries.

## Dependencies

- `psycopg2-binary` - PostgreSQL database connectivity
- `anthropic` - Claude API integration for semantic translation
- `sqlparse` - SQL parsing and schema introspection

## License

MIT License - see LICENSE file for details.
