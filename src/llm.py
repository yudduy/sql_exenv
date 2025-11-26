"""
LLM Provider Abstraction Layer

Provides a unified interface for multiple LLM providers (Anthropic, Groq, OpenRouter).
Automatically handles extended thinking for Claude and chain-of-thought fallback for others.
"""

import copy
import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class LLMProvider(Enum):
    """Supported LLM providers."""
    ANTHROPIC = "anthropic"
    GROQ = "groq"
    OPENROUTER = "openrouter"


@dataclass
class LLMConfig:
    """Configuration for LLM client."""
    provider: LLMProvider
    api_key: str
    model: str
    temperature: float = 0.1
    max_tokens: int = 4096
    base_url: str | None = None  # For OpenRouter


@dataclass
class LLMResponse:
    """Unified response from LLM providers."""
    content: str
    thinking: str | None = None  # Extended thinking content (Claude only)
    usage: dict[str, int] | None = None
    model: str | None = None


class BaseLLMClient(ABC):
    """Abstract base class for LLM clients."""

    def __init__(self, config: LLMConfig):
        self.config = config

    @abstractmethod
    def chat(
        self,
        messages: list[dict[str, str]],
        system: str | None = None,
        use_thinking: bool = False,
        thinking_budget: int = 4000,
    ) -> LLMResponse:
        """
        Send a chat completion request.

        Args:
            messages: List of message dicts with 'role' and 'content'
            system: Optional system prompt
            use_thinking: Whether to use extended thinking (Claude) or CoT (others)
            thinking_budget: Token budget for thinking (Claude only)

        Returns:
            LLMResponse with content and optional thinking
        """
        pass

    @property
    def supports_extended_thinking(self) -> bool:
        """Whether this provider supports native extended thinking."""
        return False


class AnthropicClient(BaseLLMClient):
    """Anthropic Claude client with extended thinking support."""

    def __init__(self, config: LLMConfig):
        super().__init__(config)
        try:
            import anthropic
            self.client = anthropic.Anthropic(api_key=config.api_key)
        except ImportError as e:
            raise ImportError(
                "anthropic package required. Install with: pip install anthropic"
            ) from e

    @property
    def supports_extended_thinking(self) -> bool:
        return True

    def chat(
        self,
        messages: list[dict[str, str]],
        system: str | None = None,
        use_thinking: bool = False,
        thinking_budget: int = 4000,
    ) -> LLMResponse:
        kwargs = {
            "model": self.config.model,
            "max_tokens": self.config.max_tokens,
            "messages": messages,
        }

        if system:
            kwargs["system"] = system

        # Use extended thinking for Claude
        if use_thinking:
            kwargs["temperature"] = 1  # Required for extended thinking
            kwargs["thinking"] = {
                "type": "enabled",
                "budget_tokens": max(thinking_budget, 1024),
            }
        else:
            kwargs["temperature"] = self.config.temperature

        response = self.client.messages.create(**kwargs)

        # Extract thinking and content from response
        thinking_content = None
        text_content = ""

        for block in response.content:
            if block.type == "thinking":
                thinking_content = block.thinking
            elif block.type == "text":
                text_content = block.text

        return LLMResponse(
            content=text_content,
            thinking=thinking_content,
            usage={
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
            },
            model=response.model,
        )


