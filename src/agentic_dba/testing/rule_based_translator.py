"""
Development-only rule-based translator.

Provides deterministic, non-LLM feedback for development and CI without API calls.
"""
from typing import Dict, Any


class RuleBasedTranslator:
    """
    Rule-based translator for development and testing without API calls.

    Provides deterministic feedback based on analysis patterns.
    Schema information is ignored in rule-based mode.
    """

    def translate(self, analysis: Dict[str, Any], constraints: Dict[str, Any]) -> Dict[str, Any]:
        total_cost = analysis.get('total_cost', 0)
        max_cost = constraints.get('max_cost', float('inf'))
        bottlenecks = analysis.get('bottlenecks', [])

        # Check if constraints violated
        if total_cost > max_cost:
            high_severity = [b for b in bottlenecks if b.get('severity') == 'HIGH']

            if high_severity:
                first = high_severity[0]
                return {
                    "status": "fail",
                    "reason": f"Query cost ({total_cost:.0f}) exceeds limit ({max_cost:.0f}). {first['reason']}",
                    "suggestion": first['suggestion'],
                    "priority": "HIGH",
                }

        # Query passes constraints
        if not bottlenecks or total_cost <= max_cost:
            return {
                "status": "pass",
                "reason": f"Query cost ({total_cost:.0f}) is within limit ({max_cost:.0f}).",
                "suggestion": "No optimization needed.",
                "priority": "LOW",
            }

        # Has bottlenecks but meets constraints - warning
        return {
            "status": "warning",
            "reason": "Query meets constraints but has potential optimizations.",
            "suggestion": bottlenecks[0]['suggestion'],
            "priority": "MEDIUM",
        }
