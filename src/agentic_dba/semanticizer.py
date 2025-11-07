"""
Model 2: Semantic Translator (Semanticizer)

This module translates technical database analysis from Model 1 into
natural language feedback that AI agents can understand and act upon.

Uses Claude (or other LLMs) to convert complex metrics into simple
instructions like: "Your query is slow because X. Fix it by doing Y."
"""

import json
from typing import Dict, Any, Optional
import os


class SemanticTranslator:
    """
    Translates technical PostgreSQL analysis into agent-friendly feedback.
    
    This is the "Model 2" in our pipeline that bridges expert-level
    database metrics and actionable natural language instructions.
    """
    
    def __init__(self, api_key: Optional[str] = None, model: str = "claude-3-haiku-20240307"):
        """
        Initialize the semantic translator.
        
        Args:
            api_key: Anthropic API key (or uses ANTHROPIC_API_KEY env var)
            model: Claude model to use for translation
        """
        # Import anthropic here to make it an optional dependency
        try:
            import anthropic
            self.anthropic = anthropic
        except ImportError:
            raise ImportError(
                "anthropic package required for Model 2. "
                "Install with: pip install anthropic"
            )
        
        self.api_key = api_key or os.getenv('ANTHROPIC_API_KEY')
        if not self.api_key:
            raise ValueError("Anthropic API key required (set ANTHROPIC_API_KEY env var)")
        
        self.client = anthropic.Anthropic(api_key=self.api_key)
        self.model = model
    
    def translate(
        self,
        technical_analysis: Dict[str, Any],
        constraints: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Convert technical analysis to semantic feedback.
        
        Args:
            technical_analysis: Output from Model 1 (ExplainAnalyzer)
            constraints: Performance constraints (e.g., max_cost, max_time_ms)
        
        Returns:
            {
                "status": "pass" | "fail" | "warning",
                "reason": "Brief explanation of current state",
                "suggestion": "Specific SQL command or action",
                "priority": "HIGH" | "MEDIUM" | "LOW"
            }
        """
        prompt = self._build_prompt(technical_analysis, constraints)
        
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=2000,
                temperature=0,  # Deterministic for consistent suggestions
                system=self._get_system_prompt(),
                messages=[{"role": "user", "content": prompt}]
            )
            
            # Extract and parse response
            response_text = response.content[0].text
            
            # Clean markdown code blocks if present
            response_text = self._clean_json_response(response_text)
            
            # Parse JSON
            feedback = json.loads(response_text)
            
            # Validate structure
            self._validate_feedback(feedback)
            
            # CRITICAL: Validate Model 2 didn't hallucinate - ensure suggestion uses actual columns from Model 1
            feedback = self._validate_against_analysis(feedback, technical_analysis)
            
            return feedback
            
        except json.JSONDecodeError as e:
            # Fallback if LLM returns invalid JSON
            return {
                "status": "error",
                "reason": f"Failed to parse LLM response: {str(e)}",
                "suggestion": "Manual review required",
                "priority": "HIGH"
            }
        except Exception as e:
            return {
                "status": "error",
                "reason": f"Translation error: {str(e)}",
                "suggestion": "Retry analysis",
                "priority": "HIGH"
            }
    
    def _get_system_prompt(self) -> str:
        """System prompt defining the translator's role."""
        return """You are an expert PostgreSQL DBA helping an AI agent optimize queries.

Your task: Translate technical database analysis into simple, actionable feedback.

CRITICAL RULES:
1. Respond ONLY with valid JSON (no markdown, no explanations)
2. Be concise - agents need clear instructions, not essays
3. Prioritize the most impactful optimization first
4. Suggestions must be executable SQL commands or clear actions
5. NEVER invent or modify column names - use EXACT suggestions from bottlenecks
6. If a bottleneck includes a CREATE INDEX statement, copy it VERBATIM to your suggestion
7. Never hallucinate table or column names not present in the analysis

RESPONSE FORMAT:
{
  "status": "pass" | "fail" | "warning",
  "reason": "1-2 sentence explanation",
  "suggestion": "Specific SQL command or action",
  "priority": "HIGH" | "MEDIUM" | "LOW"
}"""
    
    def _build_prompt(
        self,
        analysis: Dict[str, Any],
        constraints: Dict[str, Any]
    ) -> str:
        """
        Construct the translation prompt with analysis and constraints.
        """
        # Format constraints nicely
        constraints_str = self._format_constraints(constraints)
        
        # Format bottlenecks for clarity
        bottlenecks_str = self._format_bottlenecks(analysis.get('bottlenecks', []))
        
        return f"""TECHNICAL ANALYSIS:
Total Cost: {analysis.get('total_cost', 'unknown')}
Execution Time: {analysis.get('execution_time_ms', 'unknown')} ms
Planning Time: {analysis.get('planning_time_ms', 'unknown')} ms
Optimization Priority: {analysis.get('optimization_priority', 'unknown')}

BOTTLENECKS DETECTED:
{bottlenecks_str}

PERFORMANCE CONSTRAINTS:
{constraints_str}

TASK:
Analyze whether this query meets the constraints. If it fails, provide the SINGLE most impactful fix. If it passes, confirm no optimization needed.

EXAMPLES:

Example 1 - FAIL (Sequential Scan):
{{
  "status": "fail",
  "reason": "Query cost (55,072) far exceeds limit (1,000). Sequential scan on 'users' table is the primary bottleneck.",
  "suggestion": "CREATE INDEX idx_users_email ON users(email);",
  "priority": "HIGH"
}}

Example 2 - PASS:
{{
  "status": "pass",
  "reason": "Query cost (142) is within limit (1,000). Using Index Scan efficiently.",
  "suggestion": "No optimization needed.",
  "priority": "LOW"
}}

Example 3 - WARNING (Minor issue):
{{
  "status": "warning",
  "reason": "Query meets cost constraint but planner statistics are outdated.",
  "suggestion": "ANALYZE users;",
  "priority": "LOW"
}}

Now analyze the data above and respond with ONLY JSON:"""
    
    def _format_constraints(self, constraints: Dict[str, Any]) -> str:
        """Format constraints for the prompt."""
        if not constraints:
            return "None specified"
        
        lines = []
        if 'max_cost' in constraints:
            lines.append(f"- Maximum acceptable cost: {constraints['max_cost']}")
        if 'max_time_ms' in constraints:
            lines.append(f"- Maximum execution time: {constraints['max_time_ms']} ms")
        
        return '\n'.join(lines) if lines else "None specified"
    
    def _format_bottlenecks(self, bottlenecks: list) -> str:
        """Format bottlenecks for the prompt."""
        if not bottlenecks:
            return "None detected"
        
        lines = []
        for i, b in enumerate(bottlenecks, 1):
            severity = b.get('severity', 'UNKNOWN')
            node_type = b.get('node_type', 'Unknown')
            reason = b.get('reason', 'No reason provided')
            suggestion = b.get('suggestion', 'No suggestion')
            
            lines.append(f"{i}. [{severity}] {node_type}: {reason}")
            lines.append(f"   Suggested Fix: {suggestion}")
        
        return '\n'.join(lines)
    
    def _clean_json_response(self, text: str) -> str:
        """Remove markdown code fences and whitespace."""
        # Remove markdown code blocks
        text = text.replace('```json', '').replace('```', '')
        # Remove leading/trailing whitespace
        return text.strip()
    
    def _validate_against_analysis(self, feedback: Dict, technical_analysis: Dict) -> Dict:
        """
        Validate Model 2's suggestion against Model 1's analysis to prevent hallucinations.
        If Model 2 invented column names not in Model 1, replace with Model 1's suggestion.
        """
        model2_suggestion = feedback.get('suggestion', '')
        
        # Get the highest priority suggestion from Model 1
        bottlenecks = technical_analysis.get('bottlenecks', [])
        if not bottlenecks:
            return feedback
        
        # Find first HIGH severity bottleneck with a CREATE INDEX suggestion
        model1_suggestion = None
        for bottleneck in bottlenecks:
            suggestion = bottleneck.get('suggestion', '')
            if suggestion and 'CREATE INDEX' in suggestion and bottleneck.get('severity') == 'HIGH':
                model1_suggestion = suggestion
                break
        
        # If no HIGH severity, try first bottleneck with CREATE INDEX
        if not model1_suggestion:
            for bottleneck in bottlenecks:
                suggestion = bottleneck.get('suggestion', '')
                if suggestion and 'CREATE INDEX' in suggestion:
                    model1_suggestion = suggestion
                    break
        
        # If Model 2 has a CREATE INDEX but it differs significantly from Model 1, use Model 1's
        if model1_suggestion and 'CREATE INDEX' in model2_suggestion:
            # Extract table and column info from both
            import re
            model1_parts = re.findall(r'ON\s+(\w+)\s*\(([^)]+)\)', model1_suggestion)
            model2_parts = re.findall(r'ON\s+(\w+)\s*\(([^)]+)\)', model2_suggestion)
            
            if model1_parts and model2_parts:
                model1_table, model1_cols = model1_parts[0]
                model2_table, model2_cols = model2_parts[0]
                
                # If columns are completely different (hallucination), use Model 1's suggestion
                if model1_cols != model2_cols:
                    feedback['suggestion'] = model1_suggestion
        
        return feedback
    
    def _validate_feedback(self, feedback: Dict) -> None:
        """
        Validate that feedback has required structure.
        
        Raises ValueError if invalid.
        """
        required_keys = {'status', 'reason', 'suggestion', 'priority'}
        missing = required_keys - set(feedback.keys())
        
        if missing:
            raise ValueError(f"Feedback missing required keys: {missing}")
        
        valid_statuses = {'pass', 'fail', 'warning', 'error'}
        if feedback['status'] not in valid_statuses:
            raise ValueError(f"Invalid status: {feedback['status']}")
        
        valid_priorities = {'HIGH', 'MEDIUM', 'LOW'}
        if feedback['priority'] not in valid_priorities:
            raise ValueError(f"Invalid priority: {feedback['priority']}")


class MockTranslator:
    """
    Mock translator for testing without API calls.
    
    Uses rule-based logic to simulate Model 2 behavior.
    Useful for development and testing.
    """
    
    def translate(
        self,
        technical_analysis: Dict[str, Any],
        constraints: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Mock translation using simple rules."""
        total_cost = technical_analysis.get('total_cost', 0)
        max_cost = constraints.get('max_cost', float('inf'))
        bottlenecks = technical_analysis.get('bottlenecks', [])
        
        # Check if constraints violated
        if total_cost > max_cost:
            high_severity = [b for b in bottlenecks if b.get('severity') == 'HIGH']
            
            if high_severity:
                first = high_severity[0]
                return {
                    "status": "fail",
                    "reason": f"Query cost ({total_cost:.0f}) exceeds limit ({max_cost:.0f}). {first['reason']}",
                    "suggestion": first['suggestion'],
                    "priority": "HIGH"
                }
        
        # Query passes constraints
        if not bottlenecks or total_cost <= max_cost:
            return {
                "status": "pass",
                "reason": f"Query cost ({total_cost:.0f}) is within limit ({max_cost:.0f}).",
                "suggestion": "No optimization needed.",
                "priority": "LOW"
            }
        
        # Has bottlenecks but meets constraints - warning
        return {
            "status": "warning",
            "reason": "Query meets constraints but has potential optimizations.",
            "suggestion": bottlenecks[0]['suggestion'],
            "priority": "MEDIUM"
        }


# Example usage
if __name__ == "__main__":
    # Sample technical analysis from Model 1
    sample_analysis = {
        "total_cost": 55072.45,
        "execution_time_ms": 245.456,
        "planning_time_ms": 0.123,
        "bottlenecks": [
            {
                "node_type": "Seq Scan",
                "table": "users",
                "rows": 100000,
                "cost": 55072.45,
                "severity": "HIGH",
                "reason": "Sequential scan on users with 100,000 rows",
                "suggestion": "CREATE INDEX idx_users_email ON users(email);"
            }
        ],
        "optimization_priority": "HIGH"
    }
    
    constraints = {
        "max_cost": 1000.0,
        "max_time_ms": 100.0
    }
    
    # Use mock translator for demo (no API call)
    print("=== Using Mock Translator (No API Call) ===")
    mock_translator = MockTranslator()
    mock_result = mock_translator.translate(sample_analysis, constraints)
    print(json.dumps(mock_result, indent=2))
    
    # Uncomment to use real translator (requires ANTHROPIC_API_KEY)
    # print("\n=== Using Real Translator (API Call) ===")
    # translator = SemanticTranslator()
    # result = translator.translate(sample_analysis, constraints)
    # print(json.dumps(result, indent=2))