class GroqClient(BaseLLMClient):
    """Groq client with chain-of-thought fallback."""

    def __init__(self, config: LLMConfig):
        super().__init__(config)
        try:
            from groq import Groq
            self.client = Groq(api_key=config.api_key)
        except ImportError as e:
            raise ImportError(
                "groq package required. Install with: pip install groq"
            ) from e

    def chat(
        self,
        messages: list[dict[str, str]],
        system: str | None = None,
        use_thinking: bool = False,
        thinking_budget: int = 4000,
    ) -> LLMResponse:
        # Build messages with optional CoT prompt
        # Use deep copy to prevent mutation of caller's messages
        final_messages = []

        if system:
            # Add chain-of-thought instruction if thinking requested
            if use_thinking:
                system = self._add_cot_instruction(system)
            final_messages.append({"role": "system", "content": system})

        final_messages.extend(copy.deepcopy(messages))

        # If thinking requested but no system prompt, add CoT to last user message
        if use_thinking and not system and final_messages:
            last_msg = final_messages[-1]
            if last_msg["role"] == "user":
                last_msg["content"] = self._add_cot_to_message(last_msg["content"])

        response = self.client.chat.completions.create(
            model=self.config.model,
            messages=final_messages,
            temperature=self.config.temperature,
            max_tokens=self.config.max_tokens,
        )

        content = response.choices[0].message.content

        # Extract thinking from CoT response if present
        thinking, final_content = self._extract_cot_thinking(content) if use_thinking else (None, content)

        return LLMResponse(
            content=final_content,
            thinking=thinking,
            usage={
                "input_tokens": response.usage.prompt_tokens,
                "output_tokens": response.usage.completion_tokens,
            } if response.usage else None,
            model=response.model,
        )

    def _add_cot_instruction(self, system: str) -> str:
        """Add chain-of-thought instruction to system prompt."""
        cot_instruction = """

Before providing your final answer, think through the problem step by step.
Structure your response as:

<thinking>
[Your detailed reasoning and analysis here]
</thinking>

<answer>
[Your final response here]
</answer>"""
        return system + cot_instruction

    def _add_cot_to_message(self, content: str) -> str:
        """Add chain-of-thought instruction to user message."""
        return content + "\n\nPlease think through this step by step, showing your reasoning in <thinking> tags before providing your answer in <answer> tags."

    def _extract_cot_thinking(self, content: str) -> tuple[str | None, str]:
        """Extract thinking from chain-of-thought response."""
        import re

        thinking_match = re.search(r"<thinking>(.*?)</thinking>", content, re.DOTALL)
        answer_match = re.search(r"<answer>(.*?)</answer>", content, re.DOTALL)

        thinking = thinking_match.group(1).strip() if thinking_match else None
        final_content = answer_match.group(1).strip() if answer_match else content

        # If answer tags exist but are empty, return the full content instead
        # This handles cases where LLM wraps response incorrectly
        if answer_match and not final_content:
            logger.warning("Empty <answer> tag detected in CoT response, using full content")
            final_content = content

        return thinking, final_content


class OpenRouterClient(BaseLLMClient):
    """OpenRouter client (OpenAI-compatible API)."""

    def __init__(self, config: LLMConfig):
        super().__init__(config)
        try:
            from openai import OpenAI
            self.client = OpenAI(
                api_key=config.api_key,
                base_url=config.base_url or "https://openrouter.ai/api/v1",
            )
        except ImportError as e:
            raise ImportError(
                "openai package required. Install with: pip install openai"
            ) from e

    @property
    def supports_extended_thinking(self) -> bool:
        # OpenRouter can route to Claude models which support extended thinking
        # But we use CoT for simplicity and consistency
        return False

    def chat(
        self,
        messages: list[dict[str, str]],
        system: str | None = None,
        use_thinking: bool = False,
        thinking_budget: int = 4000,
    ) -> LLMResponse:
        # Build messages with optional CoT prompt
        # Use deep copy to prevent mutation of caller's messages
        final_messages = []

        if system:
            if use_thinking:
                system = self._add_cot_instruction(system)
            final_messages.append({"role": "system", "content": system})

        final_messages.extend(copy.deepcopy(messages))

        if use_thinking and not system and final_messages:
            last_msg = final_messages[-1]
            if last_msg["role"] == "user":
                last_msg["content"] = self._add_cot_to_message(last_msg["content"])

        response = self.client.chat.completions.create(
            model=self.config.model,
            messages=final_messages,
            temperature=self.config.temperature,
            max_tokens=self.config.max_tokens,
        )

        content = response.choices[0].message.content

        thinking, final_content = self._extract_cot_thinking(content) if use_thinking else (None, content)

        return LLMResponse(
            content=final_content,
            thinking=thinking,
            usage={
                "input_tokens": response.usage.prompt_tokens,
                "output_tokens": response.usage.completion_tokens,
            } if response.usage else None,
            model=response.model,
        )

    def _add_cot_instruction(self, system: str) -> str:
        """Add chain-of-thought instruction to system prompt."""
        cot_instruction = """

Before providing your final answer, think through the problem step by step.
Structure your response as:

<thinking>
[Your detailed reasoning and analysis here]
</thinking>

<answer>
[Your final response here]
</answer>"""
        return system + cot_instruction

    def _add_cot_to_message(self, content: str) -> str:
        """Add chain-of-thought instruction to user message."""
        return content + "\n\nPlease think through this step by step, showing your reasoning in <thinking> tags before providing your answer in <answer> tags."

    def _extract_cot_thinking(self, content: str) -> tuple[str | None, str]:
        """Extract thinking from chain-of-thought response."""
        import re

        thinking_match = re.search(r"<thinking>(.*?)</thinking>", content, re.DOTALL)
        answer_match = re.search(r"<answer>(.*?)</answer>", content, re.DOTALL)

        thinking = thinking_match.group(1).strip() if thinking_match else None
        final_content = answer_match.group(1).strip() if answer_match else content

        # If answer tags exist but are empty, return the full content instead
        # This handles cases where LLM wraps response incorrectly
        if answer_match and not final_content:
            logger.warning("Empty <answer> tag detected in CoT response, using full content")
            final_content = content

        return thinking, final_content


