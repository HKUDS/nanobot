import httpx
import pytest

from nanobot.agent.tools.web import WebSearchTool
from nanobot.config.schema import SearxngSearchConfig, WebSearchConfig


@pytest.mark.asyncio
async def test_searxng_search_formats_results(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SEARXNG_URL", raising=False)
    monkeypatch.delenv("SEARXNG_BASE_URL", raising=False)
    monkeypatch.delenv("SEARXNG_API_KEY", raising=False)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.host == "searx.example.com"
        assert request.url.path == "/search"

        params = dict(request.url.params)
        assert params["q"] == "hello"
        assert params["format"] == "json"
        assert request.headers.get("user-agent")

        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "title": "Example",
                        "url": "https://example.com",
                        "content": "<b>snippet</b> with <i>html</i>",
                    }
                ]
            },
        )

    transport = httpx.MockTransport(handler)
    cfg = WebSearchConfig(
        provider="searxng",
        max_results=3,
        searxng=SearxngSearchConfig(base_url="https://searx.example.com"),
    )
    tool = WebSearchTool(config=cfg, transport=transport)

    out = await tool.execute(query="hello", count=1)
    assert "Results for: hello" in out
    assert "1. Example" in out
    assert "https://example.com" in out
    assert "snippet with html" in out


@pytest.mark.asyncio
async def test_searxng_uses_bearer_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SEARXNG_URL", raising=False)
    monkeypatch.delenv("SEARXNG_BASE_URL", raising=False)
    monkeypatch.delenv("SEARXNG_API_KEY", raising=False)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("authorization") == "Bearer test-token"
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "title": "Example",
                        "url": "https://example.com",
                        "content": "ok",
                    }
                ]
            },
        )

    transport = httpx.MockTransport(handler)
    cfg = WebSearchConfig(
        provider="searxng",
        searxng=SearxngSearchConfig(
            base_url="https://searx.example.com",
            api_key="test-token",
        ),
    )
    tool = WebSearchTool(config=cfg, transport=transport)

    out = await tool.execute(query="hello", count=1)
    assert "Results for: hello" in out


@pytest.mark.asyncio
async def test_searxng_requires_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SEARXNG_URL", raising=False)
    monkeypatch.delenv("SEARXNG_BASE_URL", raising=False)

    cfg = WebSearchConfig(provider="searxng", searxng=SearxngSearchConfig(base_url=""))
    tool = WebSearchTool(config=cfg)

    out = await tool.execute(query="hello")
    assert "SearXNG not configured" in out
