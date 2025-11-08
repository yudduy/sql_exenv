#!/usr/bin/env python3
"""
BIRD Dataset Validator for Agentic DBA

This script validates the Agentic DBA query optimization system against
the BIRD Mini-Dev benchmark dataset. It runs the optimize_query() function
on all 500 PostgreSQL queries and collects comprehensive metrics.

Usage:
    python bird_validator.py --database bird_dev [options]

Options:
    --database DB        PostgreSQL database name (required)
    --user USER          PostgreSQL user (default: current user)
    --host HOST          PostgreSQL host (default: localhost)
    --port PORT          PostgreSQL port (default: 5432)
    --limit N            Limit to first N queries (default: all 500)
    --mock-translator    Use mock translator instead of Claude API
    --output FILE        Output JSON file (default: bird_validation_results.json)
    --report FILE        Generate markdown report (default: VALIDATION_REPORT.md)
    --verbose            Verbose output
"""

import json
import asyncio
import argparse
import time
from dataclasses import dataclass, asdict
from typing import List, Dict, Any, Optional
from pathlib import Path
import sys

# Import the optimization tool
from mcp_server import QueryOptimizationTool


@dataclass
class ValidationMetrics:
    """Metrics collected for a single query validation."""
    query_id: int
    db_id: str
    question: str
    difficulty: str
    sql_query: str

    # Execution metrics
    optimization_time_ms: float
    success: bool
    error: Optional[str] = None

    # Analysis results
    bottlenecks_found: int = 0
    bottleneck_types: List[str] = None
    total_cost: Optional[float] = None
    execution_time_ms: Optional[float] = None

    # Feedback quality
    status: Optional[str] = None  # pass/fail/warning
    reason: Optional[str] = None
    suggestion: Optional[str] = None
    priority: Optional[str] = None

    # Validation
    suggestion_is_valid_sql: Optional[bool] = None
    suggestion_is_relevant: Optional[bool] = None

    def __post_init__(self):
        if self.bottleneck_types is None:
            self.bottleneck_types = []


@dataclass
class AggregateMetrics:
    """Aggregate metrics across all validated queries."""
    total_queries: int
    successful_queries: int
    failed_queries: int

    # Performance
    avg_optimization_time_ms: float
    max_optimization_time_ms: float

    # Bottleneck detection
    queries_with_bottlenecks: int
    queries_without_bottlenecks: int
    total_bottlenecks_found: int

    # By difficulty
    simple_queries: int
    moderate_queries: int
    challenging_queries: int

    # Feedback status
    pass_count: int
    fail_count: int
    warning_count: int

    # Suggestion quality
    valid_sql_suggestions: int
    invalid_sql_suggestions: int
    relevant_suggestions: int


