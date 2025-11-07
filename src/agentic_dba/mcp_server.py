"""
MCP Server: PostgreSQL Query Optimization Bridge

This is the main MCP server that exposes the query optimization tool
to AI agents (Claude, etc.). It coordinates Model 1 (analyzer) and
Model 2 (semanticizer) to provide iterative optimization feedback.
"""

import asyncio
import json
import os
from typing import Any, Dict, Optional
import psycopg2
from psycopg2.extras import RealDictCursor

# Import our models
from .analyzer import ExplainAnalyzer
from .semanticizer import SemanticTranslator, MockTranslator


class QueryOptimizationTool:
    """
    Core optimization tool that orchestrates the full pipeline.
    
    Pipeline:
    1. Execute EXPLAIN ANALYZE on PostgreSQL
    2. Parse with Model 1 (technical analysis)
    3. Translate with Model 2 (semantic feedback)
    4. Return agent-ready feedback
    """
    
    def __init__(
        self,
        use_mock_translator: bool = False,
        analyzer_thresholds: Optional[Dict] = None,
        translator_model: Optional[str] = None,
    ):
        """
        Initialize the optimization tool.
        
        Args:
            use_mock_translator: If True, use rule-based mock instead of LLM
            analyzer_thresholds: Custom thresholds for Model 1
        """
        self.analyzer = ExplainAnalyzer(custom_thresholds=analyzer_thresholds)
        
        if use_mock_translator:
            self.translator = MockTranslator()
        else:
            self.translator = SemanticTranslator(model=translator_model or "claude-3-haiku-20240307")
    
    async def optimize_query(
        self,
        sql_query: str,
        db_connection_string: str,
        constraints: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Optimize a PostgreSQL query and return actionable feedback.
        
        Args:
            sql_query: The SELECT query to optimize
            db_connection_string: PostgreSQL connection string
            constraints: Performance constraints (max_cost, max_time_ms)
        
        Returns:
            {
                "success": bool,
                "feedback": {
                    "status": "pass|fail|warning",
                    "reason": str,
                    "suggestion": str,
                    "priority": "HIGH|MEDIUM|LOW"
                },
                "technical_analysis": dict,  # For debugging
                "error": str  # If success=False
            }
        """
        # Default constraints
        if constraints is None:
            constraints = {"max_cost": 10000.0}
        
        try:
            # Phase 1: Dry-run EXPLAIN (no ANALYZE) to get estimated cost quickly
            explain_json_dry = await self._run_explain(
                sql_query, db_connection_string, analyze=False, statement_timeout_ms=None
            )

            # Analyze dry plan first
            technical_analysis = self.analyzer.analyze(explain_json_dry)

            # Optionally run ANALYZE with timeout if estimated cost is reasonable
            analyze_plan: Optional[dict] = None
            estimated_total_cost = 0.0
            try:
                root = explain_json_dry[0] if isinstance(explain_json_dry, list) else explain_json_dry
                estimated_total_cost = float(root.get("Plan", {}).get("Total Cost", 0) or 0)
            except Exception:
                estimated_total_cost = 0.0

            analyze_cost_threshold = constraints.get("analyze_cost_threshold", 1_000_000_000.0)
            statement_timeout_ms = None
            if constraints.get("max_time_ms") is not None:
                try:
                    statement_timeout_ms = int(constraints["max_time_ms"])
                except Exception:
                    statement_timeout_ms = None

            if estimated_total_cost <= analyze_cost_threshold:
                try:
                    analyze_plan = await self._run_explain(
                        sql_query,
                        db_connection_string,
                        analyze=True,
                        statement_timeout_ms=statement_timeout_ms,
                    )
                    # Prefer ANALYZE-backed technical analysis when available
                    technical_analysis = self.analyzer.analyze(analyze_plan)
                except psycopg2.Error:
                    # Timeouts or cancellations will be reported via error handler below
                    pass

            # Optional: HypoPG proof for CREATE INDEX suggestions
            hypopg_proof: Optional[Dict[str, Any]] = None
            use_hypopg = bool(constraints.get("use_hypopg", False))
            if use_hypopg:
                # Find first CREATE INDEX suggestion from technical analysis
                idx_stmt: Optional[str] = None
                for b in technical_analysis.get("bottlenecks", []):
                    s = (b or {}).get("suggestion", "")
                    if isinstance(s, str) and s.strip().upper().startswith("CREATE INDEX"):
                        idx_stmt = s.strip().rstrip(";") + ";"
                        break
                if idx_stmt:
                    try:
                        proof = await self._run_hypopg_proof(
                            sql_query, db_connection_string, idx_stmt, explain_json_dry
                        )
                        hypopg_proof = proof
                    except psycopg2.Error:
                        hypopg_proof = None

            # Translate with Model 2 using the best available analysis
            semantic_feedback = self.translator.translate(technical_analysis, constraints)

            # Return structured result with both plans where available
            result: Dict[str, Any] = {
                "success": True,
                "feedback": semantic_feedback,
                "technical_analysis": technical_analysis,
                "explain_plan_dry": explain_json_dry,
            }
            if analyze_plan is not None:
                result["explain_plan_analyze"] = analyze_plan
            if hypopg_proof is not None:
                result["hypopg_proof"] = hypopg_proof

            # Backward compatibility: single explain_plan preferring ANALYZE if available
            result["explain_plan"] = analyze_plan if analyze_plan is not None else explain_json_dry

            return result
            
        except psycopg2.Error as e:
            return self._handle_db_error(e, sql_query)
        except Exception as e:
            return self._handle_general_error(e)
    
    async def _run_explain(self, sql_query: str, connection_string: str, analyze: bool = True, statement_timeout_ms: Optional[int] = None) -> dict:
        """
        Execute EXPLAIN ANALYZE on PostgreSQL.
        
        Returns parsed JSON of execution plan.
        """
        # Run in thread pool since psycopg2 is blocking
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            self._execute_explain_sync,
            sql_query,
            connection_string,
            analyze,
            statement_timeout_ms,
        )
    
    def _execute_explain_sync(self, sql_query: str, connection_string: str, analyze: bool, statement_timeout_ms: Optional[int]) -> dict:
        """Synchronous EXPLAIN execution (called from thread pool)."""
        conn = None
        try:
            conn = psycopg2.connect(connection_string)
            cursor = conn.cursor()
            
            # Construct EXPLAIN query with options
            analyze_flag = "true" if analyze else "false"
            explain_query = f"""
            EXPLAIN (
                ANALYZE {analyze_flag},
                COSTS true,
                VERBOSE true,
                BUFFERS true,
                FORMAT JSON
            )
            {sql_query}
            """

            # Apply a local statement_timeout if requested
            if statement_timeout_ms is not None and analyze:
                cursor.execute(f"SET LOCAL statement_timeout = '{int(statement_timeout_ms)}ms'")

            cursor.execute(explain_query)
            result = cursor.fetchone()[0]

            # End transaction to clear SET LOCAL
            try:
                conn.rollback()
            except Exception:
                pass

            return result
            
        finally:
            if conn:
                conn.close()

    async def _run_hypopg_proof(self, sql_query: str, connection_string: str, index_ddl: str, before_explain_json: dict) -> Dict[str, Any]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            self._hypopg_proof_sync,
            sql_query,
            connection_string,
            index_ddl,
            before_explain_json,
        )

    def _hypopg_proof_sync(self, sql_query: str, connection_string: str, index_ddl: str, before_explain_json: dict) -> Dict[str, Any]:
        conn = None
        try:
            conn = psycopg2.connect(connection_string)
            cursor = conn.cursor()

            # Compute before cost
            try:
                before_root = before_explain_json[0] if isinstance(before_explain_json, list) else before_explain_json
                before_cost = float(before_root.get("Plan", {}).get("Total Cost", 0) or 0)
            except Exception:
                before_cost = 0.0

            # Ensure HypoPG is available
            cursor.execute("CREATE EXTENSION IF NOT EXISTS hypopg")
            # Create hypothetical index
            cursor.execute("SELECT hypopg_create_index(%s)", (index_ddl,))

            # Re-run dry EXPLAIN under same session to see planner effect
            explain_query = f"""
            EXPLAIN (
                ANALYZE false,
                COSTS true,
                VERBOSE true,
                BUFFERS true,
                FORMAT JSON
            )
            {sql_query}
            """
            cursor.execute(explain_query)
            after_plan = cursor.fetchone()[0]

            # Get after cost
            try:
                after_root = after_plan[0] if isinstance(after_plan, list) else after_plan
                after_cost = float(after_root.get("Plan", {}).get("Total Cost", 0) or 0)
            except Exception:
                after_cost = 0.0

            # Reset hypopg hypothetical indexes for cleanliness
            try:
                cursor.execute("SELECT hypopg_reset()")
            except Exception:
                pass

            # Build proof object (improvement as percentage delta; negative is better)
            improvement_pct = 0.0
            try:
                if before_cost:
                    improvement_pct = ((after_cost - before_cost) / before_cost) * 100.0
            except Exception:
                improvement_pct = 0.0

            return {
                "suggested_index": index_ddl,
                "before_cost": before_cost,
                "after_cost": after_cost,
                "improvement": improvement_pct,
                "explain_plan_after": after_plan,
            }
        finally:
            if conn:
                conn.close()
    
    def _handle_db_error(self, error: psycopg2.Error, sql_query: str) -> Dict:
        """Handle PostgreSQL errors gracefully."""
        error_msg = str(error)
        
        # Parse common error types
        if "syntax error" in error_msg.lower():
            suggestion = "Fix SQL syntax error"
        elif "does not exist" in error_msg.lower():
            suggestion = "Verify table/column names exist"
        elif "permission denied" in error_msg.lower():
            suggestion = "Check database user permissions"
        else:
            suggestion = "Review PostgreSQL error message"
        
        return {
            "success": False,
            "error": error_msg,
            "feedback": {
                "status": "error",
                "reason": f"Query execution failed: {error_msg[:100]}...",
                "suggestion": suggestion,
                "priority": "HIGH"
            }
        }
    
    def _handle_general_error(self, error: Exception) -> Dict:
        """Handle unexpected errors."""
        return {
            "success": False,
            "error": str(error),
            "feedback": {
                "status": "error",
                "reason": f"Analysis failed: {str(error)}",
                "suggestion": "Retry or report issue",
                "priority": "HIGH"
            }
        }


# ============================================================================
# MCP Server Implementation
# ============================================================================

try:
    from mcp.server import Server
    from mcp.types import Tool, TextContent
    import mcp.server.stdio
    MCP_AVAILABLE = True
except ImportError:
    MCP_AVAILABLE = False
    print("WARNING: mcp package not installed. Install with: pip install mcp")


if MCP_AVAILABLE:
    # Initialize optimization tool
    # Use mock translator by default for testing without API key
    USE_MOCK = os.getenv('USE_MOCK_TRANSLATOR', 'true').lower() == 'true'
    optimization_tool = QueryOptimizationTool(use_mock_translator=USE_MOCK)
    
    # Define MCP tool schema
    OPTIMIZE_TOOL_SCHEMA = Tool(
        name="optimize_postgres_query",
        description="""
        Analyzes a PostgreSQL query and provides actionable optimization feedback.
        
        This tool executes EXPLAIN ANALYZE, identifies bottlenecks, and returns
        natural language suggestions for improvement. Use iteratively:
        
        1. Submit query → 2. Get feedback → 3. Apply suggestion → 4. Validate
        
        Example constraints:
        {
            "max_cost": 1000.0,      # Maximum acceptable query cost
            "max_time_ms": 100.0     # Maximum execution time in milliseconds
        }
        """,
        inputSchema={
            "type": "object",
            "properties": {
                "sql_query": {
                    "type": "string",
                    "description": "The PostgreSQL SELECT query to optimize"
                },
                "db_connection_string": {
                    "type": "string",
                    "description": "PostgreSQL connection string (postgresql://user:pass@host:port/db)"
                },
                "constraints": {
                    "type": "object",
                    "description": "Performance constraints",
                    "properties": {
                        "max_cost": {
                            "type": "number",
                            "description": "Maximum acceptable query cost"
                        },
                        "max_time_ms": {
                            "type": "number",
                            "description": "Maximum execution time in milliseconds"
                        }
                    }
                }
            },
            "required": ["sql_query", "db_connection_string"]
        }
    )
    
    # Create MCP server
    app = Server("postgres-optimization-bridge")
    
    @app.list_tools()
    async def list_tools() -> list[Tool]:
        """Return available tools."""
        return [OPTIMIZE_TOOL_SCHEMA]
    
    @app.call_tool()
    async def call_tool(name: str, arguments: Any) -> list[TextContent]:
        """Handle tool invocations."""
        if name != "optimize_postgres_query":
            raise ValueError(f"Unknown tool: {name}")
        
        # Call optimization tool
        result = await optimization_tool.optimize_query(**arguments)
        
        # Format response for agent
        return [TextContent(
            type="text",
            text=json.dumps(result, indent=2)
        )]


# ============================================================================
# Standalone Testing Interface (without MCP)
# ============================================================================

async def test_optimization(
    sql_query: str,
    db_connection_string: str,
    constraints: Optional[Dict] = None
):
    """
    Test the optimization tool without MCP.
    Useful for development and debugging.
    """
    tool = QueryOptimizationTool(use_mock_translator=True)
    result = await tool.optimize_query(sql_query, db_connection_string, constraints)
    
    print("=" * 60)
    print("OPTIMIZATION RESULT")
    print("=" * 60)
    print(json.dumps(result, indent=2))
    print("=" * 60)
    
    return result


# ============================================================================
# Entry Points
# ============================================================================

def run_mcp_server():
    """Run as MCP server (for Claude Desktop integration)."""
    if not MCP_AVAILABLE:
        print("ERROR: mcp package required. Install with: pip install mcp")
        return
    
    print("Starting PostgreSQL Optimization MCP Server...")
    print(f"Using {'MOCK' if USE_MOCK else 'REAL'} translator")
    mcp.server.stdio.run(app)


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        # Test mode - run sample optimization
        print("Running in TEST mode...")
        
        # Sample test query (replace with your own)
        test_query = "SELECT * FROM users WHERE email = 'test@example.com'"
        test_db = os.getenv('TEST_DB_URL', 'postgresql://localhost/testdb')
        test_constraints = {"max_cost": 1000.0}
        
        asyncio.run(test_optimization(test_query, test_db, test_constraints))
    else:
        # MCP server mode
        run_mcp_server()
