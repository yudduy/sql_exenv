"""
SQL Correctness Validation via Metamorphic Testing

This package implements research-backed correctness validation for SQL queries
using metamorphic testing techniques from academic database testing literature.

Based on:
- Rigger & Su, "Finding Bugs in Database Systems via Query Partitioning" (OOPSLA 2020)
- SQLancer project (github.com/sqlancer/sqlancer)

Key Components:
- TLP (Ternary Logic Partitioning): Validates WHERE clause logic
- NoREC (Non-optimizing Reference Engine Construction): Validates query optimization
"""

from .base import (
    ValidationIssue,
    ValidationResult,
    CorrectnessValidator,
)

__all__ = [
    'ValidationIssue',
    'ValidationResult',
    'CorrectnessValidator',
]
