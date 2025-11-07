# BIRD-CRITIC Evaluation Quick Start Guide

## Overview

This guide shows you how to use the BIRD-CRITIC evaluation infrastructure in 5 minutes.

## Prerequisites

```bash
# Install dependencies
pip install psycopg2-binary datasets anthropic mcp pydantic sqlparse pytest

# Download dataset (if not already done)
python scripts/download_bird_critic_dataset.py
```

## 1. Load Dataset

```python
import json

# Load BIRD-CRITIC tasks
def load_tasks(path="BIRD-CRITIC-1/baseline/data/flash_exp_200.jsonl"):
    tasks = []
    with open(path) as f:
        for line in f:
            tasks.append(json.loads(line))
    return tasks

tasks = load_tasks()
print(f"Loaded {len(tasks)} tasks")

# Inspect a task
task = tasks[0]
print(f"Task {task['instance_id']}: {task['query'][:100]}...")
print(f"Database: {task['db_id']}")
print(f"Category: {task['category']}")
print(f"Issue SQL: {task['issue_sql'][0][:80]}...")
```

## 2. Execute Test Cases

```python
from agentic_dba.test_case_runner import TestCaseRunner

# Your database connection
DB_CONN = "postgresql://user:pass@localhost/bird_db"

# Pick a task
task = tasks[0]

# Your predicted SQL (agent's solution)
predicted_sql = "SELECT account_id, MAX(amount) FROM orders GROUP BY account_id"

# Run test case
with TestCaseRunner(DB_CONN) as runner:
    result = runner.execute_test_case(
        task=task,
        predicted_sql=predicted_sql,
        compare_with_issue_sql=True  # Compare with buggy SQL
    )

    if result.passed:
        print("✓ Test passed!")
        pred = result.details['predicted_result']
        print(f"  Rows: {pred['rowcount']}")
        print(f"  Time: {pred['execution_time_ms']:.2f}ms")
    else:
        print(f"✗ Test failed: {result.error}")
```

## 3. Evaluate with Metrics

```python
from agentic_dba.evaluation_metrics import BIRDCriticMetrics

metrics = BIRDCriticMetrics(DB_CONN)

# Automatic metric selection based on task category
result = metrics.evaluate_task(task, predicted_sql)

print(f"Metric: {result.metric}")
print(f"Passed: {result.passed}")
print(f"Score: {result.score:.2f}")

if result.metric == "qep":
    # Efficiency task - show improvements
    details = result.details
    print(f"Cost improvement: {details['cost_improvement_pct']:.1f}%")
    print(f"Time improvement: {details['time_improvement_pct']:.1f}%")
```

## 4. Batch Evaluation

```python
from agentic_dba.evaluation_metrics import batch_evaluate

# Map of task_id -> predicted SQL
predictions = {
    "0": "SELECT account_id FROM orders WHERE amount > 12000",
    "1": "CREATE INDEX idx_orders ON orders(account_id)",
    # ... more predictions
}

# Evaluate all tasks
results = batch_evaluate(
    tasks=tasks[:10],  # First 10 tasks
    predicted_sql_map=predictions,
    db_connection_string=DB_CONN
)

# Aggregate results
total = len(results)
passed = sum(r.passed for r in results)
avg_score = sum(r.score for r in results) / total

print(f"Pass rate: {passed}/{total} ({passed/total*100:.1f}%)")
print(f"Average score: {avg_score:.2f}")
```

## 5. Integration with Agent

```python
from agentic_dba.agent import SQLOptimizationAgent
from agentic_dba.test_case_runner import TestCaseRunner
from agentic_dba.evaluation_metrics import BIRDCriticMetrics

async def evaluate_agent_on_bird_critic():
    # Initialize agent
    agent = SQLOptimizationAgent(
        max_iterations=10,
        use_extended_thinking=True
    )

    # Initialize metrics
    metrics = BIRDCriticMetrics(DB_CONN)

    # Load tasks
    tasks = load_tasks()

    results = []
    for task in tasks[:5]:  # First 5 tasks
        print(f"\nTask {task['instance_id']}: {task['query'][:80]}...")

        # Convert to BIRDCriticTask format
        bird_task = agent.BIRDCriticTask(
            task_id=str(task['instance_id']),
            db_id=task['db_id'],
            buggy_sql=task['issue_sql'][0],
            user_query=task['query'],
            efficiency=task['efficiency']
        )

        # Solve task
        solution = await agent.solve_task(bird_task, DB_CONN)

        # Evaluate solution
        eval_result = metrics.evaluate_task(task, solution.final_query)

        print(f"  Agent: {solution.success}, Score: {eval_result.score:.2f}")

        results.append({
            'task_id': task['instance_id'],
            'agent_success': solution.success,
            'metric_passed': eval_result.passed,
            'score': eval_result.score
        })

    return results

# Run evaluation
import asyncio
results = asyncio.run(evaluate_agent_on_bird_critic())
```

