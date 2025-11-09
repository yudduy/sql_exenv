"""
Test Suite for SQL Execution Environment Components

Demonstrates usage of Analyzer and Semanticizer with sample EXPLAIN plans.

NOTE: Semanticizer tests require ANTHROPIC_API_KEY environment variable.
"""

import json
import asyncio
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from analyzer import ExplainAnalyzer
from semanticizer import SemanticTranslator


# Sample EXPLAIN outputs from real PostgreSQL queries
SAMPLE_PLANS = {
    "slow_seq_scan": [{
        "Plan": {
            "Node Type": "Seq Scan",
            "Relation Name": "users",
            "Startup Cost": 0.00,
            "Total Cost": 55072.45,
            "Plan Rows": 100000,
            "Plan Width": 244,
            "Actual Startup Time": 0.015,
            "Actual Total Time": 245.123,
            "Actual Rows": 100000,
            "Actual Loops": 1,
            "Filter": "(email = 'test@example.com'::text)",
            "Rows Removed by Filter": 99999
        },
        "Planning Time": 0.123,
        "Execution Time": 245.456
    }],
    
    "optimized_index_scan": [{
        "Plan": {
            "Node Type": "Index Scan",
            "Scan Direction": "Forward",
            "Index Name": "idx_users_email",
            "Relation Name": "users",
            "Startup Cost": 0.42,
            "Total Cost": 14.20,
            "Plan Rows": 1,
            "Plan Width": 244,
            "Actual Startup Time": 0.025,
            "Actual Total Time": 0.028,
            "Actual Rows": 1,
            "Actual Loops": 1,
            "Index Cond": "(email = 'test@example.com'::text)"
        },
        "Planning Time": 0.089,
        "Execution Time": 0.156
    }],
    
    "nested_loop_join": [{
        "Plan": {
            "Node Type": "Nested Loop",
            "Startup Cost": 0.85,
            "Total Cost": 35672.32,
            "Plan Rows": 5000,
            "Plan Width": 488,
            "Actual Startup Time": 0.050,
            "Actual Total Time": 892.345,
            "Actual Rows": 5000,
            "Actual Loops": 1,
            "Plans": [
                {
                    "Node Type": "Seq Scan",
                    "Relation Name": "users",
                    "Startup Cost": 0.00,
                    "Total Cost": 445.00,
                    "Plan Rows": 5000,
                    "Actual Rows": 5000
                },
                {
                    "Node Type": "Index Scan",
                    "Index Name": "orders_user_id_idx",
                    "Relation Name": "orders",
                    "Startup Cost": 0.42,
                    "Total Cost": 7.02,
                    "Plan Rows": 2,
                    "Actual Rows": 2
                }
            ]
        },
        "Planning Time": 0.234,
        "Execution Time": 892.678
    }]
}


def test_analyzer():
    """Test EXPLAIN Plan Analyzer"""
    print("=" * 60)
    print("TEST: EXPLAIN Plan Analyzer")
    print("=" * 60)
    
    analyzer = ExplainAnalyzer()
    
    # Test 1: Slow Sequential Scan
    print("\n1. Testing Sequential Scan Detection:")
    print("-" * 60)
    result = analyzer.analyze(SAMPLE_PLANS["slow_seq_scan"])
    print(f"Summary: {result['summary']}")
    print(f"Total Cost: {result['total_cost']}")
    print(f"Execution Time: {result['execution_time_ms']} ms")
    print(f"Bottlenecks Found: {len(result['bottlenecks'])}")
    
    for bottleneck in result['bottlenecks']:
        print(f"\n  [{bottleneck['severity']}] {bottleneck['node_type']}")
        print(f"  Reason: {bottleneck['reason']}")
        print(f"  Suggestion: {bottleneck['suggestion']}")
    
    # Test 2: Optimized Index Scan
    print("\n2. Testing Optimized Query:")
    print("-" * 60)
    result = analyzer.analyze(SAMPLE_PLANS["optimized_index_scan"])
    print(f"Summary: {result['summary']}")
    print(f"Total Cost: {result['total_cost']}")
    print(f"Bottlenecks Found: {len(result['bottlenecks'])}")
    
    # Test 3: Nested Loop Join
    print("\n3. Testing Nested Loop Join:")
    print("-" * 60)
    result = analyzer.analyze(SAMPLE_PLANS["nested_loop_join"])
    print(f"Summary: {result['summary']}")
    print(f"Total Cost: {result['total_cost']}")
    print(f"Bottlenecks Found: {len(result['bottlenecks'])}")
    
    for bottleneck in result['bottlenecks']:
        print(f"\n  [{bottleneck['severity']}] {bottleneck['node_type']}")
        print(f"  Reason: {bottleneck['reason']}")


