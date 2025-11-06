# Architecture Diagrams

## System Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        CLAUDE AGENT                              │
│  "Optimize: SELECT * FROM users WHERE email = 'test@example.com'"│
└────────────────────────────┬────────────────────────────────────┘
                             │ MCP Protocol
                             │ (standardized tool calls)
                             ↓
┌─────────────────────────────────────────────────────────────────┐
│              SEMANTIC BRIDGE MCP SERVER (This Tool)             │
│ ┌─────────────────────────────────────────────────────────────┐ │
│ │         optimize_postgres_query(sql, db, constraints)       │ │
│ └─────────────────────────────────────────────────────────────┘ │
│                                                                   │
│   ┌──────────────┐      ┌──────────────┐      ┌──────────────┐ │
│   │   Solver     │  →   │   Model 1    │  →   │   Model 2    │ │
│   │  (EXPLAIN)   │      │  (Analyzer)  │      │(Semanticizer)│ │
│   └──────────────┘      └──────────────┘      └──────────────┘ │
│         │                      │                      │          │
│    Raw Plan              Technical              Natural          │
│    (JSON)                Analysis              Language          │
│  {cost: 55K...}         {bottleneck...}      {status: fail...}  │
└──────────┬──────────────────────────────────────────────────────┘
           │
           ↓
┌─────────────────────────────┐
│   PostgreSQL Database        │
│   (Your production/dev DB)   │
└─────────────────────────────┘
```

## Data Flow - Detailed

```
ITERATION 1: Initial Query Analysis
═══════════════════════════════════

1. Agent Input:
   ┌────────────────────────────────────────┐
   │ sql_query:                             │
   │   "SELECT * FROM users                 │
   │    WHERE email = 'test@example.com'"   │
   │                                        │
   │ constraints:                           │
   │   {"max_cost": 1000.0}                 │
   └────────────────────────────────────────┘
                    ↓
                    
2. Solver (EXPLAIN):
   ┌────────────────────────────────────────┐
   │ EXPLAIN (ANALYZE, COSTS, VERBOSE,      │
   │          BUFFERS, FORMAT JSON)         │
   │ SELECT * FROM users ...                │
   └────────────────────────────────────────┘
                    ↓
   ┌────────────────────────────────────────┐
   │ Raw EXPLAIN JSON:                      │
   │ {                                      │
   │   "Plan": {                            │
   │     "Node Type": "Seq Scan",           │
   │     "Relation Name": "users",          │
   │     "Total Cost": 55072.45,            │
   │     "Actual Rows": 100000,             │
   │     "Filter": "(email = '...')"        │
   │   }                                    │
   │ }                                      │
   └────────────────────────────────────────┘
                    ↓

3. Model 1 (Analyzer):
   ┌────────────────────────────────────────┐
   │ Parsing & Analysis:                    │
   │ • Traverse plan tree                   │
   │ • Check: Seq Scan? ✓                   │
   │ • Check: rows > 10K? ✓ (100K)          │
   │ • Severity: HIGH                       │
   │ • Extract column: "email"              │
   └────────────────────────────────────────┘
                    ↓
   ┌────────────────────────────────────────┐
   │ Technical Analysis:                    │
   │ {                                      │
   │   "total_cost": 55072.45,              │
   │   "bottlenecks": [                     │
   │     {                                  │
   │       "node_type": "Seq Scan",         │
   │       "table": "users",                │
   │       "rows": 100000,                  │
   │       "severity": "HIGH",              │
   │       "suggestion": "CREATE INDEX..."  │
   │     }                                  │
   │   ]                                    │
   │ }                                      │
   └────────────────────────────────────────┘
                    ↓

4. Model 2 (Semanticizer):
   ┌────────────────────────────────────────┐
   │ LLM Prompt:                            │
   │ "You are a PostgreSQL DBA. Given      │
   │  this technical analysis and these    │
   │  constraints, provide feedback..."    │
   │                                        │
   │ Technical: {cost: 55K, Seq Scan...}   │
   │ Constraints: {max_cost: 1K}           │
   └────────────────────────────────────────┘
                    ↓
   ┌────────────────────────────────────────┐
   │ Semantic Feedback (Agent-Ready):       │
   │ {                                      │
   │   "status": "fail",                    │
   │   "reason": "Cost (55,072) exceeds     │
   │             limit (1,000). Seq Scan    │
   │             on users is bottleneck.",  │
   │   "suggestion": "CREATE INDEX          │
   │                  idx_users_email       │
   │                  ON users(email);",    │
   │   "priority": "HIGH"                   │
   │ }                                      │
   └────────────────────────────────────────┘
                    ↓

5. Agent Receives & Acts:
   ┌────────────────────────────────────────┐
   │ Agent: "I see the problem! I'll fix it"│
   │                                        │
   │ [Executes]:                            │
   │ CREATE INDEX idx_users_email           │
   │   ON users(email);                     │
   └────────────────────────────────────────┘


ITERATION 2: Validation
═══════════════════════

1. Agent re-submits same query
                    ↓
2. EXPLAIN runs again → Cost: 14.2 (Index Scan)
                    ↓
3. Model 1: No bottlenecks (cost within threshold)
                    ↓
4. Model 2: "status: pass, No optimization needed"
                    ↓
