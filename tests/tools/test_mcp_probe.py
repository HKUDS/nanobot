"""Tests for MCP HTTP probe guard (prevents event-loop crash on unreachable servers)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot.agent.tools.mcp import _probe_http_url, connect_mcp_servers
from nanobot.agent.tools.registry import ToolRegistry


# ---------------------------------------------------------------------------
# _probe_http_url unit tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_probe_returns_true_for_open_port(tmp_path):
    """Start a trivial TCP server, probe should return True."""
    server = await asyncio.start_server(
        lambda r, w: None, "127.0.0.1", 0,
    )
    port = server.sockets[0].getsockname()[1]
    try:
        assert await _probe_http_url(f"http://127.0.0.1:{port}/mcp") is True
    finally:
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_probe_returns_false_for_closed_port():
    """Port 19999 is almost certainly not listening."""
    assert await _probe_http_url("http://127.0.0.1:19999/mcp") is False


@pytest.mark.asyncio
async def test_probe_uses_default_port_for_http():
    """When no port in URL, should default to 80 (will fail -> False)."""
    assert await _probe_http_url("http://unreachable-host.test/mcp") is False


# ---------------------------------------------------------------------------
# connect_mcp_servers skips unreachable HTTP servers
# ---------------------------------------------------------------------------

def _make_http_cfg(url: str, transport: str = "streamableHttp"):
    cfg = MagicMock()
    cfg.type = transport
    cfg.url = url
    cfg.command = None
    cfg.args = []
    cfg.env = {}
    cfg.headers = None
    cfg.tool_timeout = 30
    cfg.enabled_tools = ["*"]
    return cfg


@pytest.mark.asyncio
async def test_connect_skips_unreachable_streamable_http():
    """Unreachable streamableHttp server should be skipped with a warning, no crash."""
    registry = ToolRegistry()
    servers = {"dead": _make_http_cfg("http://127.0.0.1:19999/mcp")}
    stacks = await connect_mcp_servers(servers, registry)
    assert stacks == {}
    assert len(registry._tools) == 0


@pytest.mark.asyncio
async def test_connect_skips_unreachable_sse():
    """Unreachable SSE server should be skipped with a warning, no crash."""
    registry = ToolRegistry()
    servers = {"dead": _make_http_cfg("http://127.0.0.1:19999/sse", transport="sse")}
    stacks = await connect_mcp_servers(servers, registry)
    assert stacks == {}
    assert len(registry._tools) == 0


@pytest.mark.asyncio
async def test_probe_not_called_for_stdio():
    """stdio transport should not be probed — it spawns a local process."""
    called = False
    original_probe = _probe_http_url

    async def _spy_probe(url, **kw):
        nonlocal called
        called = True
        return await original_probe(url, **kw)

    with patch("nanobot.agent.tools.mcp._probe_http_url", _spy_probe):
        cfg = MagicMock()
        cfg.type = "stdio"
        cfg.url = None
        cfg.command = "nonexistent-command-xyz"
        cfg.args = []
        cfg.env = None
        cfg.headers = None
        cfg.tool_timeout = 30
        cfg.enabled_tools = ["*"]
        registry = ToolRegistry()
        await connect_mcp_servers({"s": cfg}, registry)

    assert not called, "probe should not be called for stdio transport"


import asyncio
