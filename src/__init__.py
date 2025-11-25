"""
sql_exenv: PostgreSQL Query Optimization System

A semantic bridge that translates PostgreSQL's technical EXPLAIN output into
agent-ready feedback, enabling autonomous iterative optimization.

Supports multiple LLM providers: Anthropic (Claude), Groq, OpenRouter.
"""

__version__ = "0.1.0"
__author__ = "sql_exenv Team"

from .analyzer import ExplainAnalyzer, Bottleneck, Severity
from .semanticizer import SemanticTranslator
from .agent import SQLOptimizationAgent
from .actions import Action, ActionType, Solution
from .schema_fetcher import SchemaFetcher
from .llm import (
    create_llm_client,
    LLMProvider,
    LLMConfig,
    LLMResponse,
    BaseLLMClient,
)

__all__ = [
    "ExplainAnalyzer",
    "Bottleneck",
    "Severity",
    "SemanticTranslator",
    "SQLOptimizationAgent",
    "Solution",
    "Action",
    "ActionType",
    "SchemaFetcher",
    "create_llm_client",
    "LLMProvider",
    "LLMConfig",
    "LLMResponse",
    "BaseLLMClient",
    "__version__",
]
