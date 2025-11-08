# SQL Execution Environment (sql_exenv)

Autonomous PostgreSQL query optimization system that translates EXPLAIN plans into actionable feedback for AI agents.

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## Overview

sql_exenv bridges the gap between PostgreSQL's technical execution metrics and AI agent decision-making. It analyzes query plans, identifies performance bottlenecks, and provides semantic feedback that enables autonomous optimization loops.

**Key capabilities:**
- Automated EXPLAIN plan analysis with bottleneck detection
- Semantic translation of technical metrics to natural language
- Autonomous optimization agent with ReAct-style planning
- Safety controls for production environments (timeouts, cost thresholds)
- HypoPG integration for hypothetical index validation

## Installation

```bash
# Clone repository
git clone https://github.com/yudduy/sql_exenv.git
cd sql_exenv

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your credentials
```

## Quick Start

### CLI Analysis

```bash
# Analyze query with mock translator (no API key required)
python cli.py \
  --db-connection postgresql://localhost/mydb \
  --query "SELECT * FROM users WHERE email='test@example.com'"

# With real LLM translator
export ANTHROPIC_API_KEY='your-key'
python cli.py \
  --db-connection postgresql://localhost/mydb \
  --query "SELECT * FROM users WHERE email='test@example.com'" \
  --real
```

### Autonomous Agent

```bash
# Run autonomous optimization loop
export ANTHROPIC_API_KEY='your-key'
export DB_CONNECTION='postgresql://localhost/testdb'
python run_agent.py
```

### Python API

```python
from src import ExplainAnalyzer, SemanticTranslator, SQLOptimizationAgent

# Analyze EXPLAIN plan
analyzer = ExplainAnalyzer()
bottlenecks = analyzer.analyze(explain_json)

# Translate to natural language
translator = SemanticTranslator()
feedback = translator.translate(bottlenecks, constraints)

# Run autonomous optimization
agent = SQLOptimizationAgent(db_connection="postgresql://localhost/mydb")
result = await agent.optimize(query="SELECT * FROM users WHERE id = 1")
```

## Architecture

### Two-Stage Pipeline

**Stage 1: Analyzer** - Parses PostgreSQL EXPLAIN JSON output and identifies bottlenecks programmatically:
- Sequential scans on large tables
- High-cost operations
- Planner estimate errors
- Inefficient joins and sorts

**Stage 2: Semanticizer** - Translates technical analysis into natural language feedback:
- Actionable suggestions (CREATE INDEX, query rewrites)
- Priority levels and severity classification
- Pass/fail status based on cost constraints

### Autonomous Agent

ReAct-style optimization loop using Claude Sonnet:
1. Analyze query execution plan
2. Plan optimization action
3. Execute DDL or query rewrite
4. Validate improvement
5. Iterate until optimized or max iterations reached

### Safety Features

- Two-phase EXPLAIN strategy (estimate first, then ANALYZE if safe)
- Statement timeout protection
- Cost threshold gates for expensive operations
- HypoPG for risk-free index validation

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
│   ├── test_demo.py
│   └── test_golden_set.py
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

1. **Phase 1**: `EXPLAIN (FORMAT JSON)` - Fast cost estimation without execution
2. **Phase 2**: `EXPLAIN (ANALYZE, FORMAT JSON)` - Full analysis with timeout protection, only if estimated cost is below threshold

Recommended production settings:
- `max_time_ms`: 60000 (60 seconds)
- `analyze_cost_threshold`: 10000000

## HypoPG Integration

HypoPG enables risk-free index validation:

1. Creates hypothetical index (no disk usage or DDL impact)
2. Re-runs EXPLAIN to capture optimized plan
3. Reports cost improvement percentage

**Requirements:**
- PostgreSQL extension: `CREATE EXTENSION IF NOT EXISTS hypopg`
- Sufficient privileges for extension creation

## Configuration

```bash
# Set environment variables
export ANTHROPIC_API_KEY="your-key-here"
export DB_CONNECTION="postgresql://localhost/mydb"

# Or use .env file
cp .env.example .env
# Edit .env with your credentials
```

**Security notes:**
- No hardcoded credentials
- Read-only EXPLAIN operations (no query execution)
- Validate connection strings before use

## Dependencies

- `psycopg2-binary` - PostgreSQL database connectivity
- `anthropic` - Claude API integration for semantic translation
- `pydantic` - Data validation and serialization
- `sqlparse` - SQL parsing and analysis

## License

MIT License - see LICENSE file for details.