class BIRDValidator:
    """
    Validates the Agentic DBA system against BIRD Mini-Dev dataset.
    """

    def __init__(
        self,
        db_connection_string: str,
        use_mock_translator: bool = False,
        verbose: bool = False
    ):
        """
        Initialize the validator.

        Args:
            db_connection_string: PostgreSQL connection string
            use_mock_translator: Use mock translator (no API key needed)
            verbose: Print detailed progress
        """
        self.db_connection_string = db_connection_string
        self.verbose = verbose

        # Initialize optimization tool
        self.tool = QueryOptimizationTool(use_mock_translator=use_mock_translator)

        # Load BIRD dataset
        self.queries = self._load_bird_dataset()

        # Results storage
        self.results: List[ValidationMetrics] = []

    def _load_bird_dataset(self) -> List[Dict[str, Any]]:
        """Load BIRD Mini-Dev PostgreSQL queries from JSON."""
        json_path = Path("./mini_dev/minidev/MINIDEV/mini_dev_postgresql.json")

        if not json_path.exists():
            raise FileNotFoundError(
                f"BIRD dataset not found at {json_path}. "
                "Run download script first or check path."
            )

        with open(json_path) as f:
            queries = json.load(f)

        if self.verbose:
            print(f"Loaded {len(queries)} queries from BIRD dataset")

        return queries

    async def validate_query(
        self,
        query_data: Dict[str, Any],
        constraints: Optional[Dict[str, Any]] = None
    ) -> ValidationMetrics:
        """
        Validate a single BIRD query.

        Args:
            query_data: Query dict from BIRD dataset
            constraints: Performance constraints for optimization

        Returns:
            ValidationMetrics with results
        """
        metrics = ValidationMetrics(
            query_id=query_data['question_id'],
            db_id=query_data['db_id'],
            question=query_data['question'],
            difficulty=query_data['difficulty'],
            sql_query=query_data['SQL']
        )

        if constraints is None:
            constraints = {"max_cost": 10000.0}

        start_time = time.time()

        try:
            # Run optimization
            result = await self.tool.optimize_query(
                sql_query=query_data['SQL'],
                db_connection_string=self.db_connection_string,
                constraints=constraints
            )

            elapsed_ms = (time.time() - start_time) * 1000
            metrics.optimization_time_ms = elapsed_ms
            metrics.success = result['success']

            if result['success']:
                # Extract technical analysis
                tech_analysis = result.get('technical_analysis', {})
                metrics.total_cost = tech_analysis.get('total_cost')
                metrics.execution_time_ms = tech_analysis.get('execution_time_ms')
                metrics.bottlenecks_found = len(tech_analysis.get('bottlenecks', []))
                metrics.bottleneck_types = [
                    b['node_type'] for b in tech_analysis.get('bottlenecks', [])
                ]

                # Extract feedback
                feedback = result.get('feedback', {})
                metrics.status = feedback.get('status')
                metrics.reason = feedback.get('reason')
                metrics.suggestion = feedback.get('suggestion')
                metrics.priority = feedback.get('priority')

                # Validate suggestion (basic checks)
                if metrics.suggestion:
                    metrics.suggestion_is_valid_sql = self._validate_sql_syntax(
                        metrics.suggestion
                    )
                    metrics.suggestion_is_relevant = self._check_suggestion_relevance(
                        metrics.suggestion,
                        metrics.bottleneck_types
                    )
            else:
                metrics.error = result.get('error', 'Unknown error')

        except Exception as e:
            elapsed_ms = (time.time() - start_time) * 1000
            metrics.optimization_time_ms = elapsed_ms
            metrics.success = False
            metrics.error = str(e)

        return metrics

    def _validate_sql_syntax(self, suggestion: str) -> bool:
        """
        Basic SQL syntax validation for suggestions.

        Returns:
            True if suggestion looks like valid SQL
        """
        if not suggestion:
            return False

        # Check for common SQL keywords
        sql_keywords = [
            'CREATE INDEX', 'ALTER TABLE', 'SELECT', 'UPDATE',
            'REWRITE', 'OPTIMIZE', 'ANALYZE', 'VACUUM'
        ]

        suggestion_upper = suggestion.upper()

        return any(keyword in suggestion_upper for keyword in sql_keywords)

    def _check_suggestion_relevance(
        self,
        suggestion: str,
        bottleneck_types: List[str]
    ) -> bool:
        """
        Check if suggestion is relevant to detected bottlenecks.

        Returns:
            True if suggestion addresses detected issues
        """
        if not suggestion or not bottleneck_types:
            return True  # Can't determine, assume relevant

        suggestion_upper = suggestion.upper()

        # Map bottleneck types to expected suggestion keywords
        relevance_map = {
            'Seq Scan': ['INDEX', 'CREATE INDEX'],
            'Nested Loop': ['JOIN', 'HASH JOIN', 'MERGE JOIN'],
            'Sort': ['INDEX', 'ORDER BY', 'LIMIT'],
        }

        for bottleneck in bottleneck_types:
            expected_keywords = relevance_map.get(bottleneck, [])
            if any(kw in suggestion_upper for kw in expected_keywords):
                return True

        return False

    async def validate_all(
        self,
        limit: Optional[int] = None,
        start_index: int = 0
    ) -> List[ValidationMetrics]:
        """
        Validate all queries (or subset) from BIRD dataset.

        Args:
            limit: Maximum number of queries to validate
            start_index: Start from this query index

        Returns:
            List of ValidationMetrics
        """
        queries_to_validate = self.queries[start_index:]
        if limit:
            queries_to_validate = queries_to_validate[:limit]

        total = len(queries_to_validate)

        print(f"Validating {total} queries from BIRD dataset...")
        print(f"Database: {self.db_connection_string}")
        print()

        for i, query_data in enumerate(queries_to_validate, start=1):
            if self.verbose or i % 10 == 0:
                print(f"[{i}/{total}] Query {query_data['question_id']} "
                      f"({query_data['db_id']}, {query_data['difficulty']})")

            metrics = await self.validate_query(query_data)
            self.results.append(metrics)

            if self.verbose:
                status_emoji = "✓" if metrics.success else "✗"
                print(f"  {status_emoji} Status: {metrics.status or 'ERROR'}, "
                      f"Bottlenecks: {metrics.bottlenecks_found}, "
                      f"Time: {metrics.optimization_time_ms:.1f}ms")
                if metrics.error:
                    print(f"  Error: {metrics.error}")
                print()

        print(f"\nValidation complete! Processed {len(self.results)} queries.")
        return self.results

    def compute_aggregate_metrics(self) -> AggregateMetrics:
        """Compute aggregate statistics from validation results."""
        if not self.results:
            raise ValueError("No validation results to aggregate")

        successful = [r for r in self.results if r.success]
        failed = [r for r in self.results if not r.success]

        # Optimization time stats
        times = [r.optimization_time_ms for r in self.results]
        avg_time = sum(times) / len(times) if times else 0
        max_time = max(times) if times else 0

        # Bottleneck stats
        queries_with_bottlenecks = len([
            r for r in successful if r.bottlenecks_found > 0
        ])
        total_bottlenecks = sum(r.bottlenecks_found for r in successful)

        # Difficulty distribution
        simple = len([r for r in self.results if r.difficulty == 'simple'])
        moderate = len([r for r in self.results if r.difficulty == 'moderate'])
        challenging = len([r for r in self.results if r.difficulty == 'challenging'])

        # Feedback status
        pass_count = len([r for r in successful if r.status == 'pass'])
        fail_count = len([r for r in successful if r.status == 'fail'])
        warning_count = len([r for r in successful if r.status == 'warning'])

        # Suggestion quality
        with_suggestions = [r for r in successful if r.suggestion]
        valid_sql = len([r for r in with_suggestions if r.suggestion_is_valid_sql])
        relevant = len([r for r in with_suggestions if r.suggestion_is_relevant])

        return AggregateMetrics(
            total_queries=len(self.results),
            successful_queries=len(successful),
            failed_queries=len(failed),
            avg_optimization_time_ms=avg_time,
            max_optimization_time_ms=max_time,
            queries_with_bottlenecks=queries_with_bottlenecks,
            queries_without_bottlenecks=len(successful) - queries_with_bottlenecks,
            total_bottlenecks_found=total_bottlenecks,
            simple_queries=simple,
            moderate_queries=moderate,
            challenging_queries=challenging,
            pass_count=pass_count,
            fail_count=fail_count,
            warning_count=warning_count,
            valid_sql_suggestions=valid_sql,
            invalid_sql_suggestions=len(with_suggestions) - valid_sql,
            relevant_suggestions=relevant
        )

    def save_results(self, output_file: str):
        """Save validation results to JSON file."""
        output_data = {
            'metadata': {
                'dataset': 'BIRD Mini-Dev PostgreSQL',
                'total_queries': len(self.results),
                'database': self.db_connection_string,
                'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
            },
            'aggregate_metrics': asdict(self.compute_aggregate_metrics()),
            'query_results': [asdict(r) for r in self.results]
        }

        with open(output_file, 'w') as f:
            json.dump(output_data, f, indent=2)

        print(f"\nResults saved to {output_file}")

    def generate_report(self, report_file: str):
        """Generate markdown validation report."""
        agg = self.compute_aggregate_metrics()

        report = f"""# BIRD Dataset Validation Report

**Generated**: {time.strftime('%Y-%m-%d %H:%M:%S')}
**Dataset**: BIRD Mini-Dev PostgreSQL
**Database**: {self.db_connection_string}

---

## Executive Summary

Validated **{agg.total_queries}** queries from the BIRD Mini-Dev benchmark against the Agentic DBA query optimization system.

### Success Rate

- ✅ Successful: **{agg.successful_queries}** ({agg.successful_queries/agg.total_queries*100:.1f}%)
- ❌ Failed: **{agg.failed_queries}** ({agg.failed_queries/agg.total_queries*100:.1f}%)

### Performance

- Average optimization time: **{agg.avg_optimization_time_ms:.1f}ms**
- Maximum optimization time: **{agg.max_optimization_time_ms:.1f}ms**

---

## Bottleneck Detection

- Queries with bottlenecks: **{agg.queries_with_bottlenecks}** ({agg.queries_with_bottlenecks/agg.successful_queries*100:.1f}%)
- Queries without bottlenecks: **{agg.queries_without_bottlenecks}**
- Total bottlenecks found: **{agg.total_bottlenecks_found}**

### Feedback Status Distribution

| Status | Count | Percentage |
|--------|-------|------------|
| Pass   | {agg.pass_count} | {agg.pass_count/agg.successful_queries*100:.1f}% |
| Fail   | {agg.fail_count} | {agg.fail_count/agg.successful_queries*100:.1f}% |
| Warning| {agg.warning_count} | {agg.warning_count/agg.successful_queries*100:.1f}% |

---

## Query Difficulty Analysis

| Difficulty | Count | Percentage |
|------------|-------|------------|
| Simple     | {agg.simple_queries} | {agg.simple_queries/agg.total_queries*100:.1f}% |
| Moderate   | {agg.moderate_queries} | {agg.moderate_queries/agg.total_queries*100:.1f}% |
| Challenging| {agg.challenging_queries} | {agg.challenging_queries/agg.total_queries*100:.1f}% |

---

## Suggestion Quality

Analyzed {agg.valid_sql_suggestions + agg.invalid_sql_suggestions} queries with suggestions:

- Valid SQL syntax: **{agg.valid_sql_suggestions}** ({agg.valid_sql_suggestions/(agg.valid_sql_suggestions + agg.invalid_sql_suggestions)*100:.1f}%)
- Relevant suggestions: **{agg.relevant_suggestions}** ({agg.relevant_suggestions/(agg.valid_sql_suggestions + agg.invalid_sql_suggestions)*100:.1f}%)

---

## Top Bottleneck Types

"""

        # Count bottleneck types
        bottleneck_counts = {}
        for r in self.results:
            if r.success and r.bottleneck_types:
                for bt in r.bottleneck_types:
                    bottleneck_counts[bt] = bottleneck_counts.get(bt, 0) + 1

        sorted_bottlenecks = sorted(
            bottleneck_counts.items(),
            key=lambda x: x[1],
            reverse=True
        )

        for bt, count in sorted_bottlenecks[:10]:
            report += f"- **{bt}**: {count} occurrences\n"

        report += "\n---\n\n"

        # Sample successes and failures
        report += "## Sample Results\n\n### Successful Optimizations\n\n"

        successful = [r for r in self.results if r.success and r.status == 'fail'][:3]
        for r in successful:
            report += f"""
#### Query {r.query_id} ({r.difficulty})

**Question**: {r.question}

**Database**: {r.db_id}

**Bottlenecks Found**: {r.bottlenecks_found} ({', '.join(r.bottleneck_types)})

**Suggestion**: {r.suggestion or 'N/A'}

**Cost**: {r.total_cost:.2f if r.total_cost else 'N/A'}

---
"""

        # Failures
        failures = [r for r in self.results if not r.success][:3]
        if failures:
            report += "\n### Failed Validations\n\n"
            for r in failures:
                report += f"""
#### Query {r.query_id} ({r.difficulty})

**Question**: {r.question}

**Error**: {r.error}

---
"""

        report += """
## Recommendations

Based on this validation:

1. **Coverage**: System successfully analyzed {success_rate:.1f}% of queries
2. **Bottleneck Detection**: Identified issues in {bottleneck_rate:.1f}% of successful queries
3. **Suggestion Quality**: {suggestion_quality:.1f}% of suggestions appear valid and relevant

### Next Steps

- Review failed queries to identify system limitations
- Analyze false positives (queries flagged as slow but are optimal)
- Refine Model 1 thresholds based on BIRD query patterns
- Improve Model 2 prompts for better suggestion quality

---

*Generated by BIRD Validator for Agentic DBA*
""".format(
            success_rate=agg.successful_queries / agg.total_queries * 100,
            bottleneck_rate=agg.queries_with_bottlenecks / max(agg.successful_queries, 1) * 100,
            suggestion_quality=(agg.valid_sql_suggestions + agg.relevant_suggestions) / max((agg.valid_sql_suggestions + agg.invalid_sql_suggestions) * 2, 1) * 100
        )

        with open(report_file, 'w') as f:
            f.write(report)

        print(f"Report saved to {report_file}")


