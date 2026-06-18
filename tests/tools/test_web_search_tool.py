"""Tests for multi-provider web search."""

import httpx
import pytest

from nanobot.agent.tools.web import WebSearchTool
from nanobot.config.schema import WebSearchConfig


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


def test_duckduckgo_search_is_exclusive():
    tool = _tool(provider="duckduckgo")
    assert tool.exclusive is True
    assert tool.concurrency_safe is False


def test_brave_with_api_key_remains_concurrency_safe():
    tool = _tool(provider="brave", api_key="brave-key")
    assert tool.exclusive is False
    assert tool.concurrency_safe is True


def test_brave_without_api_key_is_treated_as_duckduckgo_for_concurrency(monkeypatch):
    monkeypatch.delenv("BRAVE_API_KEY", raising=False)
    tool = _tool(provider="brave", api_key="")
    assert tool.exclusive is True
    assert tool.concurrency_safe is False


@pytest.mark.asyncio
async def test_brave_search(monkeypatch):
    async def mock_get(self, url, **kw):
        assert "brave" in url
        assert kw["headers"]["X-Subscription-Token"] == "brave-key"
        assert kw["headers"]["User-Agent"] == "nanobot-search-test"
        return _response(json={
            "web": {"results": [{"title": "NanoBot", "url": "https://example.com", "description": "AI assistant"}]}
        })

    monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)
    tool = _tool(provider="brave", api_key="brave-key", user_agent="nanobot-search-test")
    result = await tool.execute(query="nanobot", count=1)
    assert "NanoBot" in result
    assert "https://example.com" in result


@pytest.mark.asyncio
async def test_brave_search_retries_rate_limit_once(monkeypatch):
    calls = {"n": 0}
    sleeps: list[float] = []

    async def mock_sleep(delay: float):
        sleeps.append(delay)

    async def mock_get(self, url, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            return _response(status=429, json={"error": "rate limit"})
        return _response(json={
            "web": {"results": [{"title": "Recovered", "url": "https://example.com", "description": "ok"}]}
        })

    monkeypatch.setattr("nanobot.agent.tools.web.asyncio.sleep", mock_sleep)
    monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)

    tool = _tool(provider="brave", api_key="brave-key")
    result = await tool.execute(query="nanobot", count=1)

    assert calls["n"] == 2
    assert "Recovered" in result
    assert sleeps == [1.0]


@pytest.mark.asyncio
async def test_brave_search_returns_clear_rate_limit_after_retries(monkeypatch):
    calls = {"n": 0}

    async def mock_sleep(delay: float):
        return None

    async def mock_get(self, url, **kw):
        calls["n"] += 1
        return _response(status=429, json={"error": "rate limit"})

    monkeypatch.setattr("nanobot.agent.tools.web.asyncio.sleep", mock_sleep)
    monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)

    tool = _tool(provider="brave", api_key="brave-key")
    result = await tool.execute(query="nanobot", count=1)

    assert calls["n"] == 2
    assert "Brave search rate limited" in result
    assert "consecutive web_search" in result


@pytest.mark.asyncio
async def test_tavily_search(monkeypatch):
    async def mock_post(self, url, **kw):
        assert "tavily" in url
        assert kw["headers"]["Authorization"] == "Bearer tavily-key"
        assert kw["headers"]["User-Agent"] == "nanobot-search-test"
        return _response(json={
            "results": [{"title": "OpenClaw", "url": "https://openclaw.io", "content": "Framework"}]
        })

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)
    tool = _tool(provider="tavily", api_key="tavily-key", user_agent="nanobot-search-test")
    result = await tool.execute(query="openclaw")
    assert "OpenClaw" in result
    assert "https://openclaw.io" in result


def test_keenable_without_api_key_is_concurrency_safe(monkeypatch):
    monkeypatch.delenv("KEENABLE_API_KEY", raising=False)
    tool = _tool(provider="keenable", api_key="")
    assert tool.exclusive is False
    assert tool.concurrency_safe is True


@pytest.mark.asyncio
async def test_keenable_search(monkeypatch):
    async def mock_post(self, url, **kw):
        assert "keenable" in url
        assert kw["headers"]["X-API-Key"] == "keen-key"
        assert kw["headers"]["User-Agent"] == "nanobot-search-test"
        assert kw["headers"]["X-Keenable-Title"] == "nanobot"
        return _response(json={
            "results": [{"title": "Keen", "url": "https://keenable.ai", "description": "short", "snippet": "longer excerpt"}]
        })

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)
    tool = _tool(provider="keenable", api_key="keen-key", user_agent="nanobot-search-test")
    result = await tool.execute(query="keenable", count=1)
    assert "Keen" in result
    assert "https://keenable.ai" in result
    assert "longer excerpt" in result


