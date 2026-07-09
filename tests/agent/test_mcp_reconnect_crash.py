"""Reproduction test for HKUDS/nanobot#4302.

This test starts a real FastMCP streamable-http server in a child process,
lets its idle timeout kill the session, and then exercises nanobot's MCP
reconnect path.  The bug being reproduced is a gateway crash caused by
improper cleanup of the old ``streamable_http_client`` async generator during
reconnect / shutdown.

Run:

    pytest tests/agent/test_mcp_reconnect_crash.py -v
"""

import asyncio
import multiprocessing
import socket
import time
from contextlib import suppress
from unittest.mock import MagicMock

import httpx
import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.agent.tools import mcp as mcp_module
from nanobot.agent.tools.mcp import MCPToolWrapper
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import MCPServerConfig
from nanobot.security import network as security_network

_IDLE_TIMEOUT_SECONDS = 5
_TOOL_TIMEOUT_SECONDS = 10


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _run_mcp_server(port: int, ready_event: multiprocessing.Event) -> None:
    """FastMCP server target for ``multiprocessing.Process``.

    The server exposes a single ``greet`` tool and terminates idle sessions
    after ``_IDLE_TIMEOUT_SECONDS``.
    """
    from mcp.server.fastmcp import FastMCP
    from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

    mcp = FastMCP("IdleTimeoutDemo", json_response=True, port=port)

    @mcp.tool()
    def greet(name: str = "World") -> str:  # noqa: N802
        """Greet someone."""
        return f"Hello, {name}!"

    mcp._session_manager = StreamableHTTPSessionManager(
        app=mcp._mcp_server,
        json_response=mcp.settings.json_response,
        stateless=mcp.settings.stateless_http,
        security_settings=mcp.settings.transport_security,
        session_idle_timeout=_IDLE_TIMEOUT_SECONDS,
    )

    ready_event.set()
    mcp.run(transport="streamable-http")


async def _wait_for_server(url: str, timeout: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                response = await client.get(
                    url,
                    headers={"Accept": "text/event-stream"},
                )
                if response.status_code < 500:
                    return True
        except Exception:
            await asyncio.sleep(0.1)
    return False


@pytest.fixture(scope="module")
def mcp_server_url():
    """Start the idle-timeout MCP server and yield its URL."""
    ctx = multiprocessing.get_context("spawn")
    port = _free_port()
    ready_event = ctx.Event()
    process = ctx.Process(
        target=_run_mcp_server,
        args=(port, ready_event),
        daemon=True,
    )
    process.start()
    ready_event.wait(timeout=10.0)

    url = f"http://127.0.0.1:{port}/mcp"
    if not asyncio.run(_wait_for_server(url, timeout=10.0)):
        process.terminate()
        process.join(timeout=5.0)
        pytest.skip(f"MCP repro server failed to start on {url}")

    yield url

    process.terminate()
    process.join(timeout=5.0)
    if process.is_alive():
        process.kill()
        process.join(timeout=2.0)


def _make_loop(tmp_path, *, mcp_servers: dict) -> AgentLoop:
    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    provider.generation.max_tokens = 4096
    return AgentLoop(
        bus=bus,
        provider=provider,
        workspace=tmp_path,
        model="test-model",
        mcp_servers=mcp_servers,
    )


@pytest.fixture(autouse=True)
def allow_loopback_mcp_urls(monkeypatch: pytest.MonkeyPatch):
    """The repro server runs on 127.0.0.1; allow nanobot to talk to it."""
    class TestPinnedDNSAsyncTransport(security_network.PinnedDNSAsyncTransport):
        _resolver_lock = asyncio.Lock()

    monkeypatch.setattr(mcp_module, "PinnedDNSAsyncTransport", TestPinnedDNSAsyncTransport)
    monkeypatch.setattr(
        mcp_module,
        "validate_url_target",
        lambda url, *, allow_loopback=False: (True, ""),
    )
    monkeypatch.setattr(
        mcp_module,
        "resolve_url_target",
        lambda url, *, allow_loopback=False: (True, "", ("127.0.0.1",)),
    )
    monkeypatch.setattr(
        security_network,
        "resolve_url_target",
        lambda url, *, allow_loopback=False: (True, "", ("127.0.0.1",)),
    )
    monkeypatch.setattr(
        mcp_module,
        "env_proxy_applies_to_url",
        lambda url: False,
    )
    monkeypatch.setattr(
        mcp_module,
        "httpx_env_proxy_mounts",
        lambda: {},
    )


@pytest.mark.asyncio
async def test_mcp_reconnect_after_session_timeout(tmp_path, mcp_server_url):
    """Reconnect to a real MCP server after its idle timeout kills the session."""
    cfg = MCPServerConfig(
        type="streamableHttp",
        url=mcp_server_url,
        tool_timeout=_TOOL_TIMEOUT_SECONDS,
        enabled_tools=["*"],
    )
    loop = _make_loop(tmp_path, mcp_servers={"repro": cfg})

    await loop._connect_mcp()
    assert "repro" in loop._mcp_stacks

    tool = loop.tools.get("mcp_repro_greet")
    assert isinstance(tool, MCPToolWrapper)

    output = await tool.execute(name="first")
    assert "Hello, first" in output

    # Wait for the server-side idle timeout to terminate the session.
    await asyncio.sleep(_IDLE_TIMEOUT_SECONDS + 1)

    output = await tool.execute(name="second")
    assert "Hello, second" in output

    await loop.close_mcp()


@pytest.mark.asyncio
async def test_mcp_reconnect_during_shutdown_does_not_crash(tmp_path, mcp_server_url):
    """Simulate the production crash: shutdown while reconnect is in flight."""
    cfg = MCPServerConfig(
        type="streamableHttp",
        url=mcp_server_url,
        tool_timeout=_TOOL_TIMEOUT_SECONDS,
        enabled_tools=["*"],
    )
    loop = _make_loop(tmp_path, mcp_servers={"repro": cfg})

    await loop._connect_mcp()
    tool = loop.tools.get("mcp_repro_greet")
    assert isinstance(tool, MCPToolWrapper)

    await tool.execute(name="first")
    await asyncio.sleep(_IDLE_TIMEOUT_SECONDS + 1)

    call_task = asyncio.create_task(tool.execute(name="second"))
    loop.stop()

    unhandled: list[BaseException] = []

    def capture_unhandled(_loop, context):
        exc = context.get("exception")
        if exc is not None:
            unhandled.append(exc)

    asyncio.get_running_loop().set_exception_handler(capture_unhandled)

    try:
        await asyncio.wait_for(asyncio.shield(call_task), timeout=15)
    except asyncio.CancelledError:
        unhandled.append(asyncio.CancelledError("main task cancelled by leaked MCP cancel scope"))
    except Exception as exc:
        unhandled.append(exc)

    with suppress(Exception):
        await loop.close_mcp()

    assert not unhandled, f"Unhandled exception leaked during reconnect/shutdown: {unhandled[0]}"