async def main():
    """Main entry point for BIRD validator."""
    parser = argparse.ArgumentParser(
        description='Validate Agentic DBA against BIRD Mini-Dev benchmark'
    )
    parser.add_argument('--database', required=True, help='PostgreSQL database name')
    parser.add_argument('--user', default=None, help='PostgreSQL user')
    parser.add_argument('--host', default='localhost', help='PostgreSQL host')
    parser.add_argument('--port', default='5432', help='PostgreSQL port')
    parser.add_argument('--limit', type=int, default=None, help='Limit queries to validate')
    parser.add_argument('--mock-translator', action='store_true',
                        help='Use mock translator (no API key needed)')
    parser.add_argument('--output', default='bird_validation_results.json',
                        help='Output JSON file')
    parser.add_argument('--report', default='VALIDATION_REPORT.md',
                        help='Output markdown report')
    parser.add_argument('--verbose', action='store_true', help='Verbose output')

    args = parser.parse_args()

    # Build connection string
    user_part = f"{args.user}@" if args.user else ""
    conn_string = f"postgresql://{user_part}{args.host}:{args.port}/{args.database}"

    print("=" * 60)
    print("BIRD Dataset Validator")
    print("=" * 60)
    print()

    try:
        # Create validator
        validator = BIRDValidator(
            db_connection_string=conn_string,
            use_mock_translator=args.mock_translator,
            verbose=args.verbose
        )

        # Run validation
        await validator.validate_all(limit=args.limit)

        # Save results
        validator.save_results(args.output)

        # Generate report
        validator.generate_report(args.report)

        print("\n" + "=" * 60)
        print("Validation complete!")
        print("=" * 60)

    except Exception as e:
        print(f"\n❌ Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
