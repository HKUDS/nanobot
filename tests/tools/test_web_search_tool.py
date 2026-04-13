"""Tests for multi-provider web search."""

import asyncio

import httpx
import pytest

from nanobot.agent.tools.web import WebSearchTool
from nanobot.config.schema import WebSearchConfig


def _tool(provider: str = "brave", api_key: str = "", base_url: str = "") -> WebSearchTool:
    return WebSearchTool(config=WebSearchConfig(provider=provider, api_key=api_key, base_url=base_url))


def _response(status: int = 200, json: dict | None = None) -> httpx.Response:
    """Build a mock httpx.Response with a dummy request attached."""
    r = httpx.Response(status, json=json)
    r._request = httpx.Request("GET", "https://mock")
    return r


@pytest.mark.asyncio
async def test_brave_search(monkeypatch):
    async def mock_get(self, url, **kw):
        assert "brave" in url
        assert kw["headers"]["X-Subscription-Token"] == "brave-key"
        return _response(json={
            "web": {"results": [{"title": "NanoBot", "url": "https://example.com", "description": "AI assistant"}]}
        })

    monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)
    tool = _tool(provider="brave", api_key="brave-key")
    result = await tool.execute(query="nanobot", count=1)
    assert "NanoBot" in result
    assert "https://example.com" in result


@pytest.mark.asyncio
async def test_tavily_search(monkeypatch):
    async def mock_post(self, url, **kw):
        assert "tavily" in url
        assert kw["headers"]["Authorization"] == "Bearer tavily-key"
        return _response(json={
            "results": [{"title": "OpenClaw", "url": "https://openclaw.io", "content": "Framework"}]
        })

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)
    tool = _tool(provider="tavily", api_key="tavily-key")
    result = await tool.execute(query="openclaw")
    assert "OpenClaw" in result
    assert "https://openclaw.io" in result


@pytest.mark.asyncio
async def test_searxng_search(monkeypatch):
    async def mock_get(self, url, **kw):
        assert "searx.example" in url
        return _response(json={
            "results": [{"title": "Result", "url": "https://example.com", "content": "SearXNG result"}]
        })

    monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)
    tool = _tool(provider="searxng", base_url="https://searx.example")
    result = await tool.execute(query="test")
    assert "Result" in result


@pytest.mark.asyncio
async def test_duckduckgo_search(monkeypatch):
    class MockDDGS:
        def __init__(self, **kw):
            pass

        def text(self, query, max_results=5):
            return [{"title": "DDG Result", "href": "https://ddg.example", "body": "From DuckDuckGo"}]

    monkeypatch.setattr("nanobot.agent.tools.web.DDGS", MockDDGS, raising=False)
    import nanobot.agent.tools.web as web_mod
    monkeypatch.setattr(web_mod, "DDGS", MockDDGS, raising=False)

    from ddgs import DDGS
    monkeypatch.setattr("ddgs.DDGS", MockDDGS)

    tool = _tool(provider="duckduckgo")
    result = await tool.execute(query="hello")
    assert "DDG Result" in result


@pytest.mark.asyncio
async def test_brave_fallback_to_duckduckgo_when_no_key(monkeypatch):
    class MockDDGS:
        def __init__(self, **kw):
            pass

        def text(self, query, max_results=5):
            return [{"title": "Fallback", "href": "https://ddg.example", "body": "DuckDuckGo fallback"}]

    monkeypatch.setattr("ddgs.DDGS", MockDDGS)
    monkeypatch.delenv("BRAVE_API_KEY", raising=False)

    tool = _tool(provider="brave", api_key="")
    result = await tool.execute(query="test")
    assert "Fallback" in result


@pytest.mark.asyncio
async def test_jina_search(monkeypatch):
    async def mock_get(self, url, **kw):
        assert "s.jina.ai" in str(url)
        assert kw["headers"]["Authorization"] == "Bearer jina-key"
        return _response(json={
            "data": [{"title": "Jina Result", "url": "https://jina.ai", "content": "AI search"}]
        })

    monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)
    tool = _tool(provider="jina", api_key="jina-key")
    result = await tool.execute(query="test")
    assert "Jina Result" in result
    assert "https://jina.ai" in result


