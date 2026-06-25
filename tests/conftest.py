"""Shared fixtures and markers for tests."""

import httpx
import pytest

from blackcat.providers.openai_compat_provider import OpenAICompatProvider

# Default test model — ministral-3 is small, fast, and supports native tool calling.
LLM_TEST_MODEL = "ministral-3:8b"


def pytest_configure(config):
    config.addinivalue_line("markers", "llm: tests that require a running LLM (Ollama)")


def _ollama_reachable() -> bool:
    """Check if Ollama is running at localhost:11434."""
    try:
        r = httpx.get("http://localhost:11434/api/tags", timeout=2.0)
        return r.status_code == 200
    except Exception:
        return False

def _ollama_model_available(model: str) -> bool:
    """Check if *model* is installed in the local Ollama instance."""
    try:
        r = httpx.get("http://localhost:11434/api/tags", timeout=2.0)
        if r.status_code != 200:
            return False
        names = {m.get("name", "") for m in r.json().get("models", [])}
        return any(name.startswith(model) for name in names)
    except Exception:
        return False


@pytest.fixture(scope="session")
def ollama_available():
    """Return True if Ollama is reachable AND the test model is installed.

    Tests should use this fixture and skip manually if needed.
    """
    return _ollama_reachable() and _ollama_model_available(LLM_TEST_MODEL)


@pytest.fixture(scope="session")
def llm_provider(ollama_available):
    """Default LLM provider for tests (Ollama via OpenAI-compatible API).

    Skips if Ollama is not reachable or the test model is not installed.
    """
    if not ollama_available:
        pytest.skip(f"Ollama not running at localhost:11434 or {LLM_TEST_MODEL} not installed")
    return OpenAICompatProvider(
        api_key="ollama",
        api_base="http://localhost:11434/v1",
        default_model=LLM_TEST_MODEL,
    )
