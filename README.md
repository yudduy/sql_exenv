# sql_exenv

PostgreSQL query optimization with correctness validation via metamorphic testing.

## What it does

1. **Validates query correctness** using TLP and NoREC metamorphic testing
2. **Detects performance bottlenecks** via EXPLAIN plan analysis
3. **Suggests optimizations** (indexes, query rewrites)
4. **Runs autonomous optimization loops** with safety controls

LLM-generated SQL often has semantic errors that return wrong results silently. This tool catches those bugs.

## Install

```bash
git clone https://github.com/yudduy/sql_exenv.git
cd sql_exenv
pip install -r requirements.txt
```

Requires Python 3.10+.

## Usage

Start PostgreSQL with sample data:

```bash
docker-compose up -d
export DB_CONNECTION='postgresql://postgres:postgres@localhost:5432/demo'
export ANTHROPIC_API_KEY='your-key'
```

Run CLI:

```bash
python cli.py  # chat mode
python cli.py --query "SELECT * FROM users WHERE email='user5000@example.com'"
python cli.py --query "..." --validate-only  # skip optimization
python cli.py --query "..." --no-validation  # skip validation
```

Run autonomous agent:

```bash
python run_agent.py
```

## Python API

```python
from src.agent import SQLOptimizationAgent

agent = SQLOptimizationAgent()
result = await agent.optimize_query(
    sql="SELECT * FROM users WHERE email='user@example.com'",
    db_connection="postgresql://postgres:postgres@localhost:5432/demo",
)

print(result['success'], result['final_query'])
```

## How it works

**Analyzer**: Parses EXPLAIN JSON, identifies sequential scans, high-cost operations, estimate errors.

**Semanticizer**: Translates analysis to natural language via Claude. Suggests CREATE INDEX or query rewrites.

**Agent**: ReAct-style loop using Claude Sonnet. Iteratively improves queries until optimized or max iterations.

**Safety**: Two-phase EXPLAIN (estimate cost first, run ANALYZE only if safe). Statement timeouts. HypoPG for virtual index testing.

## Testing

```bash
pytest
pytest --cov=src --cov-report=html
```

## Configuration

```bash
export ANTHROPIC_API_KEY="your-key"
export DB_CONNECTION="postgresql://localhost:5432/mydb"
```

Or use a `.env` file.

## License

MIT