@pytest.mark.asyncio
async def test_kagi_search(monkeypatch):
    async def mock_get(self, url, **kw):
        assert "kagi.com/api/v0/search" in url
        assert kw["headers"]["Authorization"] == "Bot kagi-key"
        assert kw["params"] == {"q": "test", "limit": 2}
        return _response(json={
            "data": [
                {"t": 0, "title": "Kagi Result", "url": "https://kagi.com", "snippet": "Premium search"},
                {"t": 1, "list": ["ignored related search"]},
            ]
        })

    monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)
    tool = _tool(provider="kagi", api_key="kagi-key")
    result = await tool.execute(query="test", count=2)
    assert "Kagi Result" in result
    assert "https://kagi.com" in result
    assert "ignored related search" not in result


@pytest.mark.asyncio
async def test_unknown_provider():
    tool = _tool(provider="unknown")
    result = await tool.execute(query="test")
    assert "unknown" in result
    assert "Error" in result


@pytest.mark.asyncio
async def test_default_provider_is_brave(monkeypatch):
    async def mock_get(self, url, **kw):
        assert "brave" in url
        return _response(json={"web": {"results": []}})

    monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)
    tool = _tool(provider="", api_key="test-key")
    result = await tool.execute(query="test")
    assert "No results" in result


@pytest.mark.asyncio
async def test_searxng_no_base_url_falls_back(monkeypatch):
    class MockDDGS:
        def __init__(self, **kw):
            pass

        def text(self, query, max_results=5):
            return [{"title": "Fallback", "href": "https://ddg.example", "body": "fallback"}]

    monkeypatch.setattr("ddgs.DDGS", MockDDGS)
    monkeypatch.delenv("SEARXNG_BASE_URL", raising=False)

    tool = _tool(provider="searxng", base_url="")
    result = await tool.execute(query="test")
    assert "Fallback" in result


@pytest.mark.asyncio
async def test_searxng_invalid_url():
    tool = _tool(provider="searxng", base_url="not-a-url")
    result = await tool.execute(query="test")
    assert "Error" in result


@pytest.mark.asyncio
async def test_jina_422_falls_back_to_duckduckgo(monkeypatch):
    class MockDDGS:
        def __init__(self, **kw):
            pass

        def text(self, query, max_results=5):
            return [{"title": "Fallback", "href": "https://ddg.example", "body": "DuckDuckGo fallback"}]

    async def mock_get(self, url, **kw):
        assert "s.jina.ai" in str(url)
        raise httpx.HTTPStatusError(
            "422 Unprocessable Entity",
            request=httpx.Request("GET", str(url)),
            response=httpx.Response(422, request=httpx.Request("GET", str(url))),
        )

    monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)
    monkeypatch.setattr("ddgs.DDGS", MockDDGS)

    tool = _tool(provider="jina", api_key="jina-key")
    result = await tool.execute(query="test")
    assert "DuckDuckGo fallback" in result


@pytest.mark.asyncio
async def test_kagi_fallback_to_duckduckgo_when_no_key(monkeypatch):
    class MockDDGS:
        def __init__(self, **kw):
            pass

        def text(self, query, max_results=5):
            return [{"title": "Fallback", "href": "https://ddg.example", "body": "DuckDuckGo fallback"}]

    monkeypatch.setattr("ddgs.DDGS", MockDDGS)
    monkeypatch.delenv("KAGI_API_KEY", raising=False)

    tool = _tool(provider="kagi", api_key="")
    result = await tool.execute(query="test")
    assert "Fallback" in result


@pytest.mark.asyncio
async def test_jina_search_uses_path_encoded_query(monkeypatch):
    calls = {}

    async def mock_get(self, url, **kw):
        calls["url"] = str(url)
        calls["params"] = kw.get("params")
        return _response(json={
            "data": [{"title": "Jina Result", "url": "https://jina.ai", "content": "AI search"}]
        })

    monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)
    tool = _tool(provider="jina", api_key="jina-key")
    await tool.execute(query="hello world")
    assert calls["url"].rstrip("/") == "https://s.jina.ai/hello%20world"
    assert calls["params"] in (None, {})


@pytest.mark.asyncio
async def test_duckduckgo_timeout_returns_error(monkeypatch):
    """asyncio.wait_for guard should fire when DDG search hangs."""
    import threading
    gate = threading.Event()

    class HangingDDGS:
        def __init__(self, **kw):
            pass

        def text(self, query, max_results=5):
            gate.wait(timeout=10)
            return []

    monkeypatch.setattr("ddgs.DDGS", HangingDDGS)
    tool = _tool(provider="duckduckgo")
    tool.config.timeout = 0.2
    result = await tool.execute(query="test")
    gate.set()
    assert "Error" in result


