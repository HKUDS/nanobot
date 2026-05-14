"""Tests for ssl_verify config flow in web tools."""

from __future__ import annotations

import socket
from unittest.mock import patch

import pytest

from nanobot.agent.tools.web import (
    WebFetchTool,
    WebSearchTool,
    WebToolsConfig,
)
from nanobot.config.schema import WebSearchConfig


def _fake_resolve_public(hostname, port, family=0, type_=0):
    return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("93.184.216.34", 0))]


# --- Config-level tests ---


def test_ssl_verify_default_is_true():
    config = WebToolsConfig()
    assert config.ssl_verify is True


def test_ssl_verify_config_accepts_false():
    config = WebToolsConfig(ssl_verify=False)
    assert config.ssl_verify is False


def test_ssl_verify_config_accepts_ca_path():
    config = WebToolsConfig(ssl_verify="/path/to/corporate-ca.pem")
    assert config.ssl_verify == "/path/to/corporate-ca.pem"


# --- Tool constructor propagation tests ---


def test_web_fetch_tool_receives_ssl_verify():
    tool = WebFetchTool(ssl_verify=False)
    assert tool.ssl_verify is False


def test_web_fetch_tool_defaults_ssl_verify_to_true():
    tool = WebFetchTool()
    assert tool.ssl_verify is True


def test_web_search_tool_receives_ssl_verify():
    tool = WebSearchTool(
        config=WebSearchConfig(),
        ssl_verify=False,
    )
    assert tool.ssl_verify is False


def test_web_search_tool_defaults_ssl_verify_to_true():
    tool = WebSearchTool(config=WebSearchConfig())
    assert tool.ssl_verify is True


# --- httpx.AsyncClient verifies receive the param ---


class FakeClient:
    """Fake httpx.AsyncClient that captures __init__ kwargs."""

    captured_kwargs: dict = {}

    def __init__(self, *args, **kwargs):
        self.captured_kwargs = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


@pytest.mark.asyncio
async def test_async_client_receives_verify_false_for_fetch(monkeypatch):
    """WebFetchTool with ssl_verify=False must pass verify=False to httpx.AsyncClient."""
    captured: list[dict] = []

    class TrackingClient:
        nonlocal captured  # type: ignore[misc]

        def __init__(self, *args, **kwargs):
            captured.append(dict(kwargs))

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        def stream(self, method, url, headers=None):
            class FakeStream:
                headers = {"content-type": "text/html"}
                url = "https://example.com/page"

                async def __aenter__(self):
                    return self

                async def __aexit__(self, *a):
                    return False

            return FakeStream()

        async def get(self, url, **kw):
            class FakeResp:
                status_code = 200
                url = "https://example.com/page"
                text = "<html><body><p>ok</p></body></html>"
                headers = {"content-type": "text/html"}

                def raise_for_status(self):
                    return None

                def json(self):
                    return {}

            return FakeResp()

    monkeypatch.setattr("nanobot.agent.tools.web.httpx.AsyncClient", TrackingClient)

    tool = WebFetchTool(ssl_verify=False)
    with patch("nanobot.security.network.socket.getaddrinfo", _fake_resolve_public):
        await tool.execute(url="https://example.com/page")

    # All 3 calls (image detection, Jina, readability) should pass verify=False
    for call_kwargs in captured:
        assert call_kwargs.get("verify") is False, f"verify was {call_kwargs.get('verify')}"


@pytest.mark.asyncio
async def test_async_client_receives_verify_true_default_for_fetch(monkeypatch):
    """WebFetchTool with default ssl_verify=True must pass verify=True."""
    captured: list[dict] = []

    class TrackingClient:
        def __init__(self, *args, **kwargs):
            captured.append(dict(kwargs))

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        def stream(self, method, url, headers=None):
            class FakeStream:
                headers = {"content-type": "text/html"}
                url = "https://example.com/page"

                async def __aenter__(self):
                    return self

                async def __aexit__(self, *a):
                    return False

            return FakeStream()

        async def get(self, url, **kw):
            class FakeResp:
                status_code = 200
                url = "https://example.com/page"
                text = "<html><body><p>ok</p></body></html>"
                headers = {"content-type": "text/html"}

                def raise_for_status(self):
                    return None

                def json(self):
                    return {}

            return FakeResp()

    monkeypatch.setattr("nanobot.agent.tools.web.httpx.AsyncClient", TrackingClient)

    tool = WebFetchTool()  # default ssl_verify=True
    with patch("nanobot.security.network.socket.getaddrinfo", _fake_resolve_public):
        await tool.execute(url="https://example.com/page")

    for call_kwargs in captured:
        assert call_kwargs.get("verify") is True, f"verify was {call_kwargs.get('verify')}"
