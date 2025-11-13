"""
Base classes and interfaces for SQL correctness validators.

Defines abstract interfaces for implementing metamorphic testing validators
like TLP (Ternary Logic Partitioning) and NoREC (Non-optimizing Reference
Engine Construction).

Based on SQLancer architecture: github.com/sqlancer/sqlancer
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from abc import ABC, abstractmethod
from enum import Enum


class IssueSeverity(Enum):
    """Severity levels for validation issues"""
    ERROR = "ERROR"
    WARNING = "WARNING"
    INFO = "INFO"


@dataclass
class ValidationIssue:
    """
    Represents a single correctness issue detected during validation.

    Attributes:
        issue_type: Type of issue (e.g., "PARTITION_MISMATCH", "ROW_COUNT_DIFF")
        description: Human-readable description of the issue
        severity: Severity level (ERROR, WARNING, INFO)
        evidence: Supporting data for the issue (e.g., row counts, queries)
        suggested_fix: Natural language suggestion for fixing the issue
    """
    issue_type: str
    description: str
    severity: str  # "ERROR", "WARNING", "INFO"
    evidence: Dict[str, Any] = field(default_factory=dict)
    suggested_fix: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        return {
            'issue_type': self.issue_type,
            'description': self.description,
            'severity': self.severity,
            'evidence': self.evidence,
            'suggested_fix': self.suggested_fix,
        }


@dataclass
class ValidationResult:
    """
    Result of a correctness validation run.

    Attributes:
        passed: Whether validation passed (True) or failed (False)
        confidence: Confidence level in the validation result (0.0 to 1.0)
        method: Validation method used (e.g., "TLP", "NoREC", "TLP+NoREC")
        issues: List of detected issues (empty if passed)
        execution_time_ms: Time taken to perform validation
        queries_executed: Number of queries executed during validation
        metadata: Additional metadata about the validation
    """
    passed: bool
    confidence: float  # 0.0 to 1.0
    method: str
    issues: List[ValidationIssue] = field(default_factory=list)
    execution_time_ms: float = 0.0
    queries_executed: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        return {
            'passed': self.passed,
            'confidence': self.confidence,
            'method': self.method,
            'issues': [issue.to_dict() for issue in self.issues],
            'execution_time_ms': self.execution_time_ms,
            'queries_executed': self.queries_executed,
            'metadata': self.metadata,
        }


class CorrectnessValidator(ABC):
    """
    Abstract base class for SQL correctness validators.

    Implements the Strategy pattern for different validation methods
    (TLP, NoREC, PQS, etc.).

    Example:
        ```python
        validator = TLPValidator()
        result = await validator.validate(
            query="SELECT * FROM users WHERE age > 25",
            db_connection="postgresql://localhost/mydb"
        )
        if not result.passed:
            for issue in result.issues:
                print(f"Error: {issue.description}")
        ```
    """

    @abstractmethod
    async def validate(
        self,
        query: str,
        db_connection: str,
    ) -> ValidationResult:
        """
        Validate query correctness.

        Args:
            query: SQL query to validate
            db_connection: Database connection string

        Returns:
            ValidationResult containing pass/fail status and any detected issues

        Raises:
            ValueError: If query or connection string is invalid
            ConnectionError: If database connection fails
        """
        pass

    def _create_error_result(
        self,
        method: str,
        error_message: str,
        issue_type: str = "VALIDATION_ERROR",
    ) -> ValidationResult:
        """
        Helper to create error result for validation failures.

        Args:
            method: Validation method name
            error_message: Error message describing what went wrong
            issue_type: Type of validation error

        Returns:
            ValidationResult with passed=False and error issue
        """
        issue = ValidationIssue(
            issue_type=issue_type,
            description=error_message,
            severity="ERROR",
            suggested_fix="Review query syntax and database connection",
        )

        return ValidationResult(
            passed=False,
            confidence=0.0,
            method=method,
            issues=[issue],
            execution_time_ms=0.0,
            queries_executed=0,
        )
