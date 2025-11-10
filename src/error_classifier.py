"""
Error Classification System for PostgreSQL Errors

Categorizes PostgreSQL errors into taxonomy and provides error-specific guidance
for alternative optimization strategies.

Inspired by SQL-of-Thought framework (2024) which found that error taxonomy-guided
correction improves accuracy by 8-10% compared to blind regeneration.
"""

from enum import Enum
from dataclasses import dataclass
from typing import List
import re


class ErrorCategory(Enum):
    """PostgreSQL error categories."""
    INDEX_ALREADY_EXISTS = "INDEX_ALREADY_EXISTS"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    SYNTAX_ERROR = "SYNTAX_ERROR"
    TIMEOUT = "TIMEOUT"
    LOCK_CONFLICT = "LOCK_CONFLICT"
    RELATION_NOT_FOUND = "RELATION_NOT_FOUND"
    DISK_FULL = "DISK_FULL"
    CONNECTION_ERROR = "CONNECTION_ERROR"
    UNKNOWN = "UNKNOWN"


class AlternativeStrategy(Enum):
    """Alternative optimization strategies when an action fails."""
    QUERY_REWRITE = "QUERY_REWRITE"
    CHECK_INDEX_USAGE = "CHECK_INDEX_USAGE"
    CREATE_DIFFERENT_INDEX = "CREATE_DIFFERENT_INDEX"
    USE_CONCURRENT_INDEX = "USE_CONCURRENT_INDEX"
    INCREASE_WORK_MEM = "INCREASE_WORK_MEM"
    RUN_VACUUM = "RUN_VACUUM"
    ANALYZE_STATISTICS = "ANALYZE_STATISTICS"
    MARK_DONE = "MARK_DONE"
    MARK_FAILED = "MARK_FAILED"


@dataclass
class ErrorClassification:
    """
    Result of classifying a PostgreSQL error.

    Attributes:
        category: The error category
        message: Human-readable explanation of the error
        guidance: Specific guidance on how to handle this error
        alternatives: List of alternative strategies to try
    """
    category: ErrorCategory
    message: str
    guidance: str
    alternatives: List[AlternativeStrategy]