@pytest.mark.asyncio
async def test_keenable_without_api_key_uses_public_endpoint(monkeypatch):
    async def mock_post(self, url, **kw):
        assert url == "https://api.keenable.ai/v1/search/public"
        assert "X-API-Key" not in kw["headers"]
        assert kw["headers"]["X-Keenable-Title"] == "nanobot"
        return _response(json={
            "results": [{"title": "Public", "url": "https://keenable.ai/pub", "description": "ok"}]
        })

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)
    monkeypatch.delenv("KEENABLE_API_KEY", raising=False)
    tool = _tool(provider="keenable", api_key="")
    result = await tool.execute(query="keenable", count=1)
    assert "Public" in result
    assert "https://keenable.ai/pub" in result


@pytest.mark.asyncio
async def test_keenable_search_uses_env_api_key(monkeypatch):
    async def mock_post(self, url, **kw):
        assert kw["headers"]["X-API-Key"] == "env-keen-key"
        return _response(json={
            "results": [{"title": "Env", "url": "https://keenable.ai/env", "description": "ok"}]
        })

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)
    monkeypatch.setenv("KEENABLE_API_KEY", "env-keen-key")
    tool = _tool(provider="keenable", api_key="")
    result = await tool.execute(query="keenable", count=1)
    assert "Env" in result


@pytest.mark.asyncio
async def test_keenable_search_http_error(monkeypatch):
    async def mock_post(self, url, **kw):
        return _response(status=401, json={"error": "invalid key"})

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)
    tool = _tool(provider="keenable", api_key="bad-keen-key")
    result = await tool.execute(query="keenable")
    assert "Error: Keenable search failed (401)" in result


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


@pytest.mark.asyncio
async def test_bocha_rate_limited(monkeypatch):
    async def mock_post(self, url, **kw):
        return _response(status=429, json={"error": "rate limit"})

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)
    tool = _tool(provider="bocha", api_key="bocha-key")
    result = await tool.execute(query="test")

    assert "429" in result


@pytest.mark.asyncio
async def test_volcengine_search(monkeypatch):
    async def mock_post(self, url, **kw):
        assert url == "https://open.feedcoopapi.com/search_api/web_search"
        assert kw["headers"]["Authorization"] == "Bearer volc-key"
        assert kw["headers"]["X-Traffic-Tag"] == "nanobot"
        assert kw["headers"]["User-Agent"] == "nanobot-search-test"
        assert kw["json"] == {
            "Query": "北京周边游",
            "SearchType": "web",
            "Count": 2,
            "NeedSummary": True,
            "TimeRange": "OneWeek",
            "Filter": {"AuthInfoLevel": 1},
            "QueryControl": {"QueryRewrite": True},
        }
        return _response(json={
            "Result": {
                "WebResults": [
                    {
                        "Title": "北京周边游攻略",
                        "Url": "https://example.cn/travel",
                        "Summary": "适合周末出行的路线。",
                        "AuthInfoDes": "非常权威",
                    }
                ]
            }
        })

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)
    tool = _tool(provider="volcengine", api_key="volc-key", user_agent="nanobot-search-test")
    result = await tool.execute(query="北京周边游", count=2, timeRange="OneWeek", authLevel=1, queryRewrite=True)

    assert "北京周边游攻略" in result
    assert "https://example.cn/travel" in result
    assert "非常权威" in result


@pytest.mark.asyncio
async def test_volcengine_missing_key_falls_back_to_duckduckgo(monkeypatch):
    class MockDDGS:
        def __init__(self, **kw):
            pass

        def text(self, query, max_results=5):
            return [{"title": "Fallback", "href": "https://ddg.example", "body": "DuckDuckGo fallback"}]

    monkeypatch.setattr("ddgs.DDGS", MockDDGS)
    monkeypatch.delenv("VOLCENGINE_SEARCH_API_KEY", raising=False)
    monkeypatch.delenv("WEB_SEARCH_API_KEY", raising=False)

    tool = _tool(provider="volcengine")
    result = await tool.execute(query="test")

    assert "DuckDuckGo fallback" in result


