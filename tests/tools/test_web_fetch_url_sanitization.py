from __future__ import annotations

import json
from unittest.mock import patch

import httpx
import pytest

from nanobot.agent.tools import web
from nanobot.agent.tools.web import WebFetchTool, _validate_url
from nanobot.agent.tools.web_config import WebFetchConfig


def _fake_resolve_public(hostname, port, family=0, type_=0):
    import socket
    return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("93.184.216.34", 0))]


@pytest.mark.parametrize("dirty_url", [
    "`https://example.com/page`",
    " `https://example.com/page` ",
    '"https://example.com/page"',
    "'https://example.com/page'",
    '  "https://example.com/page"  ',
])
def test_dirty_urls_fail_validation(dirty_url):
    is_valid, msg = _validate_url(dirty_url)
    assert not is_valid


def test_clean_url_passes_validation():
    is_valid, msg = _validate_url("https://example.com/page")
    assert is_valid


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        pytest.param("`https://example.com/page`", id="backticks"),
        pytest.param('"https://example.com/page"', id="double-quotes"),
        pytest.param("'https://example.com/page'", id="single-quotes"),
        pytest.param("  `https://example.com/page`  ", id="space-and-backticks"),
        pytest.param('"`https://example.com/page`"', id="mixed-markdown-and-quotes"),
        pytest.param("HTTPS://example.com/page", id="uppercase-scheme"),
    ],
)
async def test_execute_accepts_cleanable_http_urls(url, monkeypatch):
    tool = WebFetchTool(config=WebFetchConfig(use_jina_reader=False))

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://example.com/page"
        return httpx.Response(200, text="page contents")

    monkeypatch.setattr(web, "PinnedDNSAsyncTransport", lambda: httpx.MockTransport(handler))
    monkeypatch.setattr("nanobot.security.network.getproxies", lambda: {})
    with patch("nanobot.security.network.socket.getaddrinfo", _fake_resolve_public):
        result = await tool.execute(url=url)
    data = json.loads(result)
    assert data["status"] == 200
    assert "page contents" in data["text"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        pytest.param("ftp://example.com/file", id="non_http_url_after_cleaning"),
        pytest.param("`not a url at all`", id="garbage_after_cleaning"),
        pytest.param("`example.com/page`", id="bare_domain_after_cleaning"),
    ],
)
async def test_execute_rejects_invalid_url_after_cleaning(url):
    tool = WebFetchTool()
    result = await tool.execute(url=url)
    data = json.loads(result)
    assert "error" in data
    assert "URL validation failed" in data["error"]


async def test_web_fetch_accepts_json_integer_character_limit(monkeypatch):
    from nanobot.agent.tools.registry import ToolRegistry

    async_client = httpx.AsyncClient

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/plain"}, text="x" * 200)

    def mock_client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return async_client(*args, **kwargs)

    monkeypatch.setattr(web.httpx, "AsyncClient", mock_client)
    monkeypatch.setattr("nanobot.security.network.getproxies", lambda: {})
    registry = ToolRegistry()
    registry.register(WebFetchTool(config=WebFetchConfig(use_jina_reader=False)))
    arguments = {"url": "https://example.com/page", "maxChars": 100.0}

    with patch("nanobot.security.network.socket.getaddrinfo", _fake_resolve_public):
        result = await registry.execute("web_fetch", arguments)

    data = json.loads(result)
    assert data["text"].partition("\n\n")[2] == "x" * 100
    assert data["truncated"] is True
    assert type(arguments["maxChars"]) is float
