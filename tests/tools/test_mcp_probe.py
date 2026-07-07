"""Tests for MCP HTTP probe guard (prevents event-loop crash on unreachable servers)."""
from __future__ import annotations

import asyncio
import socket
from unittest.mock import MagicMock, patch

import pytest

from nanobot.agent.tools.mcp import _probe_http_url, connect_mcp_servers
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.security.network import configure_ssrf_whitelist

_PROXY_ENV_VARS = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy")


@pytest.fixture(autouse=True)
def _clear_proxy_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (*_PROXY_ENV_VARS, "NO_PROXY", "no_proxy"):
        monkeypatch.delenv(name, raising=False)


# ---------------------------------------------------------------------------
# _probe_http_url unit tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_probe_returns_true_for_open_port(tmp_path):
    """Start a trivial TCP server, probe should return True."""
    async def _close_connection(_reader, writer):
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(_close_connection, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    configure_ssrf_whitelist(["127.0.0.1/32"])
    try:
        assert await _probe_http_url(f"http://127.0.0.1:{port}/mcp") is True
    finally:
        configure_ssrf_whitelist([])
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


@pytest.mark.asyncio
async def test_probe_rejects_public_name_resolving_to_loopback():
    def _resolver(hostname, port, family=0, type_=0):
        return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("127.0.0.1", 0))]

    with patch("nanobot.security.network.socket.getaddrinfo", _resolver):
        assert await _probe_http_url("http://example.com:8765/mcp") is False


@pytest.mark.asyncio
async def test_probe_skips_direct_tcp_when_global_proxy_env_is_set(monkeypatch):
    def _resolver(hostname, port, family=0, type_=0):
        return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("93.184.216.34", 0))]

    async def _open_connection(*args, **kwargs):
        raise AssertionError("global proxy env should skip direct TCP probe")

    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.example:8080")
    monkeypatch.setenv("NO_PROXY", "localhost,127.0.0.1,::1")
    monkeypatch.setattr("nanobot.agent.tools.mcp.asyncio.open_connection", _open_connection)

    with patch("nanobot.security.network.socket.getaddrinfo", _resolver):
        assert await _probe_http_url("https://mcp.example.com/mcp") is True


@pytest.mark.asyncio
async def test_probe_tries_next_validated_ip_when_first_is_unreachable(monkeypatch):
    attempts: list[tuple[str, int]] = []

    class FakeWriter:
        def close(self):
            return None

        async def wait_closed(self):
            return None

    def _resolver(hostname, port, family=0, type_=0):
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("93.184.216.34", 0)),
            (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("93.184.216.35", 0)),
        ]

    async def _open_connection(host: str, port: int):
        attempts.append((host, port))
        if host == "93.184.216.34":
            raise OSError("first address unreachable")
        return object(), FakeWriter()

    monkeypatch.setattr("nanobot.security.network.socket.getaddrinfo", _resolver)
    monkeypatch.setattr("nanobot.agent.tools.mcp.asyncio.open_connection", _open_connection)

    assert await _probe_http_url("http://mcp.example:8765/mcp") is True
    assert attempts == [
        ("93.184.216.34", 8765),
        ("93.184.216.35", 8765),
    ]


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
    async def _unreachable(_url: str) -> bool:
        return False

    registry = ToolRegistry()
    servers = {"dead": _make_http_cfg("http://93.184.216.34:19999/mcp")}
    with patch("nanobot.agent.tools.mcp._probe_http_url", _unreachable):
        stacks = await connect_mcp_servers(servers, registry)
    assert stacks == {}
    assert len(registry._tools) == 0


@pytest.mark.asyncio
async def test_connect_skips_unreachable_sse():
    """Unreachable SSE server should be skipped with a warning, no crash."""
    async def _unreachable(_url: str) -> bool:
        return False

    registry = ToolRegistry()
    servers = {"dead": _make_http_cfg("http://93.184.216.34:19999/sse", transport="sse")}
    with patch("nanobot.agent.tools.mcp._probe_http_url", _unreachable):
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