def create_llm_client(
    provider: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
    **kwargs,
) -> BaseLLMClient:
    """
    Factory function to create an LLM client based on configuration.

    Auto-detects provider from environment variables if not specified:
    1. ANTHROPIC_API_KEY -> Anthropic
    2. GROQ_API_KEY -> Groq
    3. OPENROUTER_API_KEY -> OpenRouter

    Args:
        provider: Provider name ("anthropic", "groq", "openrouter")
        api_key: API key (or uses environment variable)
        model: Model name (uses provider default if not specified)
        **kwargs: Additional config options (temperature, max_tokens, etc.)

    Returns:
        Configured LLM client
    """
    # Auto-detect provider from environment
    if provider is None:
        if os.getenv("ANTHROPIC_API_KEY"):
            provider = "anthropic"
        elif os.getenv("GROQ_API_KEY"):
            provider = "groq"
        elif os.getenv("OPENROUTER_API_KEY"):
            provider = "openrouter"
        else:
            raise ValueError(
                "No LLM provider configured. Set one of: "
                "ANTHROPIC_API_KEY, GROQ_API_KEY, or OPENROUTER_API_KEY"
            )

    provider = provider.lower()

    # Get API key from environment if not provided
    if api_key is None:
        env_var = {
            "anthropic": "ANTHROPIC_API_KEY",
            "groq": "GROQ_API_KEY",
            "openrouter": "OPENROUTER_API_KEY",
        }.get(provider)
        api_key = os.getenv(env_var) if env_var else None

    if not api_key:
        raise ValueError(f"API key required for provider: {provider}")

    # Set default models per provider
    default_models = {
        "anthropic": "claude-sonnet-4-5-20250929",
        "groq": "llama-3.3-70b-versatile",
        "openrouter": "meta-llama/llama-3.3-70b-instruct",
    }
    model = model or default_models.get(provider, "")

    # Create config
    config = LLMConfig(
        provider=LLMProvider(provider),
        api_key=api_key,
        model=model,
        temperature=kwargs.get("temperature", 0.1),
        max_tokens=kwargs.get("max_tokens", 4096),
        base_url=kwargs.get("base_url"),
    )

    # Create client
    if provider == "anthropic":
        return AnthropicClient(config)
    elif provider == "groq":
        return GroqClient(config)
    elif provider == "openrouter":
        return OpenRouterClient(config)
    else:
        raise ValueError(f"Unsupported provider: {provider}")