5. Agent: "✅ Optimization successful! 99.97% improvement"
```

## Component Interaction Matrix

```
┌──────────────┬────────────┬────────────┬────────────┐
│              │  Solver    │  Model 1   │  Model 2   │
├──────────────┼────────────┼────────────┼────────────┤
│ Input        │ SQL query  │ EXPLAIN    │ Technical  │
│              │            │ JSON       │ analysis   │
├──────────────┼────────────┼────────────┼────────────┤
│ Processing   │ PostgreSQL │ Python     │ LLM        │
│              │ planner    │ parsing    │ prompt     │
├──────────────┼────────────┼────────────┼────────────┤
│ Output       │ Execution  │ Bottleneck │ Natural    │
│              │ plan JSON  │ list       │ language   │
├──────────────┼────────────┼────────────┼────────────┤
│ Latency      │ ~100ms     │ ~400ms     │ ~1.5s      │
├──────────────┼────────────┼────────────┼────────────┤
│ Dependencies │ psycopg2   │ stdlib     │ anthropic  │
└──────────────┴────────────┴────────────┴────────────┘
```

## File Dependency Graph

```
mcp_server.py (Main Entry Point)
    │
    ├── imports model_1_analyzer.py
    │       │
    │       └── uses: ExplainAnalyzer class
    │           └── methods: analyze(), _traverse_plan()
    │
    ├── imports model_2_semanticizer.py
    │       │
    │       └── uses: SemanticTranslator / MockTranslator
    │           └── methods: translate(), _build_prompt()
    │
    ├── imports psycopg2 (external)
    │       └── for: Database connections
    │
    ├── imports anthropic (external, optional)
    │       └── for: LLM API calls (Model 2)
    │
    └── imports mcp (external)
            └── for: Tool registration with Claude

test_demo.py (Standalone Testing)
    │
    ├── imports model_1_analyzer
    └── imports model_2_semanticizer
        └── provides: Sample EXPLAIN plans for validation
```

## Execution Flow - Timing Breakdown

```
Total Optimization Cycle: ~5 seconds
═══════════════════════════════════

┌─────────────────────────────────────────┐ 0ms
│ Agent calls optimize_postgres_query()   │
└─────────────────┬───────────────────────┘
                  ↓
┌─────────────────────────────────────────┐ 0-500ms
│ Database Connection                     │ (depends on network)
│ • psycopg2.connect()                    │
└─────────────────┬───────────────────────┘
                  ↓
┌─────────────────────────────────────────┐ 500-1000ms
│ EXPLAIN ANALYZE Execution               │ (depends on query)
│ • PostgreSQL runs query                 │
│ • Collects timing data                  │
│ • Returns JSON plan                     │
└─────────────────┬───────────────────────┘
                  ↓
┌─────────────────────────────────────────┐ 1000-1500ms
│ Model 1: Parse & Analyze                │ (pure Python, fast)
│ • json.loads()                          │
│ • _traverse_plan()                      │
│ • Detect bottlenecks                    │
└─────────────────┬───────────────────────┘
                  ↓
┌─────────────────────────────────────────┐ 1500-3500ms
│ Model 2: Semantic Translation           │ (LLM API call)
│ • Build prompt                          │
│ • anthropic.messages.create()           │
│ • Parse response                        │
└─────────────────┬───────────────────────┘
                  ↓
┌─────────────────────────────────────────┐ 3500ms
│ Return Feedback to Agent                │
│ {status, reason, suggestion, priority}  │
└─────────────────────────────────────────┘

Optimization: Use MockTranslator to skip LLM call
→ Reduces total time to ~2 seconds
```

## Comparison: Traditional vs. Agentic Workflow

```
TRADITIONAL HUMAN WORKFLOW
══════════════════════════

Developer                     DBA
   │                           │
   ├─ "Query is slow" ────────→│
   │                           │
   │                      [Manually runs EXPLAIN]
   │                      [Analyzes plan for 15 min]
   │                      [Identifies Seq Scan]
   │                      [Researches best index]
   │                           │
   │←──── "Add this index" ────┤
   │                           │
   ├─ Creates index            │
   │                           │
   ├─ Tests query              │
   │                           │
   ├─ "Still slow?" ──────────→│
   │                           │
   │                      [Repeat cycle]
   │                           │

Time: 30-60 minutes per query
Human effort: High
Scalability: Poor


AGENTIC WORKFLOW (This Tool)
═════════════════════════════

Agent
  │
  ├─ Writes query
  │      ↓
  ├─ Calls optimize_postgres_query()
  │      ↓
  │  [Tool analyzes in 5 seconds]
  │      ↓
  ├─ Receives: "Add index on email"
  │      ↓
  ├─ Executes: CREATE INDEX...
  │      ↓
  ├─ Validates with tool
  │      ↓
  └─ ✅ Done!

Time: <30 seconds per query
Human effort: Zero
Scalability: Excellent
```

## Error Handling Pathways

```
Query Submission
       │
       ↓
  ┌──────────┐
  │ Validate │
  │  Input   │
  └────┬─────┘
       │
       ├─ SQL Syntax Error? ──→ Return {status: "error", suggestion: "Fix syntax"}
       │
       ├─ Connection Failed? ──→ Return {status: "error", suggestion: "Check DB connection"}
       │
       ↓
  ┌──────────┐
  │  EXPLAIN │
  │  Execute │
  └────┬─────┘
       │
       ├─ Timeout? ───────────→ Return {status: "error", suggestion: "Query too slow to analyze"}
       │
       ├─ Permission Denied? ──→ Return {status: "error", suggestion: "Check user permissions"}
       │
       ↓
  ┌──────────┐
  │ Model 1  │
  │ Analysis │
  └────┬─────┘
       │
       ├─ Invalid JSON? ───────→ Retry once, then error
       │
       ↓
  ┌──────────┐
  │ Model 2  │
  │Translate │
  └────┬─────┘
       │
       ├─ LLM Timeout? ────────→ Use MockTranslator fallback
       │
       ├─ Invalid Response? ───→ Parse error, return technical analysis
       │
       ↓
  ┌──────────┐
  │  Return  │
  │ Feedback │
  └──────────┘

Note: Every error path returns a valid {status, reason, suggestion}
      so the agent always gets actionable feedback.
```
