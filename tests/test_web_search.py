from __future__ import annotations

import httpx
import pytest
from pydantic import ValidationError

from nanobot.agent.tools.web import WebSearchTool
from nanobot.config.schema import Config, WebSearchConfig


class _MockResponse:
    def __init__(self, payload: dict, status_code: int = 200, url: str = "https://example.com") -> None:
        self._payload = payload
        self.status_code = status_code
        self.url = url

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            request = httpx.Request("GET", self.url)
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError("request failed", request=request, response=response)

    def json(self) -> dict:
        return self._payload


class _MockAsyncClient:
    def __init__(self, response: _MockResponse | None = None, error: Exception | None = None) -> None:
        self._response = response
        self._error = error
        self.last_get: dict | None = None
        self.last_post: dict | None = None

    async def __aenter__(self) -> _MockAsyncClient:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:  # type: ignore[no-untyped-def]
        return None

    async def get(self, url: str, **kwargs):  # type: ignore[no-untyped-def]
        self.last_get = {"url": url, **kwargs}
        if self._error:
            raise self._error
        assert self._response is not None
        return self._response

    async def post(self, url: str, **kwargs):  # type: ignore[no-untyped-def]
        self.last_post = {"url": url, **kwargs}
        if self._error:
            raise self._error
        assert self._response is not None
        return self._response


def _patch_async_client(monkeypatch: pytest.MonkeyPatch, client: _MockAsyncClient) -> None:
    monkeypatch.setattr("nanobot.agent.tools.web.httpx.AsyncClient", lambda *a, **k: client)


def test_web_search_tool_initialization_brave_and_tavily() -> None:
    brave = WebSearchTool(api_key="b-key", provider="brave", max_results=3)
    tavily = WebSearchTool(api_key="t-key", provider="TAVILY", max_results=7)

    assert brave.provider == "brave"
    assert brave.max_results == 3
    assert tavily.provider == "tavily"
    assert tavily.max_results == 7


def test_api_key_resolution_prefers_init_key_for_both_providers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BRAVE_API_KEY", "env-brave")
    monkeypatch.setenv("TAVILY_API_KEY", "env-tavily")

    brave = WebSearchTool(api_key="init-brave", provider="brave")
    tavily = WebSearchTool(api_key="init-tavily", provider="tavily")

    assert brave.api_key == "init-brave"
    assert tavily.api_key == "init-tavily"


def test_api_key_resolution_env_fallback_for_both_providers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BRAVE_API_KEY", "env-brave")
    monkeypatch.setenv("TAVILY_API_KEY", "env-tavily")

    brave = WebSearchTool(provider="brave")
    tavily = WebSearchTool(provider="tavily")

    assert brave.api_key == "env-brave"
    assert tavily.api_key == "env-tavily"


@pytest.mark.asyncio
async def test_brave_search_execution(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "web": {
            "results": [
                {
                    "title": "Brave Result",
                    "url": "https://example.com/brave",
                    "description": "A brave snippet",
                }
            ]
        }
    }
    client = _MockAsyncClient(response=_MockResponse(payload))
    _patch_async_client(monkeypatch, client)

    tool = WebSearchTool(api_key="brave-key", provider="brave")
    result = await tool.execute(query="nanobot")

    assert "Results for: nanobot" in result
    assert "Brave Result" in result
    assert "A brave snippet" in result
    assert client.last_get is not None
    assert client.last_get["url"] == "https://api.search.brave.com/res/v1/web/search"
    assert client.last_get["params"] == {"q": "nanobot", "count": 5}
    assert client.last_get["headers"]["X-Subscription-Token"] == "brave-key"


@pytest.mark.asyncio
async def test_tavily_search_execution(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "results": [
            {
                "title": "Tavily Result",
                "url": "https://example.com/tavily",
                "content": "t" * 250,
            }
        ]
    }
    client = _MockAsyncClient(response=_MockResponse(payload))
    _patch_async_client(monkeypatch, client)

    tool = WebSearchTool(api_key="tavily-key", provider="tavily", max_results=4)
    result = await tool.execute(query="nanobot", count=2)

    assert "Results for: nanobot" in result
    assert "Tavily Result" in result
    assert "https://example.com/tavily" in result
    assert "t" * 50 in result  # content is included
    assert client.last_post is not None
    assert client.last_post["url"] == "https://api.tavily.com/search"
    assert client.last_post["json"] == {
        "api_key": "tavily-key",
        "query": "nanobot",
        "max_results": 2,
    }


