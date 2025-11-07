# Autonomous SQL Optimization Agent (Phase 2)

> **AI-powered autonomous query optimization using Claude Sonnet 4.5 and ReAct pattern**

This is **Phase 2** of the Agentic DBA project: a fully autonomous agent that iteratively optimizes SQL queries without human intervention, designed to beat BIRD-CRITIC benchmark records.

---

## 🎯 What's New in Phase 2

**Phase 1** built the "Smart Tool" (`exev.py`) that analyzes queries and suggests optimizations.

**Phase 2** builds the "Agent Brain" that autonomously:
1. **Analyzes** query performance using the tool
2. **Plans** optimization actions using Claude Sonnet 4.5 with extended thinking
3. **Executes** DDL (CREATE INDEX, ANALYZE, etc.) or query rewrites
4. **Validates** improvements through iterative feedback
5. **Repeats** until optimization goals are met

### Architecture

```
┌──────────────────────────────────────────────────────────┐
│           AUTONOMOUS AGENT (SQLOptimizationAgent)        │
│  ┌────────────────────────────────────────────────────┐  │
│  │         ReAct Loop (max 5 iterations)              │  │
│  │                                                    │  │
│  │  1. ANALYZE  → Call exev.py tool                  │  │
│  │  2. PLAN     → Claude Sonnet 4.5 + extended thinking│  │
│  │  3. ACT      → Execute DDL or rewrite              │  │
│  │  4. VALIDATE → Re-analyze performance              │  │
│  │  5. REPEAT   → Until PASS or FAILED                │  │
│  └────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────┘
                          ↓
         Uses Phase 1 Tool (QueryOptimizationTool)
                          ↓
            PostgreSQL + EXPLAIN ANALYZE
```

---

## 🚀 Quick Start

### Prerequisites

```bash
# 1. Install dependencies
pip install -e ".[dev]"

# 2. Set API key
export ANTHROPIC_API_KEY='your-key-here'

# 3. Set database connection
export DB_CONNECTION='postgresql://user:pass@localhost/testdb'
```

### Demo 1: Simple Autonomous Optimization

```bash
python demo_agent.py
```

**What it does:**
- Takes a slow query: `SELECT * FROM users WHERE email = 'alice@example.com'`
- Agent analyzes: "Sequential Scan detected, cost 55,072"
- Agent plans: "CREATE INDEX on email column"
- Agent executes: `CREATE INDEX idx_users_email ON users(email)`
- Agent validates: "Index Scan now used, cost 14.2, optimization complete!"

**Expected Output:**
```
=== Iteration 1/3 ===
Analyzing query performance...
Planning next action...
Action: CREATE_INDEX
Reasoning: Feedback indicates Sequential Scan on users table...
Executing CREATE_INDEX...
✓ Executed: CREATE INDEX idx_users_email ON users(email);

=== Iteration 2/3 ===
Analyzing query performance...
Planning next action...
Action: DONE
Reasoning: Feedback status is 'pass', query is now optimized

=== SOLUTION ===
✓ Success:       True
✓ Reason:        Query optimized successfully
✓ Iterations:    2
✓ Final Query:   SELECT * FROM users WHERE email = 'alice@example.com'
```

---

## 📊 BIRD-CRITIC Benchmark Evaluation

### What is BIRD-CRITIC?

- **600 real-world SQL debugging tasks** from NeurIPS 2025
- **Efficiency-focused subset**: Query optimization using QEP evaluation
- **Current SOTA**: 34.5% (o3-mini)
- **Human experts**: 83-90%
- **Our Goal**: 45-50% success rate

### Dataset Access

Download from Hugging Face:

```bash
# Option 1: Use existing mini_dev dataset (if available)
ls mini_dev/

# Option 2: Download BIRD-CRITIC from Hugging Face
pip install datasets
python -c "
from datasets import load_dataset
ds = load_dataset('birdsql/bird-critic-1.0-flash-exp')
print(ds)
"
```

### Run Evaluation (Flash-Exp: 200 tasks)

```bash
python -m agentic_dba.bird_critic_runner \
  --dataset ./mini_dev/bird-critic-flash.json \
  --db-connection postgresql://localhost/bird_db \
  --limit 10 \
  --output results.json
```

**Expected Output:**
```
=== BIRD-CRITIC Benchmark Evaluation ===
Dataset: ./mini_dev/bird-critic-flash.json
Database: postgresql://localhost/bird_db
Max Concurrent: 1

Loaded 10 tasks

[1/10] Evaluating task_001...
  ✓ task_001: Query optimized successfully (8.3s)
[2/10] Evaluating task_002...
  ✗ task_002: Max iterations reached (25.1s)
...

============================================================
EVALUATION SUMMARY
============================================================
Total Tasks:      10
Successful:       7 (70.0%)
Failed:           3
Avg Time/Task:    12.4s
Avg Iterations:   2.3
Total Time:       124.2s

Action Distribution:
  CREATE_INDEX        : 8
  DONE                : 7
  FAILED              : 3
  REWRITE_QUERY       : 1
============================================================
```

### Full Evaluation (530 tasks)

