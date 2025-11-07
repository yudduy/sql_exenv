# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

**Agentic DBA** is an AI-powered PostgreSQL query optimization system that serves as a semantic bridge between PostgreSQL's technical EXPLAIN output and AI agents. It enables autonomous iterative optimization through a two-phase architecture:

1. **Phase 1 (Smart Tool)**: Analyzes queries and provides actionable feedback via `exev.py`
2. **Phase 2 (Autonomous Agent)**: Iteratively optimizes queries using a ReAct loop with Claude Sonnet 4.5

## Core Architecture

```
┌────────────────────────────────────────────────────────────┐
│                    PHASE 2: AGENT                          │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  SQLOptimizationAgent (src/agentic_dba/agent.py)     │  │
│  │                                                       │  │
│  │  ReAct Loop (max 5 iterations):                      │  │
│  │    1. ANALYZE  → Call Phase 1 tool                   │  │
│  │    2. PLAN     → Claude Sonnet 4.5 (extended think)  │  │
│  │    3. ACT      → Execute DDL or rewrite              │  │
│  │    4. VALIDATE → Re-analyze performance              │  │
│  │    5. REPEAT   → Until PASS or max iterations        │  │
│  └──────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────┘
                          ↓ uses
┌────────────────────────────────────────────────────────────┐
│                   PHASE 1: SMART TOOL                      │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  QueryOptimizationTool (src/agentic_dba/mcp_server.py)│ │
│  │                                                       │  │
│  │  SQL Query → EXPLAIN → Model 1 → Model 2 → Feedback  │  │
│  │              ↓          ↓          ↓         ↓        │  │
│  │          PostgreSQL  Analyzer  Semanticizer Agent    │  │
│  │                     (Technical) (Natural Lang)       │  │
│  └──────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────┘
```

### Two-Model Pipeline (Phase 1)

**Model 1: ExplainAnalyzer** (`src/agentic_dba/analyzer.py`)
- **Purpose**: Technical analysis of EXPLAIN plans
- **Input**: PostgreSQL EXPLAIN JSON output
- **Output**: Structured bottleneck data (node types, costs, rows, severity)
- **Detection Rules**:
  - Sequential Scans on large tables (>10k rows)
  - High-cost nodes (>70% of total cost)
  - Planner estimate errors (actual/estimated > 5x)
  - Nested Loop Joins on large result sets
  - Sort operations spilling to disk
- **Key Method**: `analyze(explain_output) -> Dict[str, Any]`
- **No LLM**: Pure Python rule-based analysis

**Model 2: SemanticTranslator** (`src/agentic_dba/semanticizer.py`)
- **Purpose**: Translate technical metrics → natural language feedback
- **Input**: Model 1 output + constraints
- **Output**: `{status, reason, suggestion, priority}`
- **Uses**: Claude Haiku (default) or Sonnet
- **Key Method**: `translate(technical_analysis, constraints) -> Dict[str, Any]`
- **Mock Mode**: `MockTranslator` uses rule-based logic (no API key needed)

### ReAct Loop (Phase 2)

**SQLOptimizationAgent** (`src/agentic_dba/agent.py`)
- **Purpose**: Autonomous iterative query optimization
- **Model**: Claude Sonnet 4.5 (`claude-sonnet-4-5-20250929`)
- **Extended Thinking**: 8000 token budget for deep reasoning
- **Action Types** (defined in `src/agentic_dba/actions.py`):
  1. `CREATE_INDEX` - Execute index creation DDL
  2. `REWRITE_QUERY` - Modify query structure
  3. `RUN_ANALYZE` - Update table statistics
  4. `DONE` - Optimization complete (success)
  5. `FAILED` - Cannot optimize further (failure)

**Workflow**:
```python
for iteration in range(max_iterations):
    # 1. Analyze with Phase 1 tool
    feedback = await optimization_tool.optimize_query(...)

    # 2. Plan action with LLM
    action = await _plan_action(feedback)  # Uses extended thinking

    # 3. Check completion
    if action.type == DONE:
        return Solution(success=True)

    # 4. Execute action
    if action.type == CREATE_INDEX:
        await _execute_ddl(action.ddl)
    elif action.type == REWRITE_QUERY:
        current_query = action.new_query
```

## Common Commands

### Development Setup

```bash
# Install package in editable mode
pip install -e .

# Install with development dependencies
pip install -e ".[dev]"
```

### Testing

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=src/agentic_dba --cov-report=html

# Run integration tests (requires PostgreSQL)
pytest -m integration

# Run BIRD-CRITIC golden set validation
pytest -m golden
```

### Code Quality

```bash
# Format code with black
black src/ tests/

# Lint with ruff
ruff check src/ tests/

# Type checking with mypy
mypy src/
```

### Running Phase 1 (Smart Tool)

```bash
# Basic analysis with mock translator (no API key needed)
python exev.py \
  -q "SELECT * FROM users WHERE email='alice@example.com'" \
  -d postgresql://localhost/mydb \
  --max-cost 1000

# With real LLM translator (requires ANTHROPIC_API_KEY)
export ANTHROPIC_API_KEY='your-key'
python exev.py -q "..." -d postgresql://... --real

