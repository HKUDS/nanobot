"""Tests for Olostep web search provider."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import patch

import nanobot.agent.tools.web as web_mod
from nanobot.agent.tools.web import WebSearchTool
from nanobot.config.schema import WebSearchConfig


def test_olostep_search_formats_answer_and_sources():
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

    with patch.object(web_mod, "AsyncOlostep", MockAsyncOlostep):
        tool = WebSearchTool(config=WebSearchConfig(provider="olostep", api_key="olostep-key"))
        result = asyncio.run(tool.execute(query="test query"))

    assert calls["api_key"] == "olostep-key"
    assert calls["task"] == "test query"
    assert "Mocked Olostep answer" in result
    assert "Example Source" in result
    assert "https://example.com" in result


def test_olostep_missing_key_falls_back_to_duckduckgo():
    class MockDDGS:
        def __init__(self, **kw):
            pass

        def text(self, query, max_results=5):
            return [{"title": "Fallback", "href": "https://ddg.example", "body": "fallback"}]

    with patch.dict(web_mod.os.environ, {}, clear=False), patch("ddgs.DDGS", MockDDGS):
        tool = WebSearchTool(config=WebSearchConfig(provider="olostep", api_key=""))
        result = asyncio.run(tool.execute(query="test query"))

    assert "Fallback" in result


def test_olostep_package_missing_returns_install_hint():
    with patch.object(web_mod, "AsyncOlostep", None):
        tool = WebSearchTool(config=WebSearchConfig(provider="olostep", api_key="olostep-key"))
        result = asyncio.run(tool.execute(query="test query"))

    assert result == "Error: olostep package not installed. Run: pip install olostep"
