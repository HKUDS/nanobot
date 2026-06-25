from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from mcp.types import TextContent

from nanobot.agent.tools import mcp as mcp_runtime
from nanobot.agent.tools.mcp import MCPProvider, MCPToolWrapper
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.config.schema import MCPServerConfig
from nanobot.webui.mcp_presets_api import _mcp_server_config


class _FakeConnection:
    """MCPConnection stand-in whose close records whether cleanup finished."""

    def __init__(self) -> None:
        self.closed = False
        self.close_calls = 0

    @property
    def icons(self) -> list:
        return []

    async def aclose(self) -> None:
        self.close_calls += 1
        # Cancellation points: a close cancelled from its own watchdog task
        # dies here and never sets closed.
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        self.closed = True


@pytest_asyncio.fixture(autouse=True)
async def _clean_idle_state():
    yield
    for task in list(mcp_runtime._mcp_watchdog_tasks.values()):
        task.cancel()
    if mcp_runtime._mcp_watchdog_tasks:
        await asyncio.gather(
            *mcp_runtime._mcp_watchdog_tasks.values(), return_exceptions=True
        )
    mcp_runtime._mcp_watchdog_tasks.clear()
    mcp_runtime._mcp_last_accessed.clear()


def _make_provider(
    monkeypatch: pytest.MonkeyPatch, *, idle_timeout: int
) -> tuple[MCPProvider, ToolRegistry, _FakeConnection]:
    monkeypatch.setattr(mcp_runtime, "_MCP_IDLE_POLL_SECONDS", 0.05)
    registry = ToolRegistry()
    cfg = MCPServerConfig(type="stdio", command="test-mcp", idle_timeout=idle_timeout)
    provider = MCPProvider({"srv": cfg}, registry)
    connection = _FakeConnection()
    provider._connections["srv"] = connection
    return provider, registry, connection


@pytest.mark.asyncio
async def test_idle_watchdog_closes_server_after_timeout(monkeypatch) -> None:
    provider, _registry, connection = _make_provider(monkeypatch, idle_timeout=1)
    mcp_runtime._mcp_last_accessed["srv"] = time.time() - 10

    provider._start_idle_watchdog("srv")

    await asyncio.sleep(1.5)

    assert connection.closed is True
    assert connection.close_calls == 1
    assert "srv" not in provider._connections
    assert "srv" not in mcp_runtime._mcp_watchdog_tasks
    assert "srv" not in mcp_runtime._mcp_last_accessed


@pytest.mark.asyncio
async def test_idle_watchdog_keeps_active_server_alive(monkeypatch) -> None:
    provider, _registry, connection = _make_provider(monkeypatch, idle_timeout=1)

    provider._start_idle_watchdog("srv")
    for _ in range(5):
        await asyncio.sleep(0.3)
        mcp_runtime._mcp_last_accessed["srv"] = time.time()

    assert connection.closed is False
    assert "srv" in provider._connections

    # Once activity stops, the same watchdog closes the server.
    await asyncio.sleep(1.5)
    assert connection.closed is True
    assert "srv" not in provider._connections


@pytest.mark.asyncio
async def test_watchdog_close_is_not_interrupted_by_self_cancel(monkeypatch) -> None:
    """Regression test for the review finding on #4506.

    The watchdog closes the server by calling _close_server, which cancels
    the server's watchdog task. Cancelling the task from inside itself used
    to raise CancelledError at the next await in the cleanup and leave the
    connection half-closed.
    """
    provider, _registry, connection = _make_provider(monkeypatch, idle_timeout=1)
    mcp_runtime._mcp_last_accessed["srv"] = time.time() - 10

    provider._start_idle_watchdog("srv")

    await asyncio.sleep(1.5)

    assert connection.closed is True
    assert connection.close_calls == 1


@pytest.mark.asyncio
async def test_idle_timeout_zero_disables_watchdog(monkeypatch) -> None:
    provider, _registry, _connection = _make_provider(monkeypatch, idle_timeout=0)

    provider._start_idle_watchdog("srv")

    assert mcp_runtime._mcp_watchdog_tasks == {}
    assert "srv" not in mcp_runtime._mcp_last_accessed


@pytest.mark.asyncio
async def test_tool_call_refreshes_last_accessed(monkeypatch) -> None:
    monkeypatch.setattr(mcp_runtime, "_MCP_IDLE_POLL_SECONDS", 0.05)
    session = SimpleNamespace(
        call_tool=AsyncMock(
            return_value=SimpleNamespace(
                content=[TextContent(type="text", text="ok")]
            )
        ),
    )
    tool_def = SimpleNamespace(
        name="demo",
        description="demo tool",
        inputSchema={"type": "object", "properties": {}},
    )
    wrapper = MCPToolWrapper(session, "srv", tool_def)
    mcp_runtime._mcp_last_accessed["srv"] = time.time() - 100

    result = await wrapper.execute()

    assert result == "ok"
    assert time.time() - mcp_runtime._mcp_last_accessed["srv"] < 1


def test_mcp_server_config_parses_idle_timeout() -> None:
    _name, cfg = _mcp_server_config(
        "srv",
        {"type": "stdio", "command": "test-mcp", "idleTimeout": 120},
    )
    assert cfg.idle_timeout == 120


def test_mcp_server_config_idle_timeout_defaults_to_zero() -> None:
    _name, cfg = _mcp_server_config("srv", {"type": "stdio", "command": "x"})
    assert cfg.idle_timeout == 0


def test_mcp_server_config_idle_timeout_clamps_invalid_value() -> None:
    _name, cfg = _mcp_server_config(
        "srv",
        {"type": "stdio", "command": "x", "idle_timeout": "not-a-number"},
    )
    assert cfg.idle_timeout == 0
