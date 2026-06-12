"""Tests for MCP connection lifecycle in AgentLoop."""

from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack, asynccontextmanager
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
from mcp import types as mcp_types
from mcp.shared.exceptions import McpError
from mcp.types import ErrorData

from nanobot.agent.loop import AgentLoop
from nanobot.agent.tools import mcp as mcp_runtime
from nanobot.agent.tools.base import Tool
from nanobot.agent.tools.mcp import MCPResourceWrapper, MCPToolWrapper
from nanobot.bus.queue import MessageBus
from nanobot.config.loader import load_config, save_config
from nanobot.config.schema import MCPServerConfig


class _FakeMcpTool(Tool):
    def __init__(self, name: str) -> None:
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return "fake MCP tool"

    @property
    def parameters(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    async def execute(self, **_kwargs: Any) -> str:
        return "ok"


def _make_loop(tmp_path, *, mcp_servers: dict | None = None) -> AgentLoop:
    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    provider.generation.max_tokens = 4096
    return AgentLoop(
        bus=bus,
        provider=provider,
        workspace=tmp_path,
        model="test-model",
        mcp_servers=mcp_servers or {"test": object()},
    )


@pytest.mark.asyncio
async def test_connect_mcp_retries_when_no_servers_connect(tmp_path, monkeypatch: pytest.MonkeyPatch):
    loop = _make_loop(tmp_path)
    attempts = 0

    async def _fake_connect(_servers, _registry):
        nonlocal attempts
        attempts += 1
        return {}

    monkeypatch.setattr("nanobot.agent.tools.mcp.connect_mcp_servers", _fake_connect)

    await loop._connect_mcp()
    await loop._connect_mcp()

    assert attempts == 2
    assert loop._mcp_connected is False
    assert loop._mcp_stacks == {}


@pytest.mark.asyncio
async def test_reload_mcp_servers_adds_and_removes_tools_without_restart(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
):
    config_path = tmp_path / "config.json"
    monkeypatch.setattr("nanobot.config.loader._current_config_path", config_path)
    config = load_config()
    config.tools.mcp_servers["browserbase"] = MCPServerConfig(
        type="stdio",
        command="browserbase-mcp",
    )
    save_config(config)

    closed: list[str] = []

    async def _mark_closed(name: str) -> None:
        closed.append(name)

    async def _fake_connect(servers, registry):
        stacks = {}
        for name in servers:
            registry.register(_FakeMcpTool(f"mcp_{name}_navigate"))
            stack = AsyncExitStack()
            await stack.__aenter__()
            stack.push_async_callback(_mark_closed, name)
            stacks[name] = stack
        return stacks

    monkeypatch.setattr("nanobot.agent.tools.mcp.connect_mcp_servers", _fake_connect)
    loop = _make_loop(tmp_path, mcp_servers={})

    added = await mcp_runtime.reload_servers(loop, loop.tools)

    assert added["ok"] is True
    assert added["added"] == ["browserbase"]
    assert loop.tools.has("mcp_browserbase_navigate")
    assert "browserbase" in loop._mcp_stacks

    config = load_config()
    del config.tools.mcp_servers["browserbase"]
    save_config(config)

    removed = await mcp_runtime.reload_servers(loop, loop.tools)

    assert removed["ok"] is True
    assert removed["removed"] == ["browserbase"]
    assert not loop.tools.has("mcp_browserbase_navigate")
    assert "browserbase" not in loop._mcp_stacks
    assert closed == ["browserbase"]


@pytest.mark.asyncio
async def test_request_mcp_reload_reaches_runtime_control_without_restart(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
):
    config_path = tmp_path / "config.json"
    monkeypatch.setattr("nanobot.config.loader._current_config_path", config_path)
    config = load_config()
    config.tools.mcp_servers["browserbase"] = MCPServerConfig(
        type="stdio",
        command="browserbase-mcp",
    )
    save_config(config)

    closed: list[str] = []

    async def _mark_closed(name: str) -> None:
        closed.append(name)

    async def _fake_connect(servers, registry):
        stacks = {}
        for name in servers:
            registry.register(_FakeMcpTool(f"mcp_{name}_navigate"))
            stack = AsyncExitStack()
            await stack.__aenter__()
            stack.push_async_callback(_mark_closed, name)
            stacks[name] = stack
        return stacks

    monkeypatch.setattr("nanobot.agent.tools.mcp.connect_mcp_servers", _fake_connect)
    loop = _make_loop(tmp_path, mcp_servers={})

    async def _handle_one_runtime_control() -> None:
        msg = await loop.bus.consume_inbound()
        handled = await mcp_runtime.handle_runtime_control(loop, msg, loop.tools)
        assert handled is True

    consumer = asyncio.create_task(_handle_one_runtime_control())
    result = await mcp_runtime.request_mcp_reload(loop.bus, timeout=2.0)
    await consumer

    assert result["ok"] is True
    assert result["added"] == ["browserbase"]
    assert result["requires_restart"] is False
    assert loop.tools.has("mcp_browserbase_navigate")

    config = load_config()
    del config.tools.mcp_servers["browserbase"]
    save_config(config)

    consumer = asyncio.create_task(_handle_one_runtime_control())
    result = await mcp_runtime.request_mcp_reload(loop.bus, timeout=2.0)
    await consumer

    assert result["ok"] is True
    assert result["removed"] == ["browserbase"]
    assert result["requires_restart"] is False
    assert not loop.tools.has("mcp_browserbase_navigate")
    assert closed == ["browserbase"]


@pytest.mark.asyncio
async def test_reload_mcp_servers_retries_configured_server_without_live_stack(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
):
    config_path = tmp_path / "config.json"
    monkeypatch.setattr("nanobot.config.loader._current_config_path", config_path)
    config = load_config()
    config.tools.mcp_servers["browserbase"] = MCPServerConfig(
        type="stdio",
        command="browserbase-mcp",
    )
    save_config(config)

    async def _fake_connect(servers, registry):
        stacks = {}
        for name in servers:
            registry.register(_FakeMcpTool(f"mcp_{name}_navigate"))
            stack = AsyncExitStack()
            await stack.__aenter__()
            stacks[name] = stack
        return stacks

    monkeypatch.setattr("nanobot.agent.tools.mcp.connect_mcp_servers", _fake_connect)
    loop = _make_loop(tmp_path, mcp_servers={"browserbase": config.tools.mcp_servers["browserbase"]})

    result = await mcp_runtime.reload_servers(loop, loop.tools)

    assert result["ok"] is True
    assert result["added"] == []
    assert result["changed"] == []
    assert result["retried"] == ["browserbase"]
    assert loop.tools.has("mcp_browserbase_navigate")
    await loop.close_mcp()


@pytest.mark.asyncio
async def test_mcp_tool_reconnects_after_session_terminated(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
):
    loop = _make_loop(tmp_path, mcp_servers={"remote": object()})
    closed: list[str] = []
    sessions: list[Any] = []
    connect_count = 0

    async def _mark_closed(name: str) -> None:
        closed.append(name)

    class _FakeSession:
        def __init__(self, index: int) -> None:
            self.index = index
            self.call_count = 0

        async def call_tool(self, _name: str, arguments: dict[str, Any]) -> Any:
            self.call_count += 1
            assert arguments == {"symbol": "AAPL"}
            if self.index == 1:
                raise McpError(ErrorData(code=-32000, message="Session terminated"))
            return SimpleNamespace(
                content=[mcp_types.TextContent(type="text", text="recovered")]
            )

    async def _fake_connect(servers, registry):
        nonlocal connect_count
        stacks = {}
        for name in servers:
            connect_count += 1
            session = _FakeSession(connect_count)
            sessions.append(session)
            tool_def = SimpleNamespace(
                name="quote",
                description="quote tool",
                inputSchema={"type": "object", "properties": {}},
            )
            registry.register(MCPToolWrapper(session, name, tool_def, tool_timeout=5))
            stack = AsyncExitStack()
            await stack.__aenter__()
            stack.push_async_callback(_mark_closed, name)
            stacks[name] = stack
        return stacks

    monkeypatch.setattr("nanobot.agent.tools.mcp.connect_mcp_servers", _fake_connect)

    await loop._connect_mcp()
    old_tool = loop.tools.get("mcp_remote_quote")
    assert isinstance(old_tool, MCPToolWrapper)

    output = await old_tool.execute(symbol="AAPL")

    assert output == "recovered"
    assert connect_count == 2
    assert closed == ["remote"]
    assert sessions[0].call_count == 1
    assert sessions[1].call_count == 1
    assert "remote" in loop._mcp_stacks
    assert loop.tools.get("mcp_remote_quote") is not old_tool


@pytest.mark.asyncio
async def test_mcp_reconnect_handler_uses_sanitized_server_prefix(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
):
    loop = _make_loop(tmp_path, mcp_servers={"remote_": object()})
    connect_count = 0

    class _FakeSession:
        def __init__(self, index: int) -> None:
            self.index = index

        async def call_tool(self, _name: str, arguments: dict[str, Any]) -> Any:
            assert arguments == {}
            if self.index == 1:
                raise McpError(ErrorData(code=-32000, message="Session terminated"))
            return SimpleNamespace(
                content=[mcp_types.TextContent(type="text", text="recovered")]
            )

    async def _fake_connect(servers, registry):
        nonlocal connect_count
        stacks = {}
        for name in servers:
            connect_count += 1
            tool_def = SimpleNamespace(
                name="quote",
                description="quote tool",
                inputSchema={"type": "object", "properties": {}},
            )
            registry.register(MCPToolWrapper(_FakeSession(connect_count), name, tool_def))
            stack = AsyncExitStack()
            await stack.__aenter__()
            stacks[name] = stack
        return stacks

    monkeypatch.setattr("nanobot.agent.tools.mcp.connect_mcp_servers", _fake_connect)

    await loop._connect_mcp()
    old_tool = loop.tools.get("mcp_remote_quote")
    assert isinstance(old_tool, MCPToolWrapper)

    output = await old_tool.execute()

    assert output == "recovered"
    assert connect_count == 2
    assert loop.tools.get("mcp_remote_quote") is not old_tool


@pytest.mark.asyncio
async def test_concurrent_mcp_reconnect_reuses_fresh_session(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
):
    loop = _make_loop(tmp_path, mcp_servers={"remote": object()})
    closed: list[str] = []
    connect_count = 0

    async def _mark_closed(name: str) -> None:
        closed.append(name)

    class _DeadSession:
        async def read_resource(self, _uri: str) -> Any:
            raise McpError(ErrorData(code=-32000, message="Session terminated"))

    class _LiveSession:
        async def read_resource(self, uri: str) -> Any:
            await asyncio.sleep(0)
            return SimpleNamespace(
                contents=[
                    mcp_types.TextResourceContents(
                        uri=uri,
                        text=f"fresh:{uri.rsplit('/', maxsplit=1)[-1]}",
                    )
                ]
            )

    async def _fake_connect(servers, registry):
        nonlocal connect_count
        stacks = {}
        for name in servers:
            connect_count += 1
            session = _DeadSession() if connect_count == 1 else _LiveSession()
            for resource_name in ("alpha", "beta"):
                resource_def = SimpleNamespace(
                    name=resource_name,
                    uri=f"file:///{resource_name}",
                    description=f"{resource_name} resource",
                )
                registry.register(MCPResourceWrapper(session, name, resource_def))
            stack = AsyncExitStack()
            await stack.__aenter__()
            stack.push_async_callback(_mark_closed, name)
            stacks[name] = stack
        return stacks

    monkeypatch.setattr("nanobot.agent.tools.mcp.connect_mcp_servers", _fake_connect)

    await loop._connect_mcp()
    old_alpha = loop.tools.get("mcp_remote_resource_alpha")
    old_beta = loop.tools.get("mcp_remote_resource_beta")
    assert isinstance(old_alpha, MCPResourceWrapper)
    assert isinstance(old_beta, MCPResourceWrapper)

    outputs = await asyncio.gather(old_alpha.execute(), old_beta.execute())

    assert outputs == ["fresh:alpha", "fresh:beta"]
    assert connect_count == 2
    assert closed == ["remote"]


@pytest.mark.asyncio
async def test_close_server_cleans_up_tracked_generators_on_error():
    """When stack.aclose() raises RuntimeError (anyio cancel scope exit from a
    different task), _close_server must attempt gen.aclose() on the tracked
    raw async generators.  If gen.aclose() also raises (same cancel-scope
    issue), the generator must be kept alive in _unclosed_mcp_generators to
    prevent GC finalization from crashing the process.

    Uses a real @asynccontextmanager to match the object shape returned by
    MCP SDK's streamable_http_client().  The ``.gen`` attribute on the
    context manager is the actual async generator that needs cleanup.

    Regression test for https://github.com/HKUDS/nanobot/issues/4302
    """

    closed_via_gen: list[str] = []

    @asynccontextmanager
    async def _fake_streamable_http_client():
        """Simulates streamable_http_client() which returns an
        _AsyncGeneratorContextManager with a .gen attribute."""
        try:
            yield ("read", "write")
        finally:
            closed_via_gen.append("streamable_http")

    cm = _fake_streamable_http_client()
    # Enter the context manager so it's in a half-open state, just like
    # connect_mcp_servers does after enter_async_context().
    await cm.__aenter__()

    # Verify the SDK object shape: _AsyncGeneratorContextManager has .gen
    raw_gen = cm.gen
    assert raw_gen is not None

    class _BrokenStack(AsyncExitStack):
        """Stack whose aclose() raises RuntimeError, simulating the anyio
        cancel scope exit across tasks."""

        async def aclose(self):
            raise RuntimeError(
                "Attempted to exit cancel scope in a different task "
                "than it was entered in"
            )

    stack = _BrokenStack()
    await stack.__aenter__()
    # Simulate what connect_mcp_servers does: track the raw generator.
    stack._tracked_async_generators = [raw_gen]

    state = SimpleNamespace(_mcp_stacks={"test": stack})

    # Clear any prior unclosed references.
    mcp_runtime._unclosed_mcp_generators.clear()

    # Should not raise -- the RuntimeError is caught internally.
    await mcp_runtime._close_server(state, "test")

    # Server removed from state.
    assert "test" not in state._mcp_stacks

    # gen.aclose() succeeded and the finally block ran.
    assert closed_via_gen == ["streamable_http"]
    # No unclosed generators left behind (aclose succeeded).
    assert raw_gen not in mcp_runtime._unclosed_mcp_generators


@pytest.mark.asyncio
async def test_close_server_keeps_ref_when_gen_aclose_also_fails():
    """When stack.aclose() AND gen.aclose() both raise (anyio cancel scope),
    the generator must be kept alive in _unclosed_mcp_generators to prevent
    GC finalization from crashing the process.

    This simulates the production scenario where the generator's finally block
    also uses anyio task groups and hits the same cross-task error.
    """

    class _CancelScopeBrokenGenerator:
        """Simulates a generator whose aclose() always raises the cancel scope
        RuntimeError, matching the MCP SDK streamable_http_client behavior."""

        def __init__(self):
            self.closed = False

        async def aclose(self):
            raise RuntimeError(
                "Attempted to exit cancel scope in a different task "
                "than it was entered in"
            )

        def __aiter__(self):
            return self

        async def __anext__(self):
            raise StopAsyncIteration

    gen = _CancelScopeBrokenGenerator()

    class _BrokenStack(AsyncExitStack):
        async def aclose(self):
            raise RuntimeError(
                "Attempted to exit cancel scope in a different task "
                "than it was entered in"
            )

    stack = _BrokenStack()
    await stack.__aenter__()
    stack._tracked_async_generators = [gen]

    state = SimpleNamespace(_mcp_stacks={"test": stack})

    mcp_runtime._unclosed_mcp_generators.clear()

    # Should not raise.
    await mcp_runtime._close_server(state, "test")

    assert "test" not in state._mcp_stacks

    # gen.aclose() failed, so the generator must be kept alive.
    assert gen in mcp_runtime._unclosed_mcp_generators