@pytest.mark.asyncio
async def test_volcengine_invalid_time_range_returns_error():
    tool = _tool(provider="volcengine", api_key="volc-key")
    result = await tool.execute(query="test", timeRange="Yesterday")

    assert "timeRange must be" in result


@pytest.mark.asyncio
async def test_searxng_search(monkeypatch):
    async def mock_get(self, url, **kw):
        assert "searx.example" in url
        assert kw["headers"]["User-Agent"] == "nanobot-search-test"
        return _response(json={
            "results": [{"title": "Result", "url": "https://example.com", "content": "SearXNG result"}]
        })

    monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)
    tool = _tool(provider="searxng", base_url="https://searx.example", user_agent="nanobot-search-test")
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
        assert kw["headers"]["User-Agent"] == "nanobot-search-test"
        return _response(json={
            "data": [{"title": "Jina Result", "url": "https://jina.ai", "content": "AI search"}]
        })

    monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)
    tool = _tool(provider="jina", api_key="jina-key", user_agent="nanobot-search-test")
    result = await tool.execute(query="test")
    assert "Jina Result" in result
    assert "https://jina.ai" in result


@pytest.mark.asyncio
async def test_kagi_search(monkeypatch):
    async def mock_post(self, url, **kw):
        assert "kagi.com/api/v1/search" in url
        assert kw["headers"]["Authorization"] == "Bearer kagi-key"
        assert kw["headers"]["User-Agent"] == "nanobot-search-test"
        assert kw["json"] == {"query": "test", "limit": 2}
        return _response(json={
            "data": {
                "search": [
                    {"title": "Kagi Result", "url": "https://kagi.com", "snippet": "Premium search"},
                ],
                "related_search": [
                    {"title": "ignored related search", "url": "", "snippet": ""},
                ],
            }
        })

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)
    tool = _tool(provider="kagi", api_key="kagi-key", user_agent="nanobot-search-test")
    result = await tool.execute(query="test", count=2)
    assert "Kagi Result" in result
    assert "https://kagi.com" in result
    assert "ignored related search" not in result


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


@pytest.mark.asyncio
async def test_exa_search_http_error(monkeypatch):
    async def mock_post(self, url, **kw):
        return _response(status=401, json={"error": "invalid key"})

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)
    tool = _tool(provider="exa", api_key="bad-exa-key")
    result = await tool.execute(query="test")

    assert "Error: Exa search failed (401)" in result


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


@pytest.mark.asyncio
async def test_olostep_search_formats_answer_and_sources(monkeypatch):
    from types import SimpleNamespace

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

    import sys
    import types

    fake_mod = types.ModuleType("olostep")
    fake_mod.AsyncOlostep = MockAsyncOlostep
    fake_mod.Olostep_BaseError = Exception
    monkeypatch.setitem(sys.modules, "olostep", fake_mod)

    tool = _tool(provider="olostep", api_key="olostep-key")
    result = await tool.execute(query="test query")

    assert calls["api_key"] == "olostep-key"
    assert calls["task"] == "test query"
    assert "Mocked Olostep answer" in result
    assert "Example Source" in result
    assert "https://example.com" in result


@pytest.mark.asyncio
async def test_olostep_missing_key_falls_back_to_duckduckgo(monkeypatch):
    import sys
    import types
    from unittest.mock import patch

    class MockDDGS:
        def __init__(self, **kw):
            pass

        def text(self, query, max_results=5):
            return [{"title": "Fallback", "href": "https://ddg.example", "body": "fallback"}]

    fake_mod = types.ModuleType("olostep")
    fake_mod.AsyncOlostep = object
    fake_mod.Olostep_BaseError = Exception
    monkeypatch.setitem(sys.modules, "olostep", fake_mod)

    monkeypatch.delenv("OLOSTEP_API_KEY", raising=False)
    with patch("ddgs.DDGS", MockDDGS):
        tool = _tool(provider="olostep", api_key="")
        result = await tool.execute(query="test query")

    assert "Fallback" in result


@pytest.mark.asyncio
async def test_olostep_package_missing_returns_install_hint(monkeypatch):
    import sys
    monkeypatch.delitem(sys.modules, "olostep", raising=False)
    monkeypatch.setitem(sys.modules, "olostep", None)
    tool = _tool(provider="olostep", api_key="olostep-key")
    result = await tool.execute(query="test query")

    assert result == "Error: olostep package not installed. Run: pip install olostep"
