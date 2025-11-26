"""
Semantic Translator (Semanticizer)

Translates technical database analysis into natural language feedback
that AI agents can understand and act upon.

Uses LLM to convert complex metrics into simple instructions like:
"Your query is slow because X. Fix it by doing Y."
"""

import json
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from .llm import BaseLLMClient


class SemanticTranslator:
    """
    Translates technical PostgreSQL analysis into agent-friendly feedback.

    Bridges expert-level database metrics and actionable natural language
    instructions using LLM for semantic translation.
    """

    def __init__(
        self,
        llm_client: Optional["BaseLLMClient"] = None,
        provider: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
    ):
        """
        Initialize the semantic translator.

        Args:
            llm_client: Pre-configured LLM client (preferred)
            provider: LLM provider ("anthropic", "groq", "openrouter") - auto-detected if not set
            api_key: API key (or uses environment variable for provider)
            model: Model name (uses provider default if not specified)
        """
        if llm_client:
            self.llm_client = llm_client
        else:
            # Lazy import to avoid circular dependency
            from .llm import create_llm_client
            self.llm_client = create_llm_client(
                provider=provider,
                api_key=api_key,
                model=model,
            )

    def translate(
        self,
        technical_analysis: dict[str, Any],
        constraints: dict[str, Any],
        schema_info: str | None = None
    ) -> dict[str, Any]:
        """
        Convert technical analysis to semantic feedback.

        Args:
            technical_analysis: Output from ExplainAnalyzer
            constraints: Performance constraints (e.g., max_cost, max_time_ms)
            schema_info: Optional database schema with CREATE TABLE statements and sample data

        Returns:
            {
                "status": "pass" | "fail" | "warning",
                "reason": "Brief explanation of current state",
                "suggestion": "Specific SQL command or action",
                "priority": "HIGH" | "MEDIUM" | "LOW"
            }
        """
        prompt = self._build_prompt(technical_analysis, constraints, schema_info)

        try:
            response = self.llm_client.chat(
                messages=[{"role": "user", "content": prompt}],
                system=self._get_system_prompt(),
                use_thinking=False,  # Simple translation, no thinking needed
            )

            # Extract and parse response
            response_text = response.content

            # Clean markdown code blocks if present
            response_text = self._clean_json_response(response_text)

            # Parse JSON
            feedback = json.loads(response_text)

            # Validate structure
            self._validate_feedback(feedback)

            # CRITICAL: Validate against analyzer output to prevent hallucinations
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
            # Provide friendlier, actionable error messages
            err = str(e)
            if ("Error code: 401" in err) and ("authentication_error" in err or "invalid x-api-key" in err.lower()):
                return {
                    "status": "error",
                    "reason": "Authentication Error: Invalid API key",
                    "suggestion": "Check ANTHROPIC_API_KEY env var; ensure key is valid and active",
                    "priority": "HIGH"
                }
            if ("Error code: 429" in err) or ("rate limit" in err.lower()):
                return {
                    "status": "error",
                    "reason": "Rate Limit Error: Too many requests",
                    "suggestion": "Wait a moment and try again",
                    "priority": "MEDIUM"
                }
            if "Error code: 500" in err:
                return {
                    "status": "error",
                    "reason": "Service Error: Anthropic API issue",
                    "suggestion": "Try again in a few minutes",
                    "priority": "MEDIUM"
                }
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
        analysis: dict[str, Any],
        constraints: dict[str, Any],
        schema_info: str | None = None
    ) -> str:
        """
        Construct the translation prompt with analysis, constraints, and schema.
        """
        # Format constraints nicely
        constraints_str = self._format_constraints(constraints)

        # Format bottlenecks for clarity
        bottlenecks_str = self._format_bottlenecks(analysis.get('bottlenecks', []))

        # Include schema section if available
        schema_section = ""
        if schema_info:
            schema_section = f"""
DATABASE SCHEMA:
{schema_info}

IMPORTANT: When suggesting indexes or query modifications, only use table/column names that exist in the schema above.
"""

        return f"""TECHNICAL ANALYSIS:
Total Cost: {analysis.get('total_cost', 'unknown')}
Execution Time: {analysis.get('execution_time_ms', 'unknown')} ms
Planning Time: {analysis.get('planning_time_ms', 'unknown')} ms
Optimization Priority: {analysis.get('optimization_priority', 'unknown')}

BOTTLENECKS DETECTED:
{bottlenecks_str}

PERFORMANCE CONSTRAINTS:
{constraints_str}
{schema_section}
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

    def _format_constraints(self, constraints: dict[str, Any]) -> str:
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

    def _validate_against_analysis(self, feedback: dict, technical_analysis: dict) -> dict:
        """
        Validate semanticizer suggestion against analyzer output to prevent hallucinations.
        If semanticizer invented column names not found in analyzer, replace with analyzer suggestion.
        """
        llm_suggestion = feedback.get('suggestion', '')

        # Get the highest priority suggestion from analyzer
        bottlenecks = technical_analysis.get('bottlenecks', [])
        if not bottlenecks:
            return feedback

        # Find first HIGH severity bottleneck with a CREATE INDEX suggestion
        analyzer_suggestion = None
        for bottleneck in bottlenecks:
            suggestion = bottleneck.get('suggestion', '')
            if suggestion and 'CREATE INDEX' in suggestion and bottleneck.get('severity') == 'HIGH':
                analyzer_suggestion = suggestion
                break

        # If no HIGH severity, try first bottleneck with CREATE INDEX
        if not analyzer_suggestion:
            for bottleneck in bottlenecks:
                suggestion = bottleneck.get('suggestion', '')
                if suggestion and 'CREATE INDEX' in suggestion:
                    analyzer_suggestion = suggestion
                    break

        # If LLM has a CREATE INDEX but it differs significantly from analyzer, use analyzer's
        if analyzer_suggestion and 'CREATE INDEX' in llm_suggestion:
            # Extract table and column info from both
            import re
            analyzer_parts = re.findall(r'ON\s+(\w+)\s*\(([^)]+)\)', analyzer_suggestion)
            llm_parts = re.findall(r'ON\s+(\w+)\s*\(([^)]+)\)', llm_suggestion)

            if analyzer_parts and llm_parts:
                analyzer_table, analyzer_cols = analyzer_parts[0]
                llm_table, llm_cols = llm_parts[0]

                # If columns are completely different (hallucination), use analyzer suggestion
                if analyzer_cols != llm_cols:
                    feedback['suggestion'] = analyzer_suggestion

        return feedback

    def _validate_feedback(self, feedback: dict) -> None:
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

