# Quick Start: Running BIRD-CRITIC Evaluations

## Prerequisites

1. **Set PYTHONPATH:**
```bash
export PYTHONPATH=/home/users/duynguy/proj/sql_exev/src
```

2. **Verify setup:**
```bash
python3 test_evaluation_harness.py
# Should output: ✓ All tests passed! Evaluation harness is ready.
```

3. **Ensure databases are running:**
```bash
# Check PostgreSQL
psql -h /tmp -U duynguy -d bird_critic -c "SELECT 1"

# Verify database setup
ls -la /home/users/duynguy/proj/sql_exev/BIRD-CRITIC-1/baseline/data/
```

## Quick Validation (Recommended First Step)

Run a single task to verify everything works:

```bash
python3 -m agentic_dba.bird_critic_runner \
    --dataset /home/users/duynguy/proj/sql_exev/BIRD-CRITIC-1/baseline/data/flash_exp_200.jsonl \
    --db-connection "dbname=bird_critic host=/tmp user=duynguy" \
    --limit 1 \
    --output single_task_test.json
```

**Expected output:**
- Should complete in 1-3 minutes
- Should show iteration progress
- Should save results to `single_task_test.json`

## Smoke Test (10 Tasks)

Test the system with 10 tasks (~10-20 minutes):

```bash
python3 -m agentic_dba.bird_critic_runner \
    --dataset /home/users/duynguy/proj/sql_exev/BIRD-CRITIC-1/baseline/data/flash_exp_200.jsonl \
    --db-connection "dbname=bird_critic host=/tmp user=duynguy" \
    --smoke-test \
    --output smoke_test_results.json
```

**Estimated:**
- Cost: ~$1.00
- Time: 10-20 minutes
- Target success rate: >70%

## Category-Specific Evaluation

### Query Category Only

```bash
python3 -m agentic_dba.bird_critic_runner \
    --dataset /home/users/duynguy/proj/sql_exev/BIRD-CRITIC-1/baseline/data/flash_exp_200.jsonl \
    --db-connection "dbname={db_id} host=/tmp user=duynguy" \
    --category Query \
    --limit 20 \
    --output query_category_results.json
```

### Efficiency Category Only

```bash
python3 -m agentic_dba.bird_critic_runner \
    --dataset /home/users/duynguy/proj/sql_exev/BIRD-CRITIC-1/baseline/data/flash_exp_200.jsonl \
    --db-connection "dbname={db_id} host=/tmp user=duynguy" \
    --category Efficiency \
    --limit 20 \
    --output efficiency_category_results.json
```

## Full Evaluation (200 Tasks)

### Sequential (Safe, Slow)

```bash
python3 -m agentic_dba.bird_critic_runner \
    --dataset /home/users/duynguy/proj/sql_exev/BIRD-CRITIC-1/baseline/data/flash_exp_200.jsonl \
    --db-connection "dbname={db_id} host=/tmp user=duynguy" \
    --output flash_exp_200_sequential.json
```

**Estimated:**
- Cost: ~$20.00
- Time: 6-8 hours
- Recommended: Run overnight

### Parallel (Faster, More Complex)

```bash
python3 -m agentic_dba.bird_critic_runner \
    --dataset /home/users/duynguy/proj/sql_exev/BIRD-CRITIC-1/baseline/data/flash_exp_200.jsonl \
    --db-connection "dbname={db_id} host=/tmp user=duynguy" \
    --parallel 5 \
    --output flash_exp_200_parallel.json
```

**Estimated:**
- Cost: ~$20.00
- Time: 1.5-2 hours
- Requires: 5 concurrent database connections

**Warning:** Parallel mode may cause database contention. Start with `--parallel 2` or `--parallel 3` if issues occur.

## Advanced Configuration

### Custom Agent Parameters

```bash
python3 -m agentic_dba.bird_critic_runner \
    --dataset /home/users/duynguy/proj/sql_exev/BIRD-CRITIC-1/baseline/data/flash_exp_200.jsonl \
    --db-connection "dbname={db_id} host=/tmp user=duynguy" \
    --max-iterations 15 \
    --min-iterations 5 \
    --limit 50 \
    --output custom_config_results.json
```

**Parameters:**
- `--max-iterations`: Maximum optimization attempts (default: 10)
- `--min-iterations`: Minimum before early stopping (default: 3)
- Higher values = more thorough but slower

## Monitoring and Debugging

### Check Progress (Intermediate Results)

During sequential execution, check intermediate results:

```bash
# View intermediate results (created during evaluation)
tail -f <output_file>_intermediate.jsonl | jq '.task_id, .success, .metric_used, .score'
```

### View Results Summary

```bash
# Pretty-print aggregate statistics
jq '.aggregate' flash_exp_200_results.json

# View success rate by category
jq '.aggregate.by_category' flash_exp_200_results.json

# View action distribution
jq '.aggregate.action_distribution' flash_exp_200_results.json
```

### Analyze Failed Tasks

```bash
# Extract failed tasks
jq '.results[] | select(.success == false) | {task_id, reason, error}' flash_exp_200_results.json

# Count failures by category
jq '.results | group_by(.category) | map({category: .[0].category, failed: map(select(.success == false)) | length})' flash_exp_200_results.json
```

## Troubleshooting

### Issue: ModuleNotFoundError

