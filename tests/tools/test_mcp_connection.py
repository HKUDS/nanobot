"""Tests for MCP connection lifecycle and truststore SSL verification."""

from __future__ import annotations

import ssl
from unittest.mock import patch

import httpx
import truststore

from nanobot import _init_truststore
from nanobot.agent.tools.mcp import _pinned_transport_kwargs
from nanobot.security.network import PinnedDNSAsyncTransport


def test_truststore_injected_into_ssl():
    """Verify that Python's ssl module creates truststore SSLContext instances."""
    ctx = ssl.create_default_context()
    assert isinstance(ctx, truststore.SSLContext)


def test_init_truststore_idempotent_and_safe():
    """Verify that _init_truststore() returns True and is safe to call repeatedly."""
    assert _init_truststore() is True
    assert _init_truststore() is True


def test_init_truststore_fallback_on_exception():
    """Verify that _init_truststore() catches exceptions and returns False gracefully."""
    with patch("truststore.inject_into_ssl", side_effect=RuntimeError("Unsupported OS")):
        assert _init_truststore() is False


def test_mcp_pinned_transport_kwargs_direct():
    """Direct transport kwargs should produce transports backed by truststore SSLContext."""
    kwargs = _pinned_transport_kwargs(None)
    assert "transport" in kwargs
    transport = kwargs["transport"]
    assert isinstance(transport, PinnedDNSAsyncTransport)
    # The inner AsyncHTTPTransport should use truststore SSLContext
    assert isinstance(transport._inner._pool._ssl_context, truststore.SSLContext)


def test_mcp_pinned_transport_kwargs_proxy():
    """Proxy transport kwargs should create AsyncHTTPTransport with trust_env=False and truststore SSLContext."""
    proxy_url = "http://127.0.0.1:8080"
    kwargs = _pinned_transport_kwargs(proxy_url)
    assert kwargs.get("trust_env") is False
    transport = kwargs["transport"]
    assert isinstance(transport, httpx.AsyncHTTPTransport)
    # Proxy transport pool must use truststore SSLContext
    assert isinstance(transport._pool._ssl_context, truststore.SSLContext)
