"""
Action Types for Autonomous SQL Optimization Agent

Defines the action space for the agent's decision-making loop.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Any


class ActionType(Enum):
    """Types of actions the agent can take."""

    CREATE_INDEX = "CREATE_INDEX"      # Execute index creation DDL
    TEST_INDEX = "TEST_INDEX"          # Test index virtually via hypopg (auto-creates if beneficial)
    REWRITE_QUERY = "REWRITE_QUERY"    # Modify query structure
    RUN_ANALYZE = "RUN_ANALYZE"        # Update table statistics
    DONE = "DONE"                       # Optimization complete
    FAILED = "FAILED"                   # Cannot optimize further


@dataclass
class Action:
    """
    Represents a single action in the optimization loop.

    Attributes:
        type: Type of action to take
        ddl: SQL DDL statement (for CREATE_INDEX, TEST_INDEX, RUN_ANALYZE)
        new_query: Modified query (for REWRITE_QUERY)
        reasoning: Agent's reasoning for this action
        confidence: Confidence score 0.0-1.0
    """

    type: ActionType
    reasoning: str
    ddl: str | None = None
    new_query: str | None = None
    confidence: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "type": self.type.value,
            "reasoning": self.reasoning,
            "ddl": self.ddl,
            "new_query": self.new_query,
            "confidence": self.confidence,
        }

    def is_terminal(self) -> bool:
        """Check if this action ends the optimization loop."""
        return self.type in (ActionType.DONE, ActionType.FAILED)

    def requires_db_mutation(self) -> bool:
        """Check if this action modifies the database."""
        # TEST_INDEX may create real index if beneficial, so it's potentially mutating
        return self.type in (ActionType.CREATE_INDEX, ActionType.TEST_INDEX, ActionType.RUN_ANALYZE)


@dataclass
class Solution:
    """
    Final solution from the autonomous optimization process.

    Attributes:
        final_query: The optimized query
        actions: List of actions taken during optimization
        success: Whether optimization succeeded
        reason: Explanation of outcome
        metrics: Performance metrics (cost improvement, time, etc.)
    """

    final_query: str
    actions: list[Action]
    success: bool
    reason: str
    metrics: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "final_query": self.final_query,
            "actions": [a.to_dict() for a in self.actions],
            "success": self.success,
            "reason": self.reason,
            "metrics": self.metrics or {},
        }

    def total_iterations(self) -> int:
        """Count non-terminal actions taken."""
        return len([a for a in self.actions if not a.is_terminal()])


def parse_action_from_llm_response(response: str) -> Action:
    """
    Parse LLM response into an Action object.

    Expected JSON format:
    {
        "action": "CREATE_INDEX" | "TEST_INDEX" | "REWRITE_QUERY" | "RUN_ANALYZE" | "DONE" | "FAILED",
        "reasoning": "Why this action is needed",
        "ddl": "CREATE INDEX ...",  // if CREATE_INDEX, TEST_INDEX, or RUN_ANALYZE
        "new_query": "SELECT ...",  // if REWRITE_QUERY
        "confidence": 0.95
    }

    Args:
        response: JSON string from LLM

    Returns:
        Parsed Action object

    Raises:
        ValueError: If response format is invalid
    """
    import json

    # Strip markdown code blocks if present
    response = response.strip()
    if response.startswith("```json"):
        response = response[7:]
    if response.startswith("```"):
        response = response[3:]
    if response.endswith("```"):
        response = response[:-3]
    response = response.strip()

    # Handle empty response - default to DONE action
    if not response:
        raise ValueError(
            "Empty response from LLM - no JSON content found. "
            "This may indicate the LLM response was truncated or malformed."
        )

    try:
        data = json.loads(response)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON response: {e}") from e

    # Parse action type (try both "type" and "action" for compatibility)
    action_str = data.get("type", data.get("action", "")).upper()
    try:
        action_type = ActionType[action_str]
    except KeyError as e:
        raise ValueError(f"Unknown action type: {action_str}") from e

    # Extract fields
    reasoning = data.get("reasoning", "No reasoning provided")
    ddl = data.get("ddl")
    new_query = data.get("new_query")
    confidence = float(data.get("confidence", 1.0))

    # Validate required fields
    if action_type == ActionType.CREATE_INDEX and not ddl:
        raise ValueError("CREATE_INDEX action requires 'ddl' field")
    if action_type == ActionType.TEST_INDEX and not ddl:
        raise ValueError("TEST_INDEX action requires 'ddl' field")
    if action_type == ActionType.REWRITE_QUERY and not new_query:
        raise ValueError("REWRITE_QUERY action requires 'new_query' field")
    if action_type == ActionType.RUN_ANALYZE and not ddl:
        raise ValueError("RUN_ANALYZE action requires 'ddl' field")

    return Action(
        type=action_type,
        reasoning=reasoning,
        ddl=ddl,
        new_query=new_query,
        confidence=confidence,
    )