```bash
# Solution: Set PYTHONPATH
export PYTHONPATH=/home/users/duynguy/proj/sql_exev/src
```

### Issue: Database Connection Refused

```bash
# Check PostgreSQL is running
pg_ctl status -D /path/to/data

# Verify database exists
psql -h /tmp -U duynguy -l | grep bird_critic

# Check user permissions
psql -h /tmp -U duynguy -d bird_critic -c "SELECT current_user"
```

### Issue: Timeout Errors

```bash
# Increase timeout
# Edit agent_config in evaluator:
# "timeout_per_task_seconds": 180  # Increase from 120 to 180
```

### Issue: High Memory Usage (Parallel Mode)

```bash
# Reduce concurrent workers
python3 -m agentic_dba.bird_critic_runner \
    --parallel 2 \  # Reduce from 5 to 2
    ...
```

### Issue: Missing tqdm (No Progress Bar)

```bash
# Install tqdm for progress tracking
pip install tqdm
```

## Example Workflow

### Step 1: Validate Installation

```bash
python3 test_evaluation_harness.py
```

### Step 2: Single Task Test

```bash
python3 -m agentic_dba.bird_critic_runner \
    --dataset /home/users/duynguy/proj/sql_exev/BIRD-CRITIC-1/baseline/data/flash_exp_200.jsonl \
    --db-connection "dbname=bird_critic host=/tmp user=duynguy" \
    --limit 1 \
    --output test_1.json
```

### Step 3: Smoke Test (10 Tasks)

```bash
python3 -m agentic_dba.bird_critic_runner \
    --dataset /home/users/duynguy/proj/sql_exev/BIRD-CRITIC-1/baseline/data/flash_exp_200.jsonl \
    --db-connection "dbname=bird_critic host=/tmp user=duynguy" \
    --smoke-test \
    --output smoke_test.json
```

### Step 4: Analyze Smoke Test

```bash
# View summary
jq '.aggregate' smoke_test.json

# Check success rate
jq '.aggregate.success_rate' smoke_test.json

# View failures
jq '.results[] | select(.success == false) | {task_id, reason, error}' smoke_test.json
```

### Step 5: Tune Agent (if needed)

Based on smoke test results:
- If success rate < 50%: Investigate failures, check database setup
- If success rate 50-70%: Consider increasing max_iterations
- If success rate > 70%: Proceed to full evaluation

### Step 6: Full Evaluation

```bash
# Sequential (recommended for first full run)
python3 -m agentic_dba.bird_critic_runner \
    --dataset /home/users/duynguy/proj/sql_exev/BIRD-CRITIC-1/baseline/data/flash_exp_200.jsonl \
    --db-connection "dbname={db_id} host=/tmp user=duynguy" \
    --output flash_exp_200_results.json
```

## Expected Results

### Smoke Test (10 Tasks)

```
======================================================================
EVALUATION SUMMARY
======================================================================
Total Tasks:      10
Successful:       7-9 (70-90%)
Failed:           1-3
Avg Score:        0.75-0.90
Avg Time/Task:    30-60s
Avg Iterations:   3-5
Total Time:       5-10 minutes
======================================================================
```

### Full Evaluation (200 Tasks)

```
======================================================================
EVALUATION SUMMARY
======================================================================
Total Tasks:      200
Successful:       140-180 (70-90%)
Failed:           20-60
Avg Score:        0.70-0.85
Avg Time/Task:    30-60s
Avg Iterations:   3-5
Total Time:       100-200 minutes

By Category:
  Query               : 80-100/120 (67-83%)
  Efficiency          : 30-45/50 (60-90%)
  Management          : 20-25/30 (67-83%)

By Metric:
  soft_ex             : 80-100/120
  tcv                 : 20-25/30
  qep                 : 30-45/50
======================================================================
```

## Getting Help

1. **Check validation test:**
   ```bash
   python3 test_evaluation_harness.py
   ```

2. **Review Phase 5 documentation:**
   ```bash
   cat PHASE_5_EVALUATION_HARNESS.md
   ```

3. **Check CLI help:**
   ```bash
   python3 -m agentic_dba.bird_critic_runner --help
   ```

4. **View debug logs:**
   Enable debug logging by setting environment variable:
   ```bash
   export LOG_LEVEL=DEBUG
   python3 -m agentic_dba.bird_critic_runner ...
   ```

## File Locations

- **Main runner:** `src/agentic_dba/bird_critic_runner.py`
- **Evaluation metrics:** `src/agentic_dba/evaluation_metrics.py`
- **Test case runner:** `src/agentic_dba/test_case_runner.py`
- **Agent:** `src/agentic_dba/agent.py`
- **Dataset:** `BIRD-CRITIC-1/baseline/data/flash_exp_200.jsonl`
- **Results:** `*.json` (output files)
- **Validation test:** `test_evaluation_harness.py`

## Next Steps After Evaluation

1. **Analyze results:**
   - Review success rates by category
   - Identify common failure patterns
   - Compare with baseline results

2. **Generate report:**
   - Visualize results (plots, charts)
   - Document improvements
   - Identify optimization opportunities

3. **Iterate on agent:**
   - Tune parameters based on results
   - Add new optimization strategies
   - Improve failure handling

4. **Submit results:**
   - Compare with official baseline
   - Document methodology
   - Share findings with community
