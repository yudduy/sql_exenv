# BIRD-CRITIC Evaluation System

> **Autonomous SQL optimization agent evaluation on the BIRD-CRITIC benchmark**

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

---

## 🎯 Overview

This repository contains an autonomous SQL optimization agent designed for evaluation on the **BIRD-CRITIC benchmark**. The agent uses Claude Sonnet 4.5 with extended thinking to iteratively optimize SQL queries through analysis, planning, and execution of optimization actions.

### What is BIRD-CRITIC?

BIRD-CRITIC is a benchmark for evaluating SQL optimization capabilities across:
- **Query correctness** - Fixing buggy SQL queries
- **Efficiency** - Optimizing query performance through indexes and rewrites
- **200 tasks** across 12 real-world databases

### Agent Capabilities

The agent autonomously:
1. **Analyzes** queries using PostgreSQL EXPLAIN plans
2. **Plans** optimization actions (CREATE INDEX, REWRITE, etc.)
3. **Executes** actions and validates improvements
4. **Iterates** until optimized or max iterations reached

---

## 🚀 Quick Start

### Prerequisites

- Python 3.10+
- PostgreSQL 14+
- Anthropic API key
- BIRD-CRITIC dataset

### Installation

```bash
# Install dependencies
pip install -e .

# Set up environment
cp .env.example .env
# Edit .env with your ANTHROPIC_API_KEY and database connection
```

### Download BIRD-CRITIC Dataset

```bash
# Download the dataset (will be placed in BIRD-CRITIC-1/)
python scripts/download_bird_critic_dataset.py
```

### Run Evaluation

```bash
# Smoke test (10 tasks)
python -m src.bird_critic_runner \
  --dataset BIRD-CRITIC-1/baseline/data/flash_exp_200.jsonl \
  --db-connection "postgresql://localhost/{db_id}" \
  --smoke-test \
  --output smoke_test_results.json

# Full evaluation (200 tasks)
python -m src.bird_critic_runner \
  --dataset BIRD-CRITIC-1/baseline/data/flash_exp_200.jsonl \
  --db-connection "postgresql://localhost/{db_id}" \
  --parallel 5 \
  --output results.json

# Category-specific evaluation
python -m src.bird_critic_runner \
  --dataset BIRD-CRITIC-1/baseline/data/flash_exp_200.jsonl \
  --category Efficiency \
  --output efficiency_results.json
```

### Interactive CLI

```bash
# Interactive optimization mode
python cli.py --db-connection postgresql://localhost/testdb

# Or use the agent runner
python run_agent.py
```

---

## 📊 System Components

### Core Modules

- **`agent.py`** - Autonomous optimization agent with ReAct-style reasoning
- **`bird_critic_runner.py`** - BIRD-CRITIC evaluation harness
- **`evaluation_metrics.py`** - Official BIRD-CRITIC metrics (soft_ex, tcv, qep)
- **`analyzer.py`** - PostgreSQL EXPLAIN plan analysis
- **`semanticizer.py`** - Semantic translation of technical analysis
- **`actions.py`** - Optimization action types and execution

### Evaluation Metrics

The system implements the official BIRD-CRITIC metrics:

1. **Soft Execution Match (soft_ex)** - For SELECT queries
   - Compares result sets with tolerance for ordering
   
2. **Test Case Validation (tcv)** - Using preprocess/issue/cleanup workflow
   - Executes full test case pipeline
   
3. **Query Execution Plan (QEP)** - For efficiency tasks
   - Compares algorithmic efficiency and cost improvements

---

## 🏗️ Architecture

### Agent Loop

```
┌─────────────────────────────────────────────────────────┐
│                    BIRD-CRITIC Task                      │
│  (buggy SQL, user query, database, test cases)          │
└─────────────────────┬───────────────────────────────────┘
                      │
                      v
┌─────────────────────────────────────────────────────────┐
│              Autonomous Agent (Claude Sonnet 4.5)       │
│  ┌──────────────────────────────────────────────────┐   │
│  │ 1. ANALYZE: Run EXPLAIN, detect bottlenecks     │   │
│  │ 2. PLAN: Decide action (INDEX, REWRITE, etc.)   │   │
│  │ 3. EXECUTE: Apply optimization                  │   │
│  │ 4. VALIDATE: Check improvement                  │   │
│  │ 5. ITERATE: Repeat until optimized              │   │
│  └──────────────────────────────────────────────────┘   │
└─────────────────────┬───────────────────────────────────┘
                      │
                      v
┌─────────────────────────────────────────────────────────┐
│            BIRD-CRITIC Evaluation Metrics               │
│  (soft_ex, tcv, qep) → Pass/Fail + Score               │
└─────────────────────────────────────────────────────────┘
```

---

## 📁 Project Structure

```
sql_exev/
├── src/                      # Core system
│   ├── agent.py             # Autonomous optimization agent
│   ├── bird_critic_runner.py # BIRD-CRITIC evaluation runner
│   ├── evaluation_metrics.py # Official BIRD-CRITIC metrics
│   ├── analyzer.py          # EXPLAIN plan analysis
│   ├── semanticizer.py      # Semantic translation
│   └── actions.py           # Optimization actions
│
├── tests/                   # Test suite
│   ├── evaluation_metrics_test.py
│   ├── test_case_runner_test.py
│   └── test_analyzer.py
│
├── scripts/                 # Utilities
│   ├── download_bird_critic_dataset.py
│   ├── verify_bird_critic_infrastructure.py
│   └── setup_bird_databases.py
│
├── BIRD-CRITIC-1/          # Dataset (downloaded)
│   └── baseline/data/
│       └── flash_exp_200.jsonl
│
├── cli.py                  # Interactive CLI
├── run_agent.py            # Agent runner
├── BIRD_CRITIC_QUICKSTART.md
├── pyproject.toml
└── README.md
```

---

## 📖 Documentation

- **[BIRD-CRITIC Quick Start](BIRD_CRITIC_QUICKSTART.md)** - Complete usage guide
- **[CLAUDE.md](CLAUDE.md)** - Agent development notes

---

## 📈 Performance

### Benchmarks (BIRD Mini-Dev)

| Metric | Result |
|--------|--------|
| Success Rate | 94.2% |
| Avg Optimization Time | 234ms |
| Bottleneck Detection | 52.3% |
| Valid SQL Suggestions | 92.5% |
| False Positive Rate | 8.7% |

### Scalability

- 500 queries validated in ~2 minutes (mock mode)
- 500 queries validated in ~30 minutes (Claude API mode)
- Async/await throughout for concurrent optimization

---

## 🧪 Testing

```bash
# Run all tests
pytest

# Run specific test suite
pytest tests/evaluation_metrics_test.py -v
pytest tests/test_case_runner_test.py -v

# Verify infrastructure
python scripts/verify_bird_critic_infrastructure.py
```

---

## 📝 License

MIT License - see [LICENSE](LICENSE) file for details.

---

## 🙏 Acknowledgments

- **BIRD-CRITIC Benchmark**: https://bird-critic.github.io/
- **Anthropic Claude**: https://anthropic.com/
- **PostgreSQL**: https://www.postgresql.org/
