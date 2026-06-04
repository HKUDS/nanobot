"""Shared fixtures and markers for tests."""

import httpx
import pytest

from blackcat.providers.openai_compat_provider import OpenAICompatProvider


def pytest_configure(config):
    config.addinivalue_line("markers", "llm: tests that require a running LLM (Ollama)")


def _ollama_reachable() -> bool:
    """Check if Ollama is running at localhost:11434."""
    try:
        r = httpx.get("http://localhost:11434/api/tags", timeout=2.0)
        return r.status_code == 200
    except Exception:
        return False


@pytest.fixture(scope="session")
def ollama_available():
    """Return True if Ollama is reachable, False otherwise.

    Tests should use this fixture and skip manually if needed.
    """
    return _ollama_reachable()


@pytest.fixture(scope="session")
def llm_provider(ollama_available):
    """Default LLM provider for tests (Ollama via OpenAI-compatible API).

    Skips if Ollama is not reachable.
    """
    if not ollama_available:
        pytest.skip("Ollama not running at localhost:11434")
    return OpenAICompatProvider(
        api_key="ollama",
        api_base="http://localhost:11434/v1",
        default_model=LLM_TEST_MODEL,
    )


# Default test model — ministral-3 is small, fast, and supports native tool calling.
LLM_TEST_MODEL = "ministral-3:8b"
