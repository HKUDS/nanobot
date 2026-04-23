"""Tests for Olostep web search provider."""

from types import SimpleNamespace

import pytest

import nanobot.agent.tools.web as web_mod
from nanobot.agent.tools.web import WebSearchTool
from nanobot.config.schema import WebSearchConfig


@pytest.mark.asyncio
async def test_olostep_search_formats_answer_and_sources(monkeypatch):
    calls: dict[str, str] = {}

    class MockAsyncOlostep:
        def __init__(self, api_key: str):
            calls["api_key"] = api_key
            self.answers = self

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def create(self, task: str):
            calls["task"] = task
            return SimpleNamespace(
                answer="Mocked Olostep answer",
                sources=[SimpleNamespace(title="Example Source", url="https://example.com")],
            )

    monkeypatch.setattr(web_mod, "_OLOSTEP_AVAILABLE", True)
    monkeypatch.setattr(web_mod, "AsyncOlostep", MockAsyncOlostep)

    tool = WebSearchTool(config=WebSearchConfig(provider="olostep", olostep_api_key="olostep-key"))
    result = await tool.execute(query="test query")

    assert calls["api_key"] == "olostep-key"
    assert calls["task"] == "test query"
    assert "Mocked Olostep answer" in result
    assert "Example Source" in result
    assert "https://example.com" in result


@pytest.mark.asyncio
async def test_olostep_missing_key_returns_config_error(monkeypatch):
    monkeypatch.delenv("OLOSTEP_API_KEY", raising=False)

    tool = WebSearchTool(config=WebSearchConfig(provider="olostep", olostep_api_key=""))
    result = await tool.execute(query="test query")

    assert (
        result
        == "Error: Olostep API key not configured. "
        "Set it in ~/.nanobot/config.json under "
        "tools.web.search.olostepApiKey and restart."
    )


@pytest.mark.asyncio
async def test_olostep_package_missing_returns_install_hint(monkeypatch):
    monkeypatch.setattr(web_mod, "_OLOSTEP_AVAILABLE", False)

    tool = WebSearchTool(config=WebSearchConfig(provider="olostep", olostep_api_key="olostep-key"))
    result = await tool.execute(query="test query")

    assert result == "Error: olostep package not installed. Run: pip install olostep"