# With HypoPG proof
python exev.py \
  -q "SELECT * FROM orders WHERE status='pending'" \
  -d postgresql://user:pass@localhost/db \
  --max-cost 1000 \
  --max-time-ms 60000 \
  --analyze-cost-threshold 10000000 \
  --use-hypopg \
  --real \
  -o output.json
```

### Running Phase 2 (Autonomous Agent)

```bash
# Demo: Single query optimization
export ANTHROPIC_API_KEY='your-key'
export DB_CONNECTION='postgresql://localhost/testdb'
python demo_agent.py

# BIRD-CRITIC evaluation (10 tasks)
python -m agentic_dba.bird_critic_runner \
  --dataset ./mini_dev/bird-critic-flash.json \
  --db-connection postgresql://localhost/bird_db \
  --limit 10 \
  --output results.json

# Concurrent evaluation (3 tasks in parallel)
python -m agentic_dba.bird_critic_runner \
  --dataset ./mini_dev/bird-critic-flash.json \
  --db-connection postgresql://localhost/bird_db \
  --max-concurrent 3 \
  --output results.json
```

### BIRD Benchmark Setup

```bash
# Setup PostgreSQL databases
./scripts/setup/setup_bird_databases.sh

# Validate setup
python tests/test_bird_setup.py
```

## Architecture Patterns

### Mock vs Real LLM Mode

The system supports two modes:

**Mock Mode** (default):
- Uses `MockTranslator` with rule-based logic
- No API key required
- Fast and deterministic

**Real Mode**:
- Uses Claude API
- Requires `ANTHROPIC_API_KEY`
- Use `--real` flag in CLI

```python
# Mock mode (no API key)
tool = QueryOptimizationTool(use_mock_translator=True)

# Real mode
tool = QueryOptimizationTool(use_mock_translator=False)
```

### Two-Phase EXPLAIN Strategy

Safe and fast analysis through two phases:

**Phase 1: Dry Run** (`EXPLAIN` without `ANALYZE`)
- Instant execution
- Gets estimated plan cost
- No actual query execution

**Phase 2: Conditional Analyze** (`EXPLAIN ANALYZE`)
- Only runs if estimated cost ≤ `analyze_cost_threshold`
- Protected by `statement_timeout`
- Gets actual execution metrics

```python
constraints = {
    "max_cost": 10000.0,                 # Feedback threshold
    "max_time_ms": 60000,                 # 60s statement timeout
    "analyze_cost_threshold": 5_000_000   # Skip ANALYZE if cost > this
}
```

### Extended Thinking Configuration

Phase 2 agent uses Claude's extended thinking mode:

```python
agent = SQLOptimizationAgent(
    use_extended_thinking=True,
    extended_thinking_budget=8000  # Tokens for reasoning
)

# IMPORTANT: Temperature must be 1.0 with extended thinking
response = client.messages.create(
    model="claude-sonnet-4-5-20250929",
    temperature=1.0,  # Required
    thinking={"type": "enabled", "budget_tokens": 8000}
)
```

**Thinking Budget Recommendations**:
- Simple queries: 2000-4000 tokens
- Medium complexity: 4000-8000 tokens
- Complex queries: 8000-16000 tokens

### HypoPG Proof System

When `--use-hypopg` is enabled, validates index suggestions:

1. Creates hypothetical index via HypoPG (no disk usage)
2. Re-runs EXPLAIN to get "after" plan
3. Compares before/after costs
4. Cleans up hypothetical index

**Important**: HypoPG indexes are session-scoped.

### Action Parsing

The agent parses LLM responses with multiple fallback strategies:

```python
def parse_action_from_llm_response(response: str) -> Action:
    # 1. Try to extract JSON block
    # 2. Try to parse raw JSON
    # 3. Fallback: Parse action type from text
    # 4. Final fallback: FAILED action
```

### Async/Await Patterns

All I/O operations use async/await:

```python
async def main():
    tool = QueryOptimizationTool()
    result = await tool.optimize_query(...)

asyncio.run(main())
```

## Important Conventions

### Constraint Handling

Constraints flow through the entire pipeline:

- **`max_cost`**: Used by Model 2 for status determination
- **`max_time_ms`**: Used for `statement_timeout`
- **`analyze_cost_threshold`**: Decides whether to run ANALYZE
- **`use_hypopg`**: Enables HypoPG proof

### EXPLAIN Plan Format Handling

PostgreSQL can return two formats:

```python
# Format 1: List
[{"Plan": {...}, "Execution Time": 123.4}]

# Format 2: Dict
{"Plan": {...}, "Execution Time": 123.4}

# Analyzer normalizes both
if isinstance(plan_data, list):
    root = plan_data[0]
else:
    root = plan_data
```

### Index Suggestion Extraction

Regex patterns extract index suggestions from feedback:

```python
# Pattern 1: CREATE INDEX statement
pattern = r'CREATE\s+INDEX\s+\w+\s+ON\s+(\w+)\s*\(([^)]+)\)'

