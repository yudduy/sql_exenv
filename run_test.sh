#!/bin/bash
export ANTHROPIC_API_KEY='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'
export DB_CONNECTION='dbname=bird_critic host=/tmp user=duynguy'
export PYTHONPATH="${PYTHONPATH}:/home/users/duynguy/proj/sql_exev/src"

echo "Running BIRD-CRITIC evaluation with schema fixes..."
python3 -m agentic_dba.bird_critic_runner \
  --dataset bird_critic_test.json \
  --db-connection "$DB_CONNECTION" \
  --limit 5 \
  --output test_results.json
