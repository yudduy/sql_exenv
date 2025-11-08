# SQL Execution Environment for SQL Optimization Agents MCP

> **PostgreSQL query optimization MCP server with semantic feedback for AI agents**

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

---

## Overview

A Model Context Protocol (MCP) server that provides PostgreSQL query optimization capabilities for AI agents. The system analyzes queries through EXPLAIN plans, identifies performance bottlenecks, and provides semantic feedback for optimization. It bridges the gap between technical execution metrics and agent-ready suggestions.

## Core Features

- **EXPLAIN Plan Analysis**: Identifies performance bottlenecks including sequential scans, high-cost nodes, and nested loop joins
- **Semantic Translation**: Converts technical analysis into natural language feedback with specific SQL suggestions
- **MCP Integration**: First-class support for Model Context Protocol with Claude Desktop and other MCP-compatible agents
- **HypoPG Support**: Validates index suggestions using hypothetical indexes without database modifications
- **Safety Controls**: Configurable cost thresholds and statement timeouts for safe analysis

## Installation

### Prerequisites

- Python 3.10+
- PostgreSQL 14+
- MCP client (Claude Desktop or compatible)

### Setup

```bash
# Clone repository
git clone https://github.com/yudduy/sql_exenv.git
cd sql_exev

# Install dependencies
pip install -e .

# Configure environment
cp .env.example .env
# Edit .env with your configuration
```

### Configuration

Set environment variables in `.env`:

```bash
# Required for semantic translation
ANTHROPIC_API_KEY=your_anthropic_api_key

# Optional: Use mock translator for testing
USE_MOCK_TRANSLATOR=true
```

## MCP Server Integration

### Claude Desktop Configuration

Add to your Claude Desktop configuration:

```json
{
  "mcpServers": {
    "postgres-optimizer": {
      "command": "python",
      "args": ["-m", "src.mcp_server"],
      "env": {
        "ANTHROPIC_API_KEY": "your-key-here"
      }
    }
  }
}
```

### Available Tools

#### `optimize_postgres_query`

Analyzes a PostgreSQL query and returns optimization feedback.

**Parameters:**
- `sql_query` (string, required): The PostgreSQL SELECT query to optimize
- `db_connection_string` (string, required): PostgreSQL connection string
- `constraints` (object, optional): Performance constraints
  - `max_cost` (number): Maximum acceptable query cost
  - `max_time_ms` (number): Maximum execution time in milliseconds

**Example Usage:**
```json
{
  "sql_query": "SELECT * FROM users WHERE email = 'test@example.com'",
  "db_connection_string": "postgresql://localhost/mydb",
  "constraints": {
    "max_cost": 1000.0,
    "max_time_ms": 60000
  }
}
```

## Architecture

### Two-Stage Analysis Pipeline

1. **Technical Analyzer**: Parses PostgreSQL EXPLAIN JSON output to identify bottlenecks
2. **Semantic Translator**: Converts technical analysis into natural language suggestions

### Analysis Process

```
Query Input → EXPLAIN ANALYZE → Technical Analysis → Semantic Translation → Agent Feedback
```

### Supported Bottleneck Detection

- Sequential scans on large tables (>10,000 rows)
- High-cost nodes (>70% of total cost)
- Planner estimate errors (actual/estimated > 5x)
- Nested loop joins on large result sets
- Sort operations spilling to disk

## Usage Examples

### Direct Python Integration

```python
import asyncio
from src.mcp_server import QueryOptimizationTool

async def optimize_query():
    tool = QueryOptimizationTool(use_mock_translator=True)
    
    result = await tool.optimize_query(
        sql_query="SELECT * FROM users WHERE email = 'test@example.com'",
        db_connection_string="postgresql://localhost/mydb",
        constraints={"max_cost": 1000.0}
    )
    
    return result

# Run optimization
result = asyncio.run(optimize_query())
print(f"Status: {result['feedback']['status']}")
print(f"Suggestion: {result['feedback']['suggestion']}")
```

### HypoPG Index Validation

Enable HypoPG proof for index suggestions:

```python
result = await tool.optimize_query(
    sql_query="SELECT * FROM orders WHERE customer_id = 123",
    db_connection_string="postgresql://localhost/mydb",
    constraints={
        "max_cost": 1000.0,
        "use_hypopg": True  # Enable hypothetical index validation
    }
)

# Access HypoPG proof results
if "hypopg_proof" in result:
    proof = result["hypopg_proof"]
    print(f"Cost improvement: {proof['improvement']:.1f}%")
```

## Response Format

The optimization tool returns structured feedback:

```json
{
  "success": true,
  "feedback": {
    "status": "pass|fail|warning",
    "reason": "Natural language explanation of issues",
    "suggestion": "Specific SQL command for improvement",
    "priority": "HIGH|MEDIUM|LOW"
  },
  "technical_analysis": {
    "bottlenecks": [...],
    "total_cost": 1234.56,
    "analysis_details": {...}
  },
  "explain_plan": {...}
}
```

## Safety and Performance

### Two-Phase Execution

1. **Dry Run**: Fast EXPLAIN without ANALYZE to estimate cost
2. **Full Analysis**: EXPLAIN ANALYZE with timeout only if estimated cost is reasonable

### Recommended Constraints

```bash
# Safe defaults for production
max_cost: 10000.0
max_time_ms: 60000
analyze_cost_threshold: 10000000
```

### HypoPG Requirements

- HypoPG extension: `CREATE EXTENSION IF NOT EXISTS hypopg`
- Sufficient privileges for extension creation
- HypoPG provides risk-free index validation (no disk usage, no DDL impact)

## Development

### Testing

```bash
# Run unit tests
pytest

# Run with coverage
pytest --cov=src --cov-report=html

# Test MCP server directly
python -m src.mcp_server test
```

### Mock Mode

For development without API keys:

```python
tool = QueryOptimizationTool(use_mock_translator=True)
```

Mock translator uses rule-based logic for generating feedback.

## Project Structure

```
sql_exev/
├── src/                      # Core system
│   ├── __init__.py          # Package initialization
│   ├── analyzer.py          # PostgreSQL EXPLAIN plan analysis
│   ├── semanticizer.py      # Semantic translation engine
│   └── mcp_server.py        # MCP server implementation
│
├── tests/                   # Test suite
│   ├── test_analyzer.py
│   ├── test_demo.py
│   ├── test_exev_features.py
│   └── test_golden_set.py
│
├── examples/                # Usage examples and sample data
│   ├── queries/             # Sample SQL queries
│   ├── schemas/             # Sample database schemas
│   └── scripts/             # Example scripts
│
├── scripts/                 # Utilities
│   └── setup/
│
├── pyproject.toml           # Python packaging configuration
├── requirements.txt         # Dependencies
└── README.md               # This file
```

## Dependencies

- `psycopg2-binary`: PostgreSQL database connectivity
- `anthropic`: Claude API integration for semantic translation
- `mcp`: Model Context Protocol server framework
- `pydantic`: Data validation and serialization
- `sqlparse`: SQL parsing and analysis

## License

MIT License - see LICENSE file for details.

## Contributing

Contributions are welcome. Please ensure all tests pass and follow the existing code style.

## Support

For issues and questions:
- Review the documentation in `docs/`
- Check existing test cases for usage patterns
- Submit issues for bugs or feature requests
