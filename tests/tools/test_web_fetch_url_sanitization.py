"""Tests for web_fetch URL sanitization (backtick/quote stripping)."""

from __future__ import annotations

import json
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


def _patch_env():
    return patch("nanobot.security.network.socket.getaddrinfo", _fake_resolve_public), \
           patch("nanobot.agent.tools.web.httpx.AsyncClient", FakeClient)


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


def test_backtick_url_produces_empty_scheme_in_urlparse():
    from urllib.parse import urlparse
    p = urlparse("`https://example.com/page`")
    assert p.scheme == ""
    assert p.netloc == ""


# --- WebFetchTool.execute integration tests ---

@pytest.mark.asyncio
async def test_execute_strips_backticks_and_succeeds():
    tool = WebFetchTool()
    with _patch_env()[0], _patch_env()[1]:
        result = await tool.execute(url="`https://example.com/page`")
    data = json.loads(result)
    assert "error" not in data, f"unexpected error: {data}"


@pytest.mark.asyncio
async def test_execute_strips_double_quotes_and_succeeds():
    tool = WebFetchTool()
    with _patch_env()[0], _patch_env()[1]:
        result = await tool.execute(url='"https://example.com/page"')
    data = json.loads(result)
    assert "error" not in data, f"unexpected error: {data}"


@pytest.mark.asyncio
async def test_execute_strips_single_quotes_and_succeeds():
    tool = WebFetchTool()
    with _patch_env()[0], _patch_env()[1]:
        result = await tool.execute(url="'https://example.com/page'")
    data = json.loads(result)
    assert "error" not in data, f"unexpected error: {data}"


@pytest.mark.asyncio
async def test_execute_strips_space_and_backticks():
    tool = WebFetchTool()
    with _patch_env()[0], _patch_env()[1]:
        result = await tool.execute(url="  `https://example.com/page`  ")
    data = json.loads(result)
    assert "error" not in data, f"unexpected error: {data}"


@pytest.mark.asyncio
async def test_execute_strips_mixed_markdown_and_quotes():
    tool = WebFetchTool()
    with _patch_env()[0], _patch_env()[1]:
        result = await tool.execute(url='"`https://example.com/page`"')
    data = json.loads(result)
    assert "error" not in data, f"unexpected error: {data}"


@pytest.mark.asyncio
async def test_execute_keeps_case_insensitive_http_scheme():
    tool = WebFetchTool()
    with _patch_env()[0], _patch_env()[1]:
        result = await tool.execute(url="HTTPS://example.com/page")
    data = json.loads(result)
    assert "error" not in data, f"unexpected error: {data}"


# --- startswith guard tests ---

@pytest.mark.asyncio
async def test_execute_rejects_non_http_url_after_cleaning():
    tool = WebFetchTool()
    result = await tool.execute(url="ftp://example.com/file")
    data = json.loads(result)
    assert "error" in data
    assert "URL validation failed" in data["error"]


@pytest.mark.asyncio
async def test_execute_rejects_garbage_after_cleaning():
    tool = WebFetchTool()
    result = await tool.execute(url="`not a url at all`")
    data = json.loads(result)
    assert "error" in data
    assert "URL validation failed" in data["error"]


@pytest.mark.asyncio
async def test_execute_rejects_bare_domain_after_cleaning():
    tool = WebFetchTool()
    result = await tool.execute(url="`example.com/page`")
    data = json.loads(result)
    assert "error" in data
    assert "URL validation failed" in data["error"]