```bash
# WARNING: This takes ~2 hours and costs ~$50 in API calls
python -m agentic_dba.bird_critic_runner \
  --dataset ./mini_dev/bird-critic-postgresql.json \
  --db-connection postgresql://localhost/bird_db \
  --output full_results.json \
  --max-concurrent 3  # Parallel execution
```

---

## 🧠 How the Agent Works

### Action Types

The agent can take 5 types of actions:

1. **CREATE_INDEX** - Execute index creation DDL
   ```sql
   CREATE INDEX idx_users_email ON users(email);
   ```

2. **REWRITE_QUERY** - Modify query structure
   ```sql
   -- Before: SELECT *
   -- After:  SELECT id, name, email
   ```

3. **RUN_ANALYZE** - Update table statistics
   ```sql
   ANALYZE users;
   ```

4. **DONE** - Optimization complete (success)

5. **FAILED** - Cannot optimize further (failure)

### Planning with Extended Thinking

The agent uses **Claude Sonnet 4.5** with **extended thinking** mode:

```python
response = anthropic_client.messages.create(
    model="claude-sonnet-4-5-20250929",
    thinking={
        "type": "enabled",
        "budget_tokens": 8000  # Deep reasoning
    },
    messages=[...]
)
```

**Benefits:**
- Better decision-making for complex queries
- Considers multiple optimization strategies
- Avoids premature optimization
- Knows when to stop (diminishing returns)

### Feedback Loop

```
┌─────────────────────────────────────────────────┐
│  Iteration N                                    │
├─────────────────────────────────────────────────┤
│                                                 │
│  1. Run exev.py                                 │
│     → Feedback: {status, reason, suggestion}    │
│                                                 │
│  2. LLM Planning Prompt:                        │
│     "Status: FAIL                               │
│      Reason: Seq Scan on 100K rows              │
│      Suggestion: CREATE INDEX idx_email         │
│                                                 │
│      What action should you take?"              │
│                                                 │
│  3. LLM Response (JSON):                        │
│     {                                           │
│       "action": "CREATE_INDEX",                 │
│       "reasoning": "Index will eliminate scan", │
│       "ddl": "CREATE INDEX ...",                │
│       "confidence": 0.95                        │
│     }                                           │
│                                                 │
│  4. Execute DDL                                 │
│                                                 │
│  5. Next iteration → Validate                   │
│                                                 │
└─────────────────────────────────────────────────┘
```

---

## 🛠️ API Usage

### Python API

```python
import asyncio
from agentic_dba import SQLOptimizationAgent, BIRDCriticTask

async def optimize_query():
    # Define task
    task = BIRDCriticTask(
        task_id="custom_001",
        db_id="production",
        buggy_sql="SELECT * FROM orders WHERE status = 'pending'",
        user_query="Get all pending orders",
        efficiency=True
    )

    # Initialize agent
    agent = SQLOptimizationAgent(
        max_iterations=5,
        timeout_per_task_seconds=120,
        use_extended_thinking=True
    )

    # Run optimization
    solution = await agent.solve_task(
        task=task,
        db_connection_string="postgresql://localhost/mydb",
        constraints={
            "max_cost": 10000.0,
            "max_time_ms": 30000
        }
    )

    # Check results
    print(f"Success: {solution.success}")
    print(f"Iterations: {solution.total_iterations()}")
    for action in solution.actions:
        print(f"  - {action.type.value}: {action.reasoning}")

asyncio.run(optimize_query())
```

### Configuration Options

```python
SQLOptimizationAgent(
    max_iterations=5,              # Stop after N attempts
    timeout_per_task_seconds=120,  # Total timeout per task
    use_extended_thinking=True,    # Enable deep reasoning
    extended_thinking_budget=8000  # Tokens for thinking (1024-64000)
)
```

---

## 📈 Performance Targets

### BIRD-CRITIC Benchmarks

| Dataset | Tasks | Current SOTA | Our Target | Status |
|---------|-------|--------------|------------|--------|
| Flash-Exp | 200 | 34.5% | **45%** | 🎯 In Progress |
| PostgreSQL | 530 | 34.5% | **50%** | 📅 Planned |
| Efficiency Subset | ~100 | ~40% (est) | **70%+** | 🎯 High Confidence |

### Why We Can Win

1. **Domain-specialized**: Built specifically for SQL optimization (not general debugging)
2. **Two-model pipeline**: Technical accuracy (Analyzer) + Semantic reasoning (Semanticizer)
3. **HypoPG proof**: Validates index improvements before committing
4. **Extended thinking**: Better decision-making than standard tool-use models
5. **Iterative refinement**: Can retry and adapt, unlike one-shot models

---

## 🧪 Testing

### Unit Tests

```bash
# Test action parsing
pytest tests/test_agent.py::test_action_parsing -v

# Test planning logic
pytest tests/test_agent.py::test_agent_planning -v
```

### Integration Tests

```bash
# Test full optimization loop
pytest tests/test_agent_integration.py -v
```

### Benchmark Smoke Test

