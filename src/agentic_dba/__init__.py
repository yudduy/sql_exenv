"""
Agentic DBA: AI-Powered PostgreSQL Query Optimization System

A semantic bridge that translates PostgreSQL's technical EXPLAIN output into
agent-ready feedback, enabling autonomous iterative optimization.
"""

__version__ = "0.1.0"
__author__ = "Agentic DBA Team"

from .analyzer import ExplainAnalyzer, Bottleneck, Severity
from .semanticizer import SemanticTranslator, MockTranslator
from .mcp_server import QueryOptimizationTool
from .agent import SQLOptimizationAgent, BIRDCriticTask, Solution
from .actions import Action, ActionType

__all__ = [
    "ExplainAnalyzer",
    "Bottleneck",
    "Severity",
    "SemanticTranslator",
    "MockTranslator",
    "QueryOptimizationTool",
    "SQLOptimizationAgent",
    "BIRDCriticTask",
    "Solution",
    "Action",
    "ActionType",
    "__version__",
]