class ErrorClassifier:
    """
    Classifies PostgreSQL errors and suggests alternative strategies.

    Uses pattern matching to categorize errors and provides structured guidance
    for LLM agents to make better decisions after failures.
    """

    # Error pattern definitions with priorities (lower = higher priority)
    ERROR_PATTERNS = [
        # Priority 1: Specific errors that need exact matches
        {
            "priority": 1,
            "patterns": [r"relation.*already exists", r"index.*already exists"],
            "category": ErrorCategory.INDEX_ALREADY_EXISTS,
            "message": "The index or relation already exists in the database",
            "guidance": "The requested index exists. Check if it's being used in the query plan, or try a different index or query rewrite.",
            "alternatives": [
                AlternativeStrategy.CHECK_INDEX_USAGE,
                AlternativeStrategy.QUERY_REWRITE,
                AlternativeStrategy.CREATE_DIFFERENT_INDEX,
                AlternativeStrategy.MARK_DONE
            ]
        },
        {
            "priority": 1,
            "patterns": [r"permission denied"],
            "category": ErrorCategory.PERMISSION_DENIED,
            "message": "Permission denied - insufficient privileges to perform this operation",
            "guidance": "User lacks necessary database privileges. Cannot create indexes or modify schema without proper permissions.",
            "alternatives": [AlternativeStrategy.QUERY_REWRITE, AlternativeStrategy.MARK_FAILED]
        },
        {
            "priority": 1,
            "patterns": [r"deadlock detected"],
            "category": ErrorCategory.LOCK_CONFLICT,
            "message": "Deadlock detected - conflicting locks on database objects",
            "guidance": "Table is locked by another transaction. Try using CREATE INDEX CONCURRENTLY or wait and retry.",
            "alternatives": [
                AlternativeStrategy.USE_CONCURRENT_INDEX,
                AlternativeStrategy.QUERY_REWRITE,
                AlternativeStrategy.MARK_FAILED
            ]
        },

        # Priority 2: Common errors
        {
            "priority": 2,
            "patterns": [r"syntax error"],
            "category": ErrorCategory.SYNTAX_ERROR,
            "message": "SQL syntax error in the statement",
            "guidance": "The SQL statement has invalid syntax. Review the DDL/query format.",
            "alternatives": [AlternativeStrategy.MARK_FAILED]
        },
        {
            "priority": 2,
            "patterns": [r"timeout", r"canceling statement due to statement timeout"],
            "category": ErrorCategory.TIMEOUT,
            "message": "Statement timeout - operation exceeded time limit",
            "guidance": "Statement timeout reached. Query or DDL operation took too long. Try query rewrite, better indexes, or increasing work_mem.",
            "alternatives": [
                AlternativeStrategy.QUERY_REWRITE,
                AlternativeStrategy.CREATE_DIFFERENT_INDEX,
                AlternativeStrategy.INCREASE_WORK_MEM
            ]
        },
        {
            "priority": 2,
            "patterns": [r"lock.*timeout", r"could not obtain lock"],
            "category": ErrorCategory.LOCK_CONFLICT,
            "message": "Could not acquire lock on database object",
            "guidance": "Unable to acquire necessary lock. Table may be in use. Try CREATE INDEX CONCURRENTLY.",
            "alternatives": [
                AlternativeStrategy.USE_CONCURRENT_INDEX,
                AlternativeStrategy.MARK_FAILED
            ]
        },
        {
            "priority": 2,
            "patterns": [r"relation.*does not exist", r"table.*does not exist"],
            "category": ErrorCategory.RELATION_NOT_FOUND,
            "message": "Referenced table or relation does not exist",
            "guidance": "The table/relation referenced in the query doesn't exist. Check table name spelling and schema.",
            "alternatives": [AlternativeStrategy.MARK_FAILED]
        },

        # Priority 3: System errors
        {
            "priority": 3,
            "patterns": [r"no space left", r"disk full"],
            "category": ErrorCategory.DISK_FULL,
            "message": "Insufficient disk space",
            "guidance": "Database server has run out of disk space. Cannot create indexes until space is freed.",
            "alternatives": [AlternativeStrategy.RUN_VACUUM, AlternativeStrategy.MARK_FAILED]
        },
        {
            "priority": 3,
            "patterns": [r"connection.*refused", r"could not connect"],
            "category": ErrorCategory.CONNECTION_ERROR,
            "message": "Database connection error",
            "guidance": "Unable to connect to database. Check connection string and database availability.",
            "alternatives": [AlternativeStrategy.MARK_FAILED]
        }
    ]

    def __init__(self):
        """Initialize the error classifier."""
        # Sort patterns by priority
        self.patterns = sorted(
            self.ERROR_PATTERNS,
            key=lambda p: p["priority"]
        )

    def classify(self, error: str) -> ErrorClassification:
        """
        Classify a PostgreSQL error message.

        Args:
            error: Raw error message from PostgreSQL

        Returns:
            ErrorClassification with category, message, guidance, and alternatives
        """
        error_lower = error.lower()

        # Try to match against known patterns (prioritized)
        for pattern_def in self.patterns:
            for pattern in pattern_def["patterns"]:
                if re.search(pattern, error_lower):
                    return ErrorClassification(
                        category=pattern_def["category"],
                        message=pattern_def["message"],
                        guidance=pattern_def["guidance"],
                        alternatives=pattern_def["alternatives"]
                    )

        # Unknown error - provide generic guidance
        return ErrorClassification(
            category=ErrorCategory.UNKNOWN,
            message="Unexpected database error",
            guidance="An unexpected error occurred. Review the error message and consider alternative approaches.",
            alternatives=[
                AlternativeStrategy.QUERY_REWRITE,
                AlternativeStrategy.MARK_DONE,
                AlternativeStrategy.MARK_FAILED
            ]
        )

    def format_alternatives_for_llm(self, classification: ErrorClassification) -> str:
        """
        Format alternative strategies for LLM consumption.

        Args:
            classification: The error classification

        Returns:
            Formatted string of alternatives with descriptions
        """
        strategy_descriptions = {
            AlternativeStrategy.QUERY_REWRITE: "Rewrite the query to avoid the problematic operation",
            AlternativeStrategy.CHECK_INDEX_USAGE: "Check if the existing index is being used in the query plan",
            AlternativeStrategy.CREATE_DIFFERENT_INDEX: "Create a different index (e.g., composite, partial, or on different columns)",
            AlternativeStrategy.USE_CONCURRENT_INDEX: "Use CREATE INDEX CONCURRENTLY to avoid blocking",
            AlternativeStrategy.INCREASE_WORK_MEM: "Increase work_mem to handle larger operations",
            AlternativeStrategy.RUN_VACUUM: "Run VACUUM to free up disk space",
            AlternativeStrategy.ANALYZE_STATISTICS: "Run ANALYZE to update table statistics",
            AlternativeStrategy.MARK_DONE: "Accept current state and mark optimization as complete",
            AlternativeStrategy.MARK_FAILED: "Acknowledge failure and stop optimization attempts"
        }

        lines = ["Suggested alternative strategies:"]
        for i, strategy in enumerate(classification.alternatives, 1):
            desc = strategy_descriptions.get(strategy, strategy.value)
            lines.append(f"  {i}. {strategy.value}: {desc}")

        return "\n".join(lines)