```bash
# Quick validation on 5 tasks
python -m agentic_dba.bird_critic_runner \
  --dataset ./mini_dev/bird-critic-flash.json \
  --db-connection postgresql://localhost/bird_db \
  --limit 5
```

---

## 🔧 Advanced Usage

### Custom Constraints

```python
solution = await agent.solve_task(
    task=task,
    db_connection_string=db_conn,
    constraints={
        "max_cost": 5000.0,            # Stricter cost limit
        "max_time_ms": 10000,          # 10s timeout
        "analyze_cost_threshold": 1_000_000,  # Lower threshold
        "use_hypopg": True             # Enable HypoPG proof
    }
)
```

### Debugging Mode

```python
# Add verbose logging
import logging
logging.basicConfig(level=logging.DEBUG)

# Use mock translator for testing (no API costs)
from agentic_dba import QueryOptimizationTool
tool = QueryOptimizationTool(use_mock_translator=True)
```

### Batch Evaluation

```bash
# Process multiple datasets in parallel
python -m agentic_dba.bird_critic_runner \
  --dataset ./datasets/*.json \
  --db-connection postgresql://localhost/bird_db \
  --max-concurrent 5  # 5 tasks in parallel
```

---

## 📝 Output Format

### Solution Object

```json
{
  "final_query": "SELECT * FROM users WHERE email = 'alice@example.com'",
  "success": true,
  "reason": "Query optimized successfully",
  "actions": [
    {
      "type": "CREATE_INDEX",
      "reasoning": "Sequential Scan on users table detected...",
      "ddl": "CREATE INDEX idx_users_email ON users(email);",
      "confidence": 0.95
    },
    {
      "type": "DONE",
      "reasoning": "Query now uses Index Scan, cost within limit"
    }
  ],
  "metrics": {
    "total_cost": 14.2,
    "execution_time_ms": 0.8,
    "bottlenecks_found": 0
  }
}
```

### Benchmark Results

```json
{
  "dataset": "./mini_dev/bird-critic-flash.json",
  "total_tasks": 200,
  "total_time_seconds": 2847.3,
  "aggregate": {
    "total_tasks": 200,
    "successful": 92,
    "failed": 108,
    "success_rate": 0.46,
    "avg_time_per_task": 14.2,
    "avg_iterations": 2.3,
    "action_distribution": {
      "CREATE_INDEX": 78,
      "DONE": 92,
      "FAILED": 108,
      "REWRITE_QUERY": 12,
      "RUN_ANALYZE": 5
    }
  },
  "results": [...]
}
```

---

## 🎓 Best Practices

### 1. Start Small

Test on 5-10 tasks before running full evaluation:
```bash
python -m agentic_dba.bird_critic_runner --limit 5
```

### 2. Monitor Costs

Extended thinking costs the same as regular tokens, but:
- **Flash-Exp (200 tasks)**: ~$10-20 with extended thinking
- **Full PostgreSQL (530 tasks)**: ~$40-60

### 3. Use Appropriate Thinking Budget

| Task Complexity | Budget | Use Case |
|----------------|--------|----------|
| Simple (1-2 tables) | 2000-4000 | Basic index suggestions |
| Medium (joins, filters) | 4000-8000 | Multi-index decisions |
| Complex (subqueries, CTEs) | 8000-16000 | Query rewrites |

### 4. Handle Failures Gracefully

```python
if not solution.success:
    print(f"Optimization failed: {solution.reason}")
    # Analyze failure patterns
    for action in solution.actions:
        if action.type == ActionType.FAILED:
            print(f"  Root cause: {action.reasoning}")
```

---

## 🚧 Roadmap

### ✅ Phase 2.1 (Complete)
- [x] Core agent implementation (ReAct loop)
- [x] Action types and parsing
- [x] BIRD-CRITIC runner
- [x] Extended thinking integration

### 🎯 Phase 2.2 (Current)
- [ ] Test on BIRD-CRITIC Flash-Exp subset
- [ ] Tune prompts based on failure analysis
- [ ] Add query rewrite strategies
- [ ] Implement reflection/self-correction

### 📅 Phase 2.3 (Planned)
- [ ] Full PostgreSQL evaluation (530 tasks)
- [ ] Leaderboard submission
- [ ] Performance optimization (reduce API calls)
- [ ] Multi-database support (MySQL, SQL Server)

---

## 🤝 Contributing

See main [README.md](README.md) for contribution guidelines.

---

## 📞 Support

- **Issues**: [GitHub Issues](https://github.com/yourusername/exev_dba/issues)
- **Benchmark Questions**: bird.bench25@gmail.com
- **API Support**: Anthropic docs at docs.anthropic.com

---

## 📚 References

- **Anthropic Building Effective Agents**: https://www.anthropic.com/research/building-effective-agents
- **BIRD-CRITIC Benchmark**: https://bird-critic.github.io/
- **Extended Thinking Docs**: https://docs.anthropic.com/en/docs/build-with-claude/extended-thinking
- **Phase 1 Technical Brief**: [docs/technical-brief.md](docs/technical-brief.md)

---

**Built with ❤️ following Anthropic's best practices for autonomous agents**