@pytest.mark.asyncio
async def test_error_handling_when_no_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BRAVE_API_KEY", raising=False)
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)

    brave = WebSearchTool(provider="brave")
    tavily = WebSearchTool(provider="tavily")

    brave_result = await brave.execute(query="q")
    tavily_result = await tavily.execute(query="q")

    assert "BRAVE_API_KEY" in brave_result
    assert "Tavily" in tavily_result
    assert "TAVILY_API_KEY" in tavily_result


@pytest.mark.asyncio
async def test_error_handling_when_api_call_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _MockAsyncClient(error=httpx.ConnectTimeout("timeout"))
    _patch_async_client(monkeypatch, client)

    tool = WebSearchTool(api_key="brave-key", provider="brave")
    result = await tool.execute(query="nanobot")

    assert result.startswith("Error:")
    assert "timeout" in result


@pytest.mark.asyncio
async def test_error_handling_when_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _MockAsyncClient(response=_MockResponse(payload={}, status_code=500, url="https://api.tavily.com/search"))
    _patch_async_client(monkeypatch, client)

    tool = WebSearchTool(api_key="tavily-key", provider="tavily")
    result = await tool.execute(query="nanobot")

    assert result.startswith("Error:")


@pytest.mark.asyncio
async def test_brave_search_returns_no_results_message(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {"web": {"results": []}}
    client = _MockAsyncClient(response=_MockResponse(payload))
    _patch_async_client(monkeypatch, client)

    tool = WebSearchTool(api_key="brave-key", provider="brave")
    result = await tool.execute(query="nothing-here")

    assert result == "No results for: nothing-here"


def test_web_search_config_schema_validation_accepts_valid_providers() -> None:
    brave = WebSearchConfig(provider="brave", api_key="b", max_results=3)
    tavily = WebSearchConfig(provider="tavily", api_key="t", max_results=8)

    assert brave.provider == "brave"
    assert tavily.provider == "tavily"


def test_web_search_config_schema_validation_rejects_invalid_provider() -> None:
    with pytest.raises(ValidationError):
        WebSearchConfig(provider="duckduckgo", api_key="x", max_results=5)


def test_config_maps_camel_case_web_search_fields() -> None:
    cfg = Config.model_validate(
        {
            "tools": {
                "web": {
                    "search": {
                        "provider": "tavily",
                        "apiKey": "cfg-key",
                        "maxResults": 9,
                    }
                }
            }
        }
    )

    assert cfg.tools.web.search.provider == "tavily"
    assert cfg.tools.web.search.api_key == "cfg-key"
    assert cfg.tools.web.search.max_results == 9


def test_config_back_compat_defaults_provider_when_only_legacy_api_key_is_set() -> None:
    cfg = Config.model_validate(
        {
            "tools": {
                "web": {
                    "search": {
                        "apiKey": "legacy-key",
                        "maxResults": 4,
                    }
                }
            }
        }
    )

    assert cfg.tools.web.search.provider == "brave"
    assert cfg.tools.web.search.api_key == "legacy-key"
    assert cfg.tools.web.search.max_results == 4


@pytest.mark.asyncio
async def test_tavily_count_is_clamped_to_maximum(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {"results": []}
    client = _MockAsyncClient(response=_MockResponse(payload))
    _patch_async_client(monkeypatch, client)

    tool = WebSearchTool(api_key="tavily-key", provider="tavily")
    await tool.execute(query="nanobot", count=50)

    assert client.last_post is not None
    assert client.last_post["json"]["max_results"] == 10


@pytest.mark.asyncio
async def test_brave_count_is_clamped_to_maximum(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {"web": {"results": []}}
    client = _MockAsyncClient(response=_MockResponse(payload))
    _patch_async_client(monkeypatch, client)

    tool = WebSearchTool(api_key="brave-key", provider="brave")
    await tool.execute(query="nanobot", count=999)

    assert client.last_get is not None
    assert client.last_get["params"]["count"] == 10


@pytest.mark.asyncio
async def test_unknown_provider_falls_back_to_brave_search(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {"web": {"results": []}}
    client = _MockAsyncClient(response=_MockResponse(payload))
    _patch_async_client(monkeypatch, client)

    monkeypatch.setenv("BRAVE_API_KEY", "env-brave")
    tool = WebSearchTool(provider="not-a-provider")
    await tool.execute(query="nanobot")

    assert client.last_get is not None
    assert client.last_get["url"] == "https://api.search.brave.com/res/v1/web/search"
