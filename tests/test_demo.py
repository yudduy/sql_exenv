"""
Test Suite for Agentic DBA Components

Demonstrates usage of Model 1 (Analyzer) and Model 2 (Semanticizer)
with sample EXPLAIN plans.
"""

import json
import asyncio
from model_1_analyzer import ExplainAnalyzer
from model_2_semanticizer import MockTranslator


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


def test_model_1_analyzer():
    """Test Model 1: EXPLAIN Plan Analyzer"""
    print("=" * 60)
    print("TEST: Model 1 - EXPLAIN Analyzer")
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


def test_model_2_semanticizer():
    """Test Model 2: Semantic Translator (Mock)"""
    print("\n" + "=" * 60)
    print("TEST: Model 2 - Semantic Translator (Mock Mode)")
    print("=" * 60)
    
    translator = MockTranslator()
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
    """Test complete pipeline with both models"""
    print("\n" + "=" * 60)
    print("TEST: Full Pipeline (Model 1 + Model 2)")
    print("=" * 60)
    
    analyzer = ExplainAnalyzer()
    translator = MockTranslator()
    
    # Simulate iterative optimization
    print("\n🔄 Iteration 1: Initial Query")
    print("-" * 60)
    
    # Slow query
    analysis_1 = analyzer.analyze(SAMPLE_PLANS["slow_seq_scan"])
    feedback_1 = translator.translate(analysis_1, {"max_cost": 1000.0})
    
    print(f"Query Cost: {analysis_1['total_cost']}")
    print(f"Status: {feedback_1['status']}")
    print(f"Feedback: {feedback_1['reason']}")
    print(f"Action: {feedback_1['suggestion']}")
    
    # Agent would apply the index here
    print("\n⚙️  Agent applies: CREATE INDEX idx_users_email ON users(email);")
    
    print("\n🔄 Iteration 2: Validation")
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
    print(f"\n✅ Optimization Complete!")
    print(f"   Cost reduced by {cost_reduction:.2f}%")
    print(f"   From: {analysis_1['total_cost']:.2f} → To: {analysis_2['total_cost']:.2f}")


def demo_output_format():
    """Demonstrate the JSON output format"""
    print("\n" + "=" * 60)
    print("DEMO: JSON Output Format")
    print("=" * 60)
    
    analyzer = ExplainAnalyzer()
    translator = MockTranslator()
    
    analysis = analyzer.analyze(SAMPLE_PLANS["slow_seq_scan"])
    feedback = translator.translate(analysis, {"max_cost": 1000.0})
    
    print("\nModel 1 Output (Technical Analysis):")
    print("-" * 60)
    print(json.dumps(analysis, indent=2))
    
    print("\nModel 2 Output (Semantic Feedback):")
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
    print("\n" + "🧪" * 30)
    print("AGENTIC DBA - TEST SUITE")
    print("🧪" * 30)
    
    test_model_1_analyzer()
    test_model_2_semanticizer()
    test_full_pipeline()
    demo_output_format()
    
    print("\n" + "=" * 60)
    print("✅ All Tests Complete!")
    print("=" * 60)
    print("\nNext Steps:")
    print("1. Test with real PostgreSQL database")
    print("2. Configure Claude Desktop (see README)")
    print("3. Try iterative optimization with live queries")
    print("\n💡 Tip: Use 'python mcp_server.py test' to test with real DB")


if __name__ == "__main__":
    run_all_tests()
