"""Upstream-only tests for bocha and exa search providers.

Blackcat does not have these providers wired in web.py.
These tests are kept here for reference / future re-integration
if the provider implementation is ever cherry-picked from upstream.
"""

import httpx
import pytest

from blackcat.agent.tools.web import WebSearchConfig, WebSearchTool


def _tool(
    provider: str = "brave",
    api_key: str = "",
    base_url: str = "",
    user_agent: str | None = None,
) -> WebSearchTool:
    return WebSearchTool(
        config=WebSearchConfig(provider=provider, api_key=api_key, base_url=base_url),
        user_agent=user_agent,
    )


def _response(
    status: int = 200,
    json: dict | None = None,
) -> httpx.Response:
    """Build a mock httpx.Response with a dummy request attached."""
    r = httpx.Response(status, json=json)
    r._request = httpx.Request("GET", "https://mock")
    return r


# -- Bocha (博查) ----------------------------------------------------------

@pytest.mark.skip(reason="blackcat does not have bocha search provider")
@pytest.mark.asyncio
async def test_bocha_search(monkeypatch):
    async def mock_post(self, url, **kw):
        assert url == "https://api.bochaai.com/v1/web-search"
        assert kw["headers"]["Authorization"] == "Bearer bocha-key"
        assert kw["headers"]["User-Agent"] == "nanobot-search-test"
        assert kw["json"] == {
            "query": "MAI-THINKING-1 model",
            "freshness": "noLimit",
            "summary": True,
            "count": 2,
        }
        return _response(json={
            "webPages": {
                "value": [
                    {
                        "name": "MAI-THINKING-1 - Microsoft Research",
                        "url": "https://www.microsoft.com/research/maithinking-1",
                        "summary": "MAI-THINKING-1 is a 35B-active MoE model with strong reasoning capabilities.",
                        "snippet": "MAI-THINKING-1 achieves 97.0% on AIME 2025 and 52.8% on SWE-Bench Pro.",
                    }
                ]
            }
        })

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)
    tool = _tool(provider="bocha", api_key="bocha-key", user_agent="nanobot-search-test")
    result = await tool.execute(query="MAI-THINKING-1 model", count=2)

    assert "MAI-THINKING-1" in result
    assert "https://www.microsoft.com/research/maithinking-1" in result
    assert "35B-active MoE" in result


@pytest.mark.skip(reason="blackcat does not have bocha search provider")
@pytest.mark.asyncio
async def test_bocha_missing_key_falls_back_to_duckduckgo(monkeypatch):
    class MockDDGS:
        def __init__(self, **kw):
            pass

        def text(self, query, max_results=5):
            return [{"title": "Fallback", "href": "https://ddg.example", "body": "DuckDuckGo fallback"}]

    monkeypatch.setattr("ddgs.DDGS", MockDDGS)
    monkeypatch.delenv("BOCHA_API_KEY", raising=False)

    tool = _tool(provider="bocha")
    result = await tool.execute(query="test")

    assert "DuckDuckGo fallback" in result


@pytest.mark.skip(reason="blackcat does not have bocha search provider")
@pytest.mark.asyncio
async def test_bocha_rate_limited(monkeypatch):
    async def mock_post(self, url, **kw):
        return _response(status=429, json={"error": "rate limit"})

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)
    tool = _tool(provider="bocha", api_key="bocha-key")
    result = await tool.execute(query="test")

    assert "429" in result


# -- Exa -------------------------------------------------------------------

@pytest.mark.skip(reason="blackcat does not have exa search provider")
@pytest.mark.asyncio
async def test_exa_search(monkeypatch):
    async def mock_post(self, url, **kw):
        assert url == "https://api.exa.ai/search"
        assert kw["headers"]["x-api-key"] == "exa-key"
        assert kw["headers"]["User-Agent"] == "nanobot-search-test"
        assert kw["json"] == {
            "query": "test",
            "numResults": 2,
            "contents": {"highlights": True},
        }
        return _response(json={
            "results": [
                {
                    "title": "Exa Result",
                    "url": "https://exa.ai",
                    "highlights": ["Relevant Exa highlight"],
                }
            ]
        })

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)
    tool = _tool(provider="exa", api_key="exa-key", user_agent="nanobot-search-test")
    result = await tool.execute(query="test", count=2)

    assert "Exa Result" in result
    assert "https://exa.ai" in result
    assert "Relevant Exa highlight" in result


@pytest.mark.skip(reason="blackcat does not have exa search provider")
@pytest.mark.asyncio
async def test_exa_search_uses_env_api_key(monkeypatch):
    async def mock_post(self, url, **kw):
        assert kw["headers"]["x-api-key"] == "env-exa-key"
        return _response(json={
            "results": [
                {
                    "title": "Env Exa Result",
                    "url": "https://exa.ai/env",
                    "summary": "Summary fallback",
                }
            ]
        })

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)
    monkeypatch.setenv("EXA_API_KEY", "env-exa-key")
    tool = _tool(provider="exa", api_key="")
    result = await tool.execute(query="test", count=1)

    assert "Env Exa Result" in result
    assert "Summary fallback" in result


@pytest.mark.skip(reason="blackcat does not have exa search provider")
@pytest.mark.asyncio
async def test_exa_search_http_error(monkeypatch):
    async def mock_post(self, url, **kw):
        return _response(status=401, json={"error": "invalid key"})

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)
    tool = _tool(provider="exa", api_key="bad-exa-key")
    result = await tool.execute(query="test")

    assert "Error: Exa search failed (401)" in result


@pytest.mark.skip(reason="blackcat does not have exa search provider")
@pytest.mark.asyncio
async def test_exa_fallback_to_duckduckgo_when_no_key(monkeypatch):
    class MockDDGS:
        def __init__(self, **kw):
            pass

        def text(self, query, max_results=5):
            return [{"title": "Fallback", "href": "https://ddg.example", "body": "DuckDuckGo fallback"}]

    monkeypatch.setattr("ddgs.DDGS", MockDDGS)
    monkeypatch.delenv("EXA_API_KEY", raising=False)

    tool = _tool(provider="exa", api_key="")
    result = await tool.execute(query="test")
    assert "Fallback" in result