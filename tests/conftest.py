"""
Shared test fixtures for sql_exenv tests.
"""

from unittest.mock import Mock, patch

import pytest
from src.llm import BaseLLMClient, LLMResponse


@pytest.fixture
def mock_llm_client():
    """Mock LLM client for tests that don't need real API calls."""
    client = Mock(spec=BaseLLMClient)
    client.chat.return_value = LLMResponse(
        content='{"action": "DONE", "reasoning": "Query is optimal"}',
        thinking=None,
        usage={"input_tokens": 100, "output_tokens": 50},
        model="mock-model",
    )
    return client


@pytest.fixture
def mock_db_connection():
    """Mock database connection string."""
    return "postgresql://localhost:5432/testdb"


@pytest.fixture(autouse=True)
def auto_mock_llm_client(mock_llm_client):
    """
    Automatically patch create_llm_client for all tests.
    This prevents tests from failing due to missing API keys.
    """
    with patch('src.llm.create_llm_client', return_value=mock_llm_client):
        yield mock_llm_client