## Common Patterns

### Pattern 1: Test-Driven Development

```python
# 1. Write test case first
task = {
    "instance_id": 999,
    "db_id": "test_db",
    "query": "Find users with high activity",
    "issue_sql": ["SELECT * FROM users WHERE activity > 100"],
    "preprocess_sql": [],
    "clean_up_sql": [],
    "category": "Query"
}

# 2. Develop SQL iteratively
candidate_sql = "SELECT id, name FROM users WHERE activity > 100"

with TestCaseRunner(DB_CONN) as runner:
    result = runner.execute_test_case(task, candidate_sql)

    if not result.passed:
        print(f"Fix this: {result.error}")
        # Iterate...
```

### Pattern 2: Compare Before/After

```python
# Compare original buggy SQL with optimized version
task = tasks[0]
buggy_sql = task['issue_sql'][0]
optimized_sql = "SELECT id FROM users WHERE indexed_column = 'value'"

metrics = BIRDCriticMetrics(DB_CONN, qep_cost_threshold=0.9)

# Evaluate both
buggy_result = metrics.evaluate_task(task, buggy_sql)
optimized_result = metrics.evaluate_task(task, optimized_sql)

print(f"Buggy SQL score: {buggy_result.score:.2f}")
print(f"Optimized SQL score: {optimized_result.score:.2f}")

if optimized_result.score > buggy_result.score:
    print(f"✓ Improvement: {(optimized_result.score - buggy_result.score)*100:.1f}%")
```

### Pattern 3: Debugging Failed Tests

```python
with TestCaseRunner(DB_CONN, auto_rollback=True) as runner:
    result = runner.execute_test_case(task, predicted_sql)

    if not result.passed:
        # Detailed error info
        print(f"Error: {result.error}")
        print(f"Details: {json.dumps(result.details, indent=2)}")

        # Check which step failed
        if 'preprocess_success' not in result.details:
            print("Failed during preprocess")
        elif 'predicted_result' not in result.details:
            print("Failed during predicted SQL execution")
        else:
            print("Failed during cleanup or validation")
```

### Pattern 4: Custom Metrics

```python
from agentic_dba.evaluation_metrics import BIRDCriticMetrics

# Override default thresholds
metrics = BIRDCriticMetrics(
    DB_CONN,
    soft_ex_tolerance=0.001,      # More strict floating-point comparison
    qep_cost_threshold=0.8        # Require 20% improvement instead of 10%
)

# Manual metric selection
result = metrics.evaluate_task(
    task,
    predicted_sql,
    metric_type="qep"  # Force QEP comparison even for Query tasks
)
```

## Verification Commands

```bash
# Verify dataset is downloaded
ls -lh BIRD-CRITIC-1/baseline/data/flash_exp_200.jsonl

# Show dataset statistics
python scripts/verify_bird_critic_infrastructure.py --skip-db-tests

# Test with database (requires setup)
python scripts/verify_bird_critic_infrastructure.py \
  --db-connection "postgresql://localhost/bird_db"

# Run unit tests
pytest tests/test_case_runner_test.py -v
pytest tests/evaluation_metrics_test.py -v

# Run all tests
pytest tests/ -v --tb=short
```

## Troubleshooting

### Error: "No database connection"

```python
# Make sure to use context manager
with TestCaseRunner(DB_CONN) as runner:
    result = runner.execute_test_case(task, sql)
    # Connection is automatically managed
```

### Error: "Dataset not found"

```bash
# Download the dataset first
python scripts/download_bird_critic_dataset.py

# Or specify custom path
python scripts/verify_bird_critic_infrastructure.py \
  --dataset "path/to/custom.jsonl"
```

### Error: "Relation does not exist"

```python
# Check if database has required schemas
# You need to import BIRD database schemas first
# See: BIRD-CRITIC-1/baseline/data/flash_schema.jsonl
```

### Slow Execution

```python
# Use connection pooling for batch evaluation
# Or limit concurrent connections
runner = TestCaseRunner(
    DB_CONN,
    auto_rollback=True  # Faster with rollback vs commit
)
```

## Next Steps

1. **Set up databases:** Import BIRD schemas for 12 databases
2. **Run baseline evaluation:** Evaluate existing solutions
3. **Integrate with agent:** Use metrics in feedback loop
4. **Optimize performance:** Add connection pooling and parallel execution

## Resources

- **Full Documentation:** See `PHASE_1_2_IMPLEMENTATION_SUMMARY.md`
- **API Reference:** Docstrings in source files
- **Test Examples:** See `tests/` directory
- **BIRD-CRITIC Paper:** https://arxiv.org/abs/2406.11521