def test_semanticizer():
    """Test Semantic Translator"""
    print("\n" + "=" * 60)
    print("TEST: Semantic Translator")
    print("=" * 60)

    # Check for API key
    if not os.environ.get('ANTHROPIC_API_KEY'):
        print("Skipping: ANTHROPIC_API_KEY not set")
        return

    translator = SemanticTranslator()
    analyzer = ExplainAnalyzer()
    
    # Test 1: Failing query (exceeds constraints)
    print("\n1. Query Exceeding Constraints:")
    print("-" * 60)
    analysis = analyzer.analyze(SAMPLE_PLANS["slow_seq_scan"])
    constraints = {"max_cost": 1000.0, "max_time_ms": 100.0}
    
    feedback = translator.translate(analysis, constraints)
    print(f"Status: {feedback['status']}")
    print(f"Priority: {feedback['priority']}")
    print(f"Reason: {feedback['reason']}")
    print(f"Suggestion: {feedback['suggestion']}")
    
    # Test 2: Passing query
    print("\n2. Optimized Query (Passing):")
    print("-" * 60)
    analysis = analyzer.analyze(SAMPLE_PLANS["optimized_index_scan"])
    constraints = {"max_cost": 1000.0}
    
    feedback = translator.translate(analysis, constraints)
    print(f"Status: {feedback['status']}")
    print(f"Priority: {feedback['priority']}")
    print(f"Reason: {feedback['reason']}")
    print(f"Suggestion: {feedback['suggestion']}")


def test_full_pipeline():
    """Test complete pipeline with analyzer and semanticizer"""
    print("\n" + "=" * 60)
    print("TEST: Full Pipeline (Analyzer + Semanticizer)")
    print("=" * 60)

    # Check for API key
    if not os.environ.get('ANTHROPIC_API_KEY'):
        print("Skipping: ANTHROPIC_API_KEY not set")
        return

    analyzer = ExplainAnalyzer()
    translator = SemanticTranslator()
    
    # Simulate iterative optimization
    print("\nIteration 1: Initial Query")
    print("-" * 60)
    
    # Slow query
    analysis_1 = analyzer.analyze(SAMPLE_PLANS["slow_seq_scan"])
    feedback_1 = translator.translate(analysis_1, {"max_cost": 1000.0})
    
    print(f"Query Cost: {analysis_1['total_cost']}")
    print(f"Status: {feedback_1['status']}")
    print(f"Feedback: {feedback_1['reason']}")
    print(f"Action: {feedback_1['suggestion']}")
    
    # Agent would apply the index here
    print("\nAgent applies: CREATE INDEX idx_users_email ON users(email);")

    print("\nIteration 2: Validation")
    print("-" * 60)
    
    # Optimized query
    analysis_2 = analyzer.analyze(SAMPLE_PLANS["optimized_index_scan"])
    feedback_2 = translator.translate(analysis_2, {"max_cost": 1000.0})
    
    print(f"Query Cost: {analysis_2['total_cost']}")
    print(f"Status: {feedback_2['status']}")
    print(f"Feedback: {feedback_2['reason']}")
    
    # Calculate improvement
    cost_reduction = ((analysis_1['total_cost'] - analysis_2['total_cost']) /
                      analysis_1['total_cost'] * 100)
    print(f"\nOptimization Complete!")
    print(f"   Cost reduced by {cost_reduction:.2f}%")
    print(f"   From: {analysis_1['total_cost']:.2f} -> To: {analysis_2['total_cost']:.2f}")


def demo_output_format():
    """Demonstrate the JSON output format"""
    print("\n" + "=" * 60)
    print("DEMO: JSON Output Format")
    print("=" * 60)

    # Check for API key
    if not os.environ.get('ANTHROPIC_API_KEY'):
        print("Skipping: ANTHROPIC_API_KEY not set")
        return

    analyzer = ExplainAnalyzer()
    translator = SemanticTranslator()
    
    analysis = analyzer.analyze(SAMPLE_PLANS["slow_seq_scan"])
    feedback = translator.translate(analysis, {"max_cost": 1000.0})

    print("\nAnalyzer Output (Technical Analysis):")
    print("-" * 60)
    print(json.dumps(analysis, indent=2))

    print("\nSemanticizer Output (Semantic Feedback):")
    print("-" * 60)
    print(json.dumps(feedback, indent=2))
    
    print("\nFinal Tool Response (What Claude Sees):")
    print("-" * 60)
    tool_response = {
        "success": True,
        "feedback": feedback,
        "technical_analysis": analysis
    }
    print(json.dumps(tool_response, indent=2))


def run_all_tests():
    """Run all tests"""
    print("\n" + "=" * 60)
    print("SQL EXECUTION ENVIRONMENT - TEST SUITE")
    print("=" * 60)

    test_analyzer()
    test_semanticizer()
    test_full_pipeline()
    demo_output_format()

    print("\n" + "=" * 60)
    print("All Tests Complete!")
    print("=" * 60)
    print("\nNext Steps:")
    print("1. Test with real PostgreSQL database")
    print("2. Configure Claude Desktop (see README)")
    print("3. Try iterative optimization with live queries")


if __name__ == "__main__":
    run_all_tests()
