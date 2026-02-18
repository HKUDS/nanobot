import httpx
import pytest
from collections.abc import Callable
from typing import Literal

from nanobot.agent.tools.web import WebSearchTool
from nanobot.config.schema import WebSearchConfig


def _tool(config: WebSearchConfig, handler) -> WebSearchTool:
    return WebSearchTool(config=config, transport=httpx.MockTransport(handler))


def _assert_tavily_request(request: httpx.Request) -> bool:
    return (
        request.method == "POST"
        and str(request.url) == "https://api.tavily.com/search"
        and request.headers.get("authorization") == "Bearer tavily-key"
        and '"query":"openclaw"' in request.read().decode("utf-8")
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("provider", "config_kwargs", "query", "count", "assert_request", "response", "assert_text"),
    [
        (
            "brave",
            {"api_key": "brave-key"},
            "nanobot",
            1,
            lambda request: (
                request.method == "GET"
                and str(request.url)
                == "https://api.search.brave.com/res/v1/web/search?q=nanobot&count=1"
                and request.headers["X-Subscription-Token"] == "brave-key"
            ),
            httpx.Response(
                200,
                json={
                    "web": {
                        "results": [
                            {
                                "title": "NanoBot",
                                "url": "https://example.com/nanobot",
                                "description": "Ultra-lightweight assistant",
                            }
                        ]
                    }
                },
            ),
            ["Results for: nanobot", "1. NanoBot", "https://example.com/nanobot"],
        ),
        (
            "tavily",
            {"api_key": "tavily-key"},
            "openclaw",
            2,
            _assert_tavily_request,
            httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "title": "OpenClaw",
                            "url": "https://example.com/openclaw",
                            "content": "Plugin-based assistant framework",
                        }
                    ]
                },
            ),
            ["Results for: openclaw", "1. OpenClaw", "https://example.com/openclaw"],
        ),
        (
            "searxng",
            {"base_url": "https://searx.example"},
            "nanobot",
            1,
            lambda request: (
                request.method == "GET"
                and str(request.url) == "https://searx.example/search?q=nanobot&format=json"
            ),
            httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "title": "nanobot docs",
                            "url": "https://example.com/nanobot",
                            "content": "Lightweight assistant docs",
                        }
                    ]
                },
            ),
            ["Results for: nanobot", "1. nanobot docs", "https://example.com/nanobot"],
        ),
    ],
)
async def test_web_search_provider_formats_results(
    provider: Literal["brave", "tavily", "searxng"],
    config_kwargs: dict,
    query: str,
    count: int,
    assert_request: Callable[[httpx.Request], bool],
    response: httpx.Response,
    assert_text: list[str],
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert assert_request(request)
        return response

    tool = _tool(WebSearchConfig(provider=provider, max_results=5, **config_kwargs), handler)
    result = await tool.execute(query=query, count=count)
    for text in assert_text:
        assert text in result


@pytest.mark.asyncio
async def test_web_search_from_legacy_config_works() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "web": {
                    "results": [
                        {"title": "Legacy", "url": "https://example.com", "description": "ok"}
                    ]
                }
            },
        )

    config = WebSearchConfig(api_key="legacy-key", max_results=3)
    tool = WebSearchTool(config=config, transport=httpx.MockTransport(handler))
    result = await tool.execute(query="constructor", count=1)
    assert "1. Legacy" in result


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("provider", "config", "missing_env", "expected_title"),
    [
        (
            "brave",
            WebSearchConfig(provider="brave", api_key="", max_results=5),
            "BRAVE_API_KEY",
            "Fallback Result",
        ),
        (
            "tavily",
            WebSearchConfig(provider="tavily", api_key="", max_results=5),
            "TAVILY_API_KEY",
            "Tavily Fallback",
        ),
    ],
)
async def test_web_search_missing_key_falls_back_to_duckduckgo(
    monkeypatch: pytest.MonkeyPatch,
    provider: str,
    config: WebSearchConfig,
    missing_env: str,
    expected_title: str,
) -> None:
    monkeypatch.delenv(missing_env, raising=False)

    called = False

    class FakeDDGS:
        def __init__(self, *args, **kwargs):
            pass

        def text(self, keywords: str, max_results: int):
            nonlocal called
            called = True
            return [
                {
                    "title": expected_title,
                    "href": f"https://example.com/{provider}-fallback",
                    "body": "Fallback snippet",
                }
            ]

    monkeypatch.setattr("nanobot.agent.tools.web.DDGS", FakeDDGS, raising=False)

    result = await WebSearchTool(config=config).execute(query="fallback", count=1)
    assert called
    assert "Using DuckDuckGo fallback" in result
    assert f"1. {expected_title}" in result


