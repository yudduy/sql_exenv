# Quick Start Guide

## Interactive SQL Optimization CLI

### 30-Second Setup

```bash
# 1. Install dependencies
pip install -e .

# 2. Set API key
export ANTHROPIC_API_KEY='sk-ant-...'

# 3. Set database connection
export DB_CONNECTION='postgresql://localhost/yourdb'

# 4. Run CLI
python optimize_cli.py
```

### Example Session

```
Enter SQL query (type 'GO' to execute, 'EXIT' to quit):
SELECT * FROM users WHERE email = 'alice@example.com'
GO
```

The agent will:
1. ✓ Analyze query performance
2. ✓ Detect bottlenecks (e.g., sequential scans)
3. ✓ Plan optimization action
4. ✓ Execute improvements (e.g., create index)
5. ✓ Validate results
6. ✓ Show complete trace

### What You'll See

**Iteration 1:**
- Status: FAIL
- Cost: 55,072.50
- Bottleneck: Sequential scan on 100,000 rows
- Action: CREATE INDEX idx_users_email ON users(email)

**Iteration 2:**
- Status: PASS
- Cost: 142.50 (99.7% improvement!)
- Action: DONE

### Files You Need

| File | Purpose |
|------|---------|
| `optimize_cli.py` | Main interactive CLI |
| `OPTIMIZE_CLI_USAGE.txt` | Full documentation |
| `demo_cli_example.py` | Demo walkthrough |
| `test_cli.py` | Validation tests |

### Command Options

```bash
# Basic
python optimize_cli.py

# With constraints
python optimize_cli.py --max-cost 1000 --max-time-ms 5000

# Different database
python optimize_cli.py --db-connection postgresql://prod-db/analytics

# More iterations
python optimize_cli.py --max-iterations 10
```

### Demo Without Database

```bash
python demo_cli_example.py --mock
```

### Testing

```bash
python test_cli.py
```

Expected: `Tests passed: 2/2` ✅

### Features

- ✓ Multi-line query input
- ✓ Real-time optimization traces
- ✓ Agent reasoning display
- ✓ Color-coded output
- ✓ Performance metrics
- ✓ Action history
- ✓ Iterative improvement

### Architecture

```
Phase 1: QueryOptimizationTool
  ↓ EXPLAIN analysis
  ↓ Bottleneck detection
  ↓ Technical feedback

Phase 2: SQLOptimizationAgent
  ↓ ReAct loop (Analyze → Plan → Act)
  ↓ Extended thinking (8000 tokens)
  ↓ Action execution
  ↓ Validation
```

### Troubleshooting

| Issue | Solution |
|-------|----------|
| No API key | `export ANTHROPIC_API_KEY='your-key'` |
| No DB connection | `export DB_CONNECTION='postgresql://...'` |
| Import error | `pip install -e .` |
| Test failures | Check ANTHROPIC_API_KEY is set |

### Next Steps

1. **Quick Demo**: `python demo_cli_example.py --mock`
2. **Full Usage Guide**: Read `OPTIMIZE_CLI_USAGE.txt`
3. **Architecture**: See `CLAUDE.md`
4. **Programmatic Use**: See `run_agent.py`

### Support

- Issues: Check `OPTIMIZE_CLI_USAGE.txt` troubleshooting section
- Examples: See `demo_cli_example.py`
- Tests: Run `test_cli.py`

---

**Ready to optimize!** 🚀
