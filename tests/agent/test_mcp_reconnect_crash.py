"""Reproduction test for HKUDS/nanobot#4302.

This test starts a real MCP v2 streamable-http server in a child process and
exercises both the 2026-07-28 stateless path and nanobot's reconnect/shutdown
resource ownership.

Run:

    pytest tests/agent/test_mcp_reconnect_crash.py -v
"""

import asyncio
import multiprocessing
import socket
import time
from unittest.mock import MagicMock

import httpx
import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.agent.tools import mcp as mcp_module
from nanobot.agent.tools.mcp import MCPToolWrapper
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import MCPServerConfig
from nanobot.security import network as security_network

_IDLE_WAIT_SECONDS = 0.5
_TOOL_TIMEOUT_SECONDS = 10


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _run_mcp_server(port: int, ready_event: multiprocessing.Event) -> None:
    """MCP v2 server target for ``multiprocessing.Process``."""
    from mcp.server import MCPServer

    mcp = MCPServer("StatelessDemo")

    @mcp.tool()
    def greet(name: str = "World") -> str:  # noqa: N802
        """Greet someone."""
        return f"Hello, {name}!"

    ready_event.set()
    mcp.run(transport="streamable-http", host="127.0.0.1", port=port, json_response=True)


async def _wait_for_server(url: str, timeout: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            async with httpx.AsyncClient(timeout=2.0, trust_env=False) as client:
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
        "_httpx2_env_proxy_mounts",
        lambda: {},
    )


@pytest.mark.asyncio
async def test_mcp_v2_stateless_connection_survives_idle_time(tmp_path, mcp_server_url):
    """Use the modern protocol without a transport session across idle time."""
    cfg = MCPServerConfig(
        type="streamableHttp",
        url=mcp_server_url,
        tool_timeout=_TOOL_TIMEOUT_SECONDS,
        enabled_tools=["*"],
    )
    loop = _make_loop(tmp_path, mcp_servers={"repro": cfg})

    await asyncio.create_task(loop._connect_mcp())
    assert "repro" in loop._mcp_stacks

    tool = loop.tools.get("mcp_repro_greet")
    assert isinstance(tool, MCPToolWrapper)
    assert tool._session.protocol_version == "2026-07-28"

    output = await asyncio.create_task(tool.execute(name="first"))
    assert "Hello, first" in output

    await asyncio.sleep(_IDLE_WAIT_SECONDS)

    output = await asyncio.create_task(tool.execute(name="second"))
    assert "Hello, second" in output

    await asyncio.create_task(loop.close_mcp())


@pytest.mark.asyncio
async def test_mcp_reconnect_during_shutdown_does_not_crash(
    tmp_path,
    mcp_server_url,
    monkeypatch: pytest.MonkeyPatch,
):
    """Simulate the production crash: shutdown while reconnect is in flight."""
    cfg = MCPServerConfig(
        type="streamableHttp",
        url=mcp_server_url,
        tool_timeout=_TOOL_TIMEOUT_SECONDS,
        enabled_tools=["*"],
    )
    loop = _make_loop(tmp_path, mcp_servers={"repro": cfg})

    await asyncio.create_task(loop._connect_mcp())
    tool = loop.tools.get("mcp_repro_greet")
    assert isinstance(tool, MCPToolWrapper)

    await asyncio.create_task(tool.execute(name="first"))

    reconnect_started = asyncio.Event()
    finish_reconnect = asyncio.Event()
    real_connect = mcp_module.connect_mcp_servers

    async def gated_connect(*args, **kwargs):
        reconnect_started.set()
        await finish_reconnect.wait()
        return await real_connect(*args, **kwargs)

    monkeypatch.setattr(mcp_module, "connect_mcp_servers", gated_connect)
    assert tool._reconnect is not None
    call_task = asyncio.create_task(tool._reconnect("repro", tool.name, tool))
    await asyncio.wait_for(reconnect_started.wait(), timeout=5)
    close_task = asyncio.create_task(loop.close_mcp())
    await asyncio.sleep(0)
    finish_reconnect.set()

    unhandled: list[BaseException] = []

    def capture_unhandled(_loop, context):
        exc = context.get("exception")
        if exc is not None:
            unhandled.append(exc)

    asyncio.get_running_loop().set_exception_handler(capture_unhandled)

    try:
        await asyncio.wait_for(asyncio.gather(call_task, close_task), timeout=15)
    except asyncio.CancelledError:
        unhandled.append(asyncio.CancelledError("main task cancelled by leaked MCP cancel scope"))
    except Exception as exc:
        unhandled.append(exc)

    assert not unhandled, f"Unhandled exception leaked during reconnect/shutdown: {unhandled[0]}"
    assert loop._mcp_stacks == {}