@pytest.mark.asyncio
async def test_web_search_brave_missing_key_without_fallback_returns_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("BRAVE_API_KEY", raising=False)
    tool = WebSearchTool(
        config=WebSearchConfig(
            provider="brave",
            api_key="",
            fallback_to_duckduckgo=False,
        )
    )

    result = await tool.execute(query="fallback", count=1)
    assert result == "Error: BRAVE_API_KEY not configured"


@pytest.mark.asyncio
async def test_web_search_searxng_missing_base_url_falls_back_to_duckduckgo() -> None:
    tool = WebSearchTool(
        config=WebSearchConfig(provider="searxng", base_url="", max_results=5)
    )

    result = await tool.execute(query="nanobot", count=1)
    assert "DuckDuckGo fallback" in result
    assert "SEARXNG_BASE_URL" in result


@pytest.mark.asyncio
async def test_web_search_searxng_missing_base_url_no_fallback_returns_error() -> None:
    tool = WebSearchTool(
        config=WebSearchConfig(
            provider="searxng", base_url="",
            fallback_to_duckduckgo=False, max_results=5,
        )
    )

    result = await tool.execute(query="nanobot", count=1)
    assert result == "Error: SEARXNG_BASE_URL not configured"


@pytest.mark.asyncio
async def test_web_search_searxng_uses_env_base_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SEARXNG_BASE_URL", "https://searx.env")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert str(request.url) == "https://searx.env/search?q=nanobot&format=json"
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "title": "env result",
                        "url": "https://example.com/env",
                        "content": "from env",
                    }
                ]
            },
        )

    config = WebSearchConfig(provider="searxng", base_url="", max_results=5)
    result = await _tool(config, handler).execute(query="nanobot", count=1)
    assert "1. env result" in result


@pytest.mark.asyncio
async def test_web_search_register_custom_provider() -> None:
    config = WebSearchConfig(provider="custom", max_results=5)
    tool = WebSearchTool(config=config)

    async def _custom_provider(query: str, n: int) -> str:
        return f"custom:{query}:{n}"

    tool._provider_dispatch["custom"] = _custom_provider

    result = await tool.execute(query="nanobot", count=2)
    assert result == "custom:nanobot:2"


@pytest.mark.asyncio
async def test_web_search_duckduckgo_uses_injected_ddgs_factory() -> None:
    class FakeDDGS:
        def text(self, keywords: str, max_results: int):
            assert keywords == "nanobot"
            assert max_results == 1
            return [
                {
                    "title": "NanoBot result",
                    "href": "https://example.com/nanobot",
                    "body": "Search content",
                }
            ]

    tool = WebSearchTool(
        config=WebSearchConfig(provider="duckduckgo", max_results=5),
        ddgs_factory=lambda: FakeDDGS(),
    )

    result = await tool.execute(query="nanobot", count=1)
    assert "1. NanoBot result" in result


@pytest.mark.asyncio
async def test_web_search_unknown_provider_returns_error() -> None:
    tool = WebSearchTool(
        config=WebSearchConfig(provider="google", max_results=5),
    )
    result = await tool.execute(query="nanobot", count=1)
    assert result == "Error: unknown search provider 'google'"


@pytest.mark.asyncio
async def test_web_search_dispatch_dict_overwrites_builtin() -> None:
    async def _custom_brave(query: str, n: int) -> str:
        return f"custom-brave:{query}:{n}"

    tool = WebSearchTool(
        config=WebSearchConfig(provider="brave", api_key="key", max_results=5),
    )
    tool._provider_dispatch["brave"] = _custom_brave
    result = await tool.execute(query="nanobot", count=2)
    assert result == "custom-brave:nanobot:2"


@pytest.mark.asyncio
async def test_web_search_searxng_rejects_invalid_url() -> None:
    tool = WebSearchTool(
        config=WebSearchConfig(
            provider="searxng",
            base_url="ftp://internal.host",
            max_results=5,
        ),
    )
    result = await tool.execute(query="nanobot", count=1)
    assert "Error: invalid SearXNG URL" in result
