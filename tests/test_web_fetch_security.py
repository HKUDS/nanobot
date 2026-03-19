"""Tests for web_fetch SSRF protection and untrusted content marking."""

from __future__ import annotations

import json
import socket
from unittest.mock import patch

import pytest

from nanobot.agent.tools.web import WebFetchTool


def _fake_resolve_private(hostname, port, family=0, type_=0):
    return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("169.254.169.254", 0))]


def _fake_resolve_public(hostname, port, family=0, type_=0):
    return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("93.184.216.34", 0))]


@pytest.mark.asyncio
async def test_web_fetch_blocks_private_ip():
    tool = WebFetchTool()
    with patch("nanobot.security.network.socket.getaddrinfo", _fake_resolve_private):
        result = await tool.execute(url="http://169.254.169.254/computeMetadata/v1/")
    data = json.loads(result)
    assert "error" in data
    assert "private" in data["error"].lower() or "blocked" in data["error"].lower()


@pytest.mark.asyncio
async def test_web_fetch_blocks_localhost():
    tool = WebFetchTool()
    def _resolve_localhost(hostname, port, family=0, type_=0):
        return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("127.0.0.1", 0))]
    with patch("nanobot.security.network.socket.getaddrinfo", _resolve_localhost):
        result = await tool.execute(url="http://localhost/admin")
    data = json.loads(result)
    assert "error" in data


@pytest.mark.asyncio
async def test_web_fetch_allowlist_bypasses_private_ip():
    """WebFetchTool with allowed_hosts must pass validation for private-resolving allowlisted hosts."""
    allowed = frozenset(["gitlab.gleezy.cn"])
    tool = WebFetchTool(allowed_hosts=allowed)

    def _resolve_gitlab(hostname, port, family=0, type_=0):
        return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("172.16.1.10", 0))]

    with patch("nanobot.security.network.socket.getaddrinfo", _resolve_gitlab):
        ok, err = tool._validate_url_safe("https://gitlab.gleezy.cn/api/v4/projects")
    assert ok, f"Allowlisted host should pass validation, got: {err}"


@pytest.mark.asyncio
async def test_web_fetch_allowlist_still_blocks_non_allowlisted():
    """WebFetchTool with allowed_hosts must still block non-allowlisted private hosts."""
    allowed = frozenset(["gitlab.gleezy.cn"])
    tool = WebFetchTool(allowed_hosts=allowed)

    def _resolve_evil(hostname, port, family=0, type_=0):
        return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("10.0.0.5", 0))]

    with patch("nanobot.security.network.socket.getaddrinfo", _resolve_evil):
        ok, err = tool._validate_url_safe("https://evil.internal/secret")
    assert not ok


@pytest.mark.asyncio
async def test_web_fetch_result_contains_untrusted_flag():
    """When fetch succeeds, result JSON must include untrusted=True and the banner."""
    tool = WebFetchTool()

    fake_html = "<html><head><title>Test</title></head><body><p>Hello world</p></body></html>"

    import httpx

    class FakeResponse:
        status_code = 200
        url = "https://example.com/page"
        text = fake_html
        headers = {"content-type": "text/html"}
        def raise_for_status(self): pass
        def json(self): return {}

    async def _fake_get(self, url, **kwargs):
        return FakeResponse()

    with patch("nanobot.security.network.socket.getaddrinfo", _fake_resolve_public), \
         patch("httpx.AsyncClient.get", _fake_get):
        result = await tool.execute(url="https://example.com/page")

    data = json.loads(result)
    assert data.get("untrusted") is True
    assert "[External content" in data.get("text", "")
