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

Requires PostgreSQL 12+ with a running database instance.

```bash
git clone https://github.com/yudduy/sql_exenv.git
cd sql_exenv
pip install -r requirements.txt
```

## Quick Start

### CLI Analysis

```bash
python cli.py \
  --db-connection postgresql://localhost/mydb \
  --query "SELECT * FROM users WHERE email='test@example.com'"

export ANTHROPIC_API_KEY='your-key'
python cli.py \
  --db-connection postgresql://localhost/mydb \
  --query "SELECT * FROM users WHERE email='test@example.com'" \
  --real
```

### Autonomous Agent

```bash
export ANTHROPIC_API_KEY='your-key'
export DB_CONNECTION='postgresql://localhost/testdb'
python run_agent.py
```

### Python API

```python
from src import ExplainAnalyzer, SemanticTranslator, SQLOptimizationAgent

analyzer = ExplainAnalyzer()
bottlenecks = analyzer.analyze(explain_json)

translator = SemanticTranslator()
feedback = translator.translate(bottlenecks, constraints)

agent = SQLOptimizationAgent(db_connection="postgresql://localhost/mydb")
result = await agent.optimize(query="SELECT * FROM users WHERE id = 1")
```

## How It Works

### Two-Stage Pipeline

The **Analyzer** parses PostgreSQL EXPLAIN JSON output and identifies bottlenecks programmatically: sequential scans on large tables, high-cost operations, planner estimate errors, and inefficient joins. It operates deterministically using rule-based detection.

The **Semanticizer** translates technical analysis into natural language feedback using Claude. It provides actionable suggestions like CREATE INDEX statements or query rewrites, assigns priority levels, and determines pass/fail status based on cost constraints.

### Autonomous Agent

The ReAct-style optimization loop uses Claude Sonnet to iteratively improve queries. Each iteration analyzes the execution plan, plans an optimization action, executes DDL or rewrites the query, validates the improvement, and repeats until the query is optimized or reaches max iterations. The agent includes stagnation detection to avoid infinite loops.

### Safety Features

sql_exenv uses a two-phase EXPLAIN strategy: it estimates cost first, then runs ANALYZE only if safe. Statement timeouts prevent runaway queries, cost thresholds gate expensive operations, and HypoPG enables hypothetical index validation without actual DDL impact.

## Project Structure

```
sql_exenv/
├── src/                      # Core system
│   ├── __init__.py          # Package initialization
│   ├── analyzer.py          # EXPLAIN plan analysis
│   ├── semanticizer.py      # Semantic translation
│   ├── agent.py             # Autonomous optimization agent
│   └── actions.py           # Action definitions
│
├── tests/                   # Test suite
│   ├── test_analyzer.py
│   ├── test_agent.py
│   ├── test_e2e.py
│   └── test_edge_cases.py
│
├── examples/                # Sample queries and schemas
│   ├── queries/
│   ├── schemas/
│   └── README.md
│
├── cli.py                   # Interactive CLI
├── run_agent.py             # Autonomous agent demo
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
export DB_CONNECTION="postgresql://localhost/mydb"
```

All EXPLAIN operations are read-only and execute no user queries.

## Dependencies

- `psycopg2-binary` - PostgreSQL database connectivity
- `anthropic` - Claude API integration for semantic translation
- `pydantic` - Data validation and serialization
- `sqlparse` - SQL parsing and analysis

## License

MIT License - see LICENSE file for details.
