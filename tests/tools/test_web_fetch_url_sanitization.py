"""Tests for web_fetch URL sanitization (backtick/quote stripping)."""

from __future__ import annotations

import json
from contextlib import contextmanager
from unittest.mock import patch

import pytest

from nanobot.agent.tools.web import WebFetchTool, _validate_url


def _fake_resolve_public(hostname, port, family=0, type_=0):
    import socket
    return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("93.184.216.34", 0))]


class FakeResponse:
    status_code = 200
    url = "https://example.com/page"
    text = "<html><head><title>T</title></head><body><p>ok</p></body></html>"
    headers = {"content-type": "text/html"}
    def raise_for_status(self): pass
    def json(self): return {}


class FakeStreamResponse:
    headers = {"content-type": "text/html"}
    url = "https://example.com/page"
    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False


class FakeClient:
    def __init__(self, *a, **kw): pass
    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False
    def stream(self, method, url, **kw):
        return FakeStreamResponse()
    async def get(self, url, **kw):
        return FakeResponse()


@contextmanager
def _patched_web_fetch():
    with (
        patch("nanobot.security.network.socket.getaddrinfo", _fake_resolve_public),
        patch("nanobot.agent.tools.web.httpx.AsyncClient", FakeClient),
        patch("nanobot.agent.tools.web._pinned_dns_transport", lambda: object()),
    ):
        yield


# --- urlparse / _validate_url level tests ---

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


# --- WebFetchTool.execute integration tests ---

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
async def test_execute_accepts_cleanable_http_urls(url):
    tool = WebFetchTool()
    with _patched_web_fetch():
        result = await tool.execute(url=url)
    data = json.loads(result)
    assert data["status"] == 200


# --- startswith guard tests ---

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