# Pattern 2: "index on table(column)"
pattern = r'index\s+on\s+(\w+)\s*\(([^)]+)\)'
```

**Hallucination Prevention**: Model 1's suggestion is preferred over Model 2's.

### Correctness Validation

For BIRD-CRITIC tasks with ground truth:

```python
if task.solution_sql:
    correctness = self._check_correctness(query, task.solution_sql, db_conn)
    if not correctness["matches"]:
        feedback["status"] = "fail"
```

### Schema Information for Rewrites

The agent extracts schema info to prevent column name hallucination:

```python
def _get_schema_info(db_conn_string, query):
    # 1. Extract table names via regex
    tables = re.findall(r'(?:FROM|JOIN)\s+(\w+)', query)
    
    # 2. Query information_schema
    # 3. Format as: "table: col1 (type1), col2 (type2), ..."
```

## Important Gotchas

### Extended Thinking Temperature

Temperature **must** be 1.0 with extended thinking:

```python
# ❌ Wrong
response = client.messages.create(temperature=0, thinking={...})

# ✓ Correct
response = client.messages.create(temperature=1.0, thinking={...})
```

### LLM Response Content Blocks

Filter for text blocks only:

```python
# ❌ Wrong
response_text = response.content[0].text

# ✓ Correct
text_parts = [b.text for b in response.content if b.type == "text"]
response_text = "\n".join(text_parts)
```

### HypoPG Session Scope

New connection per task to avoid index accumulation:

```python
# ❌ Wrong: Reusing connection
conn = psycopg2.connect(db_string)
for task in tasks:
    run_hypopg_proof(conn, task)  # Indexes accumulate!

# ✓ Correct: New connection per task
for task in tasks:
    conn = psycopg2.connect(db_string)
    run_hypopg_proof(conn, task)
    conn.close()  # Auto-cleanup
```

### Cost vs Execution Time

Don't confuse:
- **Total Cost**: Estimated cost units (arbitrary scale)
- **Execution Time**: Actual milliseconds from EXPLAIN ANALYZE

```python
estimated_cost = tech["total_cost"]           # Cost units
actual_time_ms = tech.get("execution_time_ms")  # Milliseconds
```

### Action Attributes Must Match Type

```python
# ✓ Correct
Action(type=CREATE_INDEX, ddl="CREATE INDEX ...", reasoning="...")
Action(type=REWRITE_QUERY, new_query="SELECT ...", reasoning="...")

# ❌ Wrong
Action(type=CREATE_INDEX, reasoning="...")  # Missing ddl!
```

## Output Formats

### Phase 1 Output

```json
{
  "success": true,
  "feedback": {
    "status": "fail",
    "reason": "Sequential Scan detected on large table",
    "suggestion": "CREATE INDEX idx_users_email ON users(email);",
    "priority": "HIGH"
  },
  "technical_analysis": {
    "total_cost": 55072.5,
    "execution_time_ms": 234.5,
    "bottlenecks": [...]
  }
}
```

### Phase 2 Output

```json
{
  "final_query": "SELECT * FROM users WHERE email='alice@example.com'",
  "success": true,
  "reason": "Query optimized successfully",
  "actions": [
    {
      "type": "CREATE_INDEX",
      "reasoning": "Sequential Scan detected...",
      "ddl": "CREATE INDEX idx_users_email ON users(email);"
    },
    {
      "type": "DONE",
      "reasoning": "Query now uses Index Scan"
    }
  ]
}
```

## Key Files

- **`exev.py`**: Production CLI for Phase 1
- **`src/agentic_dba/analyzer.py`**: Model 1 (technical analysis)
- **`src/agentic_dba/semanticizer.py`**: Model 2 (semantic translation)
- **`src/agentic_dba/mcp_server.py`**: Pipeline orchestration
- **`src/agentic_dba/agent.py`**: Phase 2 autonomous agent
- **`src/agentic_dba/actions.py`**: Action types and parsing
- **`src/agentic_dba/bird_critic_runner.py`**: Benchmark evaluation

## Testing Patterns

### Unit Tests
```python
def test_seq_scan_detection():
    analyzer = ExplainAnalyzer()
    plan = load_fixture('seq_scan.json')
    result = analyzer.analyze(plan)
    assert len(result['bottlenecks']) > 0
```

### Integration Tests
```python
@pytest.mark.integration
async def test_optimize_query():
    tool = QueryOptimizationTool(use_mock_translator=True)
    result = await tool.optimize_query(...)
    assert result["success"] is True
```

## Performance Considerations

### API Costs

- **Phase 1 only**: ~$0.001 per query
- **Phase 2 (3 iterations)**: ~$0.10 per task
- **Flash-Exp (200 tasks)**: ~$20

### Optimization Tips

1. Use mock mode for testing
2. Lower thinking budget for simple queries
3. Limit max iterations
4. Use concurrent evaluation carefully
5. Set high `analyze_cost_threshold`

## Known Limitations

1. PostgreSQL only (MySQL/SQL Server not supported)
2. Simple schema extraction (regex-based)
3. HypoPG requires CREATE EXTENSION privilege
4. Query rewrite quality depends on LLM
5. Simple correctness validation (tuple comparison)
