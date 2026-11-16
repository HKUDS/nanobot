from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack, asynccontextmanager
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import anyio
import pytest
from mcp import types as mcp_types
from mcp.shared.exceptions import McpError
from mcp.shared.message import SessionMessage
from mcp.types import ErrorData

from nanobot.agent.tools import mcp as mcp_runtime
from nanobot.agent.tools.base import Tool
from nanobot.agent.tools.mcp import (
    MCPProvider,
    MCPResourceWrapper,
    MCPServerConnection,
    MCPToolWrapper,
)
from nanobot.agent.tools.registry import ToolRegistry, is_tool_error_result
from nanobot.config.loader import load_config, save_config
from nanobot.config.network import NetworkConfig
from nanobot.config.schema import Config, MCPServerConfig


def _mcp_notification(method: str, params: dict[str, Any] | None = None) -> SessionMessage:
    return SessionMessage(
        message=mcp_types.JSONRPCMessage(
            mcp_types.JSONRPCNotification(
                jsonrpc="2.0",
                method=method,
                params=params,
            )
        )
    )


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


def _stdio_server(command: str = "test-mcp") -> MCPServerConfig:
    return MCPServerConfig(type="stdio", command=command)


def _make_provider(
    *,
    mcp_servers: dict[str, MCPServerConfig] | None = None,
) -> tuple[MCPProvider, ToolRegistry]:
    registry = ToolRegistry()
    provider = MCPProvider(
        mcp_servers if mcp_servers is not None else {"test": _stdio_server()},
        registry,
    )
    return provider, registry


@pytest.mark.asyncio
async def test_mcp_read_filter_drops_progress_notifications_without_progress_token():
    send, receive = anyio.create_memory_object_stream(4)
    malformed_progress = _mcp_notification(
        "notifications/progress",
        {"progress": 20, "total": 600, "message": "Polling"},
    )
    tool_change = _mcp_notification("notifications/tools/list_changed")
    valid_progress = _mcp_notification(
        "notifications/progress",
        {"progressToken": "req-1", "progress": 25, "total": 600, "message": "Polling"},
    )

    await send.send(malformed_progress)
    await send.send(tool_change)
    await send.send(valid_progress)
    await send.aclose()

    async with mcp_runtime._MCPReceiveStream(receive) as wrapped:
        forwarded = [message async for message in wrapped]

    assert forwarded == [tool_change, valid_progress]


@pytest.mark.asyncio
async def test_mcp_connection_closes_sdk_context_in_its_opening_task(monkeypatch):
    tasks = []

    @asynccontextmanager
    async def stdio(_params):
        tasks.append(asyncio.current_task())
        try:
            yield None, None
        finally:
            tasks.append(asyncio.current_task())

    @asynccontextmanager
    async def session(_read, _write):
        yield SimpleNamespace(initialize=AsyncMock(return_value=SimpleNamespace(
            capabilities=mcp_types.ServerCapabilities(),
        )))

    monkeypatch.setattr("mcp.client.stdio.stdio_client", stdio)
    monkeypatch.setattr("mcp.ClientSession", session)
    provider, _ = _make_provider(mcp_servers={"test": MCPServerConfig(command="fake", enabled_tools=[])})
    await provider.connect()
    assert provider.connected_server_names == {"test"}
    await provider.aclose()
    opened, closed = tasks
    assert opened is closed and opened is not asyncio.current_task()


@pytest.mark.asyncio
async def test_connect_mcp_retries_when_no_servers_connect(tmp_path, monkeypatch: pytest.MonkeyPatch):
    provider, _registry = _make_provider()
    attempts = 0

    async def _fake_connect(_name, _cfg, *, network, stdio_slots):
        nonlocal attempts
        attempts += 1
        return None

    monkeypatch.setattr("nanobot.agent.tools.mcp.connect_mcp_server", _fake_connect)

    await provider.connect()
    await provider.connect()

    assert attempts == 2
    assert provider.connected_server_names == set()
    assert provider.runtime_status() == {"test": "failed"}


@pytest.mark.asyncio
async def test_maintenance_recovers_failed_server_without_a_turn(monkeypatch: pytest.MonkeyPatch):
    provider, registry = _make_provider(mcp_servers={
        name: _stdio_server() for name in ("good", "recovering", "stalled")
    })
    retry_started = asyncio.Event()
    finish_retry = asyncio.Event()
    first_failure = asyncio.Event()
    initial = asyncio.Event()
    closed: list[str] = []
    attempts = 0

    async def _mark_closed(name: str) -> None:
        closed.append(name)

    async def connect(name, _cfg, *, network, stdio_slots):
        nonlocal attempts
        if name == "stalled":
            try:
                await asyncio.Event().wait()
            finally:
                closed.append(name)
        if name == "recovering":
            attempts += 1
            if attempts == 1:
                await first_failure.wait()
                return None
            retry_started.set()
            await finish_retry.wait()
        stack = AsyncExitStack()
        await stack.__aenter__()
        stack.push_async_callback(_mark_closed, name)
        return MCPServerConnection(stack.aclose, (_FakeMcpTool(f"mcp_{name}_ping"),))

    monkeypatch.setattr(mcp_runtime, "connect_mcp_server", connect)
    monkeypatch.setattr(mcp_runtime, "_RETRY_DELAY_SECONDS", 0)
    worker = asyncio.create_task(provider.maintain(initial))
    try:
        async with asyncio.timeout(2):
            while not registry.has("mcp_good_ping"):
                await asyncio.sleep(0)
            assert await registry.execute("mcp_good_ping", {}) == "ok"
            first_failure.set()
            await retry_started.wait()
            assert provider.runtime_status()["stalled"] == "connecting"
            assert not registry.has("mcp_recovering_ping")
            finish_retry.set()
            while not registry.has("mcp_recovering_ping"):
                await asyncio.sleep(0)
            assert await registry.execute("mcp_recovering_ping", {}) == "ok"
    finally:
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)
        await provider.aclose()
    assert sorted(closed) == ["good", "recovering", "stalled"]


@pytest.mark.asyncio
async def test_consecutive_connection_failures_back_off_without_new_turns(monkeypatch):
    provider, registry = _make_provider()
    initial = asyncio.Event()
    starts: list[float] = []
    loop = asyncio.get_running_loop()
    first_delay = 0.04

    async def connect(_name, _cfg, *, network, stdio_slots):
        starts.append(loop.time())
        if len(starts) < 3:
            return None
        stack = AsyncExitStack()
        await stack.__aenter__()
        return MCPServerConnection(stack.aclose, (_FakeMcpTool("mcp_test_ping"),))

    monkeypatch.setattr(mcp_runtime, "connect_mcp_server", connect)
    monkeypatch.setattr(mcp_runtime, "_RETRY_DELAY_SECONDS", first_delay)
    worker = asyncio.create_task(provider.maintain(initial))
    try:
        async with asyncio.timeout(5):
            await initial.wait()
            while not registry.has("mcp_test_ping"):
                await asyncio.sleep(0.01)
            assert await registry.execute("mcp_test_ping", {}) == "ok"
        assert len(starts) == 3
        assert starts[1] - starts[0] >= first_delay
        assert starts[2] - starts[1] >= 2 * first_delay
    finally:
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)
        await provider.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("first", ["a.b", "a_b"])
async def test_mcp_name_collision_cannot_redirect_a_published_tool(first, monkeypatch):
    configs = {name: _stdio_server() for name in ("a.b", "a_b")}
    registry = ToolRegistry()
    provider = MCPProvider(configs, registry, server_loader=lambda: (configs, NetworkConfig()))
    allow_second = asyncio.Event()
    shared_name = "mcp_a_b_ping"
    definition = mcp_types.Tool(name="ping", inputSchema={"type": "object"})
    session = SimpleNamespace(
        send_ping=AsyncMock(),
        call_tool=AsyncMock(return_value=mcp_types.CallToolResult(
            content=[mcp_types.TextContent(type="text", text="pong")],
        )),
    )

    async def connect(name, _config, *, network, stdio_slots):
        if name != first:
            await allow_second.wait()
        return MCPServerConnection(AsyncMock(), (
            MCPToolWrapper(session, name, definition),
            _FakeMcpTool(f"mcp_sibling_{name}"),
        ))

    monkeypatch.setattr(mcp_runtime, "connect_mcp_server", connect)
    work = asyncio.create_task(provider.connect())
    try:
        async with asyncio.timeout(2):
            while not registry.has(shared_name):
                await asyncio.sleep(0)
            assert await registry.execute(shared_name, {}) == "pong"
            allow_second.set()
            await work
        assert not registry.has(shared_name)
        assert is_tool_error_result(await registry.execute(shared_name, {}))
        assert set(registry.tool_names) == {
            "mcp_sibling_a.b", "mcp_sibling_a_b",
        }
        # The old name must not be rebound to a different server after a reload.
        del configs[first]
        assert (await provider.reload())["ok"]
        assert not registry.has(shared_name)
        assert session.call_tool.await_count == 1
    finally:
        work.cancel()
        await asyncio.gather(work, return_exceptions=True)
        await provider.aclose()


@pytest.mark.asyncio
async def test_connect_mcp_does_not_report_failure_before_oauth_authorization(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
):
    cfg = MCPServerConfig(
        type="streamableHttp",
        auth="oauth",
        url="https://mcp.example.com/mcp",
    )
    provider, _registry = _make_provider(mcp_servers={"oauth-app": cfg})
    connect = AsyncMock()
    monkeypatch.setattr("nanobot.agent.tools.mcp.connect_mcp_server", connect)
    monkeypatch.setattr(
        "nanobot.agent.tools.mcp_oauth.mcp_oauth_has_credentials",
        lambda _name, _url: False,
    )

    await provider.connect()

    connect.assert_not_awaited()
    assert provider.runtime_status() == {}


@pytest.mark.asyncio
async def test_mcp_provider_closes_connections_independently_from_agent_loop(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
):
    provider, registry = _make_provider(
        mcp_servers={"playwright": _stdio_server("playwright")}
    )
    close = AsyncMock()

    async def _fake_connect(name, _cfg, *, network, stdio_slots):
        return MCPServerConnection(close, (_FakeMcpTool(f"mcp_{name}_search"),))

    monkeypatch.setattr("nanobot.agent.tools.mcp.connect_mcp_server", _fake_connect)

    await provider.connect()
    assert registry.has("mcp_playwright_search")
    await provider.aclose()

    close.assert_awaited_once()
    assert provider.connected_server_names == set()
    assert registry.get("mcp_playwright_search") is None


@pytest.mark.asyncio
async def test_close_server_ignores_server_cancelled_error(tmp_path):
    provider, _registry = _make_provider()

    class _ServerCancelledStack:
        async def aclose(self) -> None:
            raise asyncio.CancelledError()

    provider._connections = {"test": MCPServerConnection(_ServerCancelledStack().aclose)}

    await provider._close_server("test")

    assert provider.connected_server_names == set()


@pytest.mark.asyncio
async def test_provider_close_continues_after_server_cancelled_error(tmp_path):
    provider, _registry = _make_provider()
    closed: list[str] = []

    class _ServerCancelledStack:
        async def aclose(self) -> None:
            raise asyncio.CancelledError()

    class _TrackedStack:
        async def aclose(self) -> None:
            closed.append("second")

    provider._connections = {
        "first": MCPServerConnection(_ServerCancelledStack().aclose),
        "second": MCPServerConnection(_TrackedStack().aclose),
    }

    await provider.aclose()

    assert closed == ["second"]
    assert provider.connected_server_names == set()


@pytest.mark.asyncio
async def test_provider_close_finishes_other_connections_before_propagating_cancellation(
    tmp_path,
):
    provider, _registry = _make_provider()
    started = asyncio.Event()
    closed: list[str] = []

    class _BlockingStack:
        async def aclose(self) -> None:
            started.set()
            await asyncio.Event().wait()

    class _TrackedStack:
        async def aclose(self) -> None:
            closed.append("second")

    provider._connections = {
        "first": MCPServerConnection(_BlockingStack().aclose),
        "second": MCPServerConnection(_TrackedStack().aclose),
    }
    task = asyncio.create_task(provider.aclose())
    await asyncio.wait_for(started.wait(), timeout=1)

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert closed == ["second"]
    assert provider.connected_server_names == set()


@pytest.mark.asyncio
@pytest.mark.parametrize("close_all", [False, True], ids=["single", "all"])
async def test_mcp_cleanup_re_raises_external_cancellation(tmp_path, close_all: bool):
    provider, _registry = _make_provider()
    started = asyncio.Event()

    class _BlockingStack:
        async def aclose(self) -> None:
            started.set()
            await asyncio.Event().wait()

    provider._connections = {"test": MCPServerConnection(_BlockingStack().aclose)}

    if close_all:
        task = asyncio.create_task(provider.aclose())
    else:
        task = asyncio.create_task(provider._close_server("test"))
    await asyncio.wait_for(started.wait(), timeout=1)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task


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

    async def _fake_connect(name, _cfg, *, network, stdio_slots):
        stack = AsyncExitStack()
        await stack.__aenter__()
        stack.push_async_callback(_mark_closed, name)
        return MCPServerConnection(stack.aclose, (_FakeMcpTool(f"mcp_{name}_navigate"),))

    monkeypatch.setattr("nanobot.agent.tools.mcp.connect_mcp_server", _fake_connect)
    provider, registry = _make_provider(mcp_servers={})

    added = await provider.reload()

    assert added["ok"] is True
    assert added["added"] == ["browserbase"]
    assert registry.has("mcp_browserbase_navigate")
    assert provider.connected_server_names == {"browserbase"}

    config = load_config()
    del config.tools.mcp_servers["browserbase"]
    save_config(config)

    removed = await provider.reload()

    assert removed["ok"] is True
    assert removed["removed"] == ["browserbase"]
    assert not registry.has("mcp_browserbase_navigate")
    assert provider.connected_server_names == set()
    assert closed == ["browserbase"]


@pytest.mark.asyncio
async def test_reload_is_a_direct_provider_operation_without_an_agent_loop(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
):
    browserbase = MCPServerConfig(
        type="stdio",
        command="browserbase-mcp",
    )
    configured: dict[str, MCPServerConfig] = {"browserbase": browserbase}

    closed: list[str] = []

    async def _mark_closed(name: str) -> None:
        closed.append(name)

    async def _fake_connect(name, _cfg, *, network, stdio_slots):
        stack = AsyncExitStack()
        await stack.__aenter__()
        stack.push_async_callback(_mark_closed, name)
        return MCPServerConnection(stack.aclose, (_FakeMcpTool(f"mcp_{name}_navigate"),))

    monkeypatch.setattr("nanobot.agent.tools.mcp.connect_mcp_server", _fake_connect)
    registry = ToolRegistry()
    provider = MCPProvider({}, registry, server_loader=lambda: (configured, NetworkConfig()))

    result = await provider.reload()

    assert result["ok"] is True
    assert result["added"] == ["browserbase"]
    assert result["requires_restart"] is False
    assert registry.has("mcp_browserbase_navigate")

    configured = {}

    result = await provider.reload()

    assert result["ok"] is True
    assert result["removed"] == ["browserbase"]
    assert result["requires_restart"] is False
    assert not registry.has("mcp_browserbase_navigate")
    assert closed == ["browserbase"]


@pytest.mark.asyncio
async def test_reload_does_not_report_closed_connection_as_connected(monkeypatch: pytest.MonkeyPatch):
    close_started, finish_close = asyncio.Event(), asyncio.Event()
    connect_started, finish_connect = asyncio.Event(), asyncio.Event()
    registry = ToolRegistry()
    name = "test"
    old, new = _stdio_server("old-mcp"), _stdio_server("new-mcp")
    tool_name = "mcp_test_ping"

    async def close_old() -> None:
        close_started.set()
        await finish_close.wait()

    async def connect(_name, cfg, *, network, stdio_slots):
        if cfg.command == old.command:
            stack = AsyncMock(aclose=close_old)
        else:
            connect_started.set()
            await finish_connect.wait()
            stack = AsyncMock()
        return MCPServerConnection(stack.aclose, (_FakeMcpTool(tool_name),))

    monkeypatch.setattr(mcp_runtime, "connect_mcp_server", connect)
    provider = MCPProvider({name: old}, registry, server_loader=lambda: ({name: new}, NetworkConfig()))
    await provider.connect()
    assert provider.runtime_status() == {name: "connected"}
    reload_task = asyncio.create_task(provider.reload())
    try:
        async with asyncio.timeout(2):
            await close_started.wait()
            assert provider.runtime_status().get(name) != "connected"
            assert not registry.has(tool_name)

            finish_close.set()
            await connect_started.wait()
            assert provider.runtime_status() == {name: "connecting"}
            finish_connect.set()
            assert (await reload_task)["ok"]
        assert provider.runtime_status() == {name: "connected"}
        assert await registry.execute(tool_name, {}) == "ok"
    finally:
        if not reload_task.done():
            reload_task.cancel()
        await asyncio.gather(reload_task, return_exceptions=True)
        await provider.aclose()


@pytest.mark.asyncio
async def test_reload_wait_limit_keeps_slow_discovery_alive(
    monkeypatch: pytest.MonkeyPatch,
):
    server = _stdio_server("slow-mcp")
    started = asyncio.Event()
    ready = asyncio.Event()
    attempts = 0

    async def _fake_connect(_name, _cfg, *, network, stdio_slots):
        nonlocal attempts
        attempts += 1
        started.set()
        await ready.wait()
        stack = AsyncExitStack()
        await stack.__aenter__()
        return MCPServerConnection(stack.aclose)

    monkeypatch.setattr("nanobot.agent.tools.mcp.connect_mcp_server", _fake_connect)
    monkeypatch.setattr(mcp_runtime, "_RELOAD_WAIT_SECONDS", 0.02)
    provider = MCPProvider(
        {"test": server},
        ToolRegistry(),
        server_loader=lambda: ({"test": server}, NetworkConfig()),
    )

    try:
        async with asyncio.timeout(2):
            reload_task = asyncio.create_task(provider.reload())
            await started.wait()
            result = await reload_task
            assert not result["ok"] and not result["requires_restart"]
            assert result["failed"] == []
            assert result["connecting"] == ["test"]
            assert provider.runtime_status() == {"test": "connecting"}
            assert (await provider.reload())["connecting"] == ["test"]
            monkeypatch.setattr(mcp_runtime, "_STARTUP_SLOW_SECONDS", 0)
            assert provider.runtime_status() == {"test": "connecting_slow"}
            ready.set()
            await provider.connect()
            assert provider.runtime_status() == {"test": "connected"}
        assert attempts == 1
    finally:
        await provider.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("shutdown_during_cleanup", [False, True])
async def test_startup_timeout_closes_transport_and_leaves_no_tools(monkeypatch, shutdown_during_cleanup):
    opened = asyncio.Event()
    closing = asyncio.Event()
    release = asyncio.Event()
    closed = asyncio.Event()

    @asynccontextmanager
    async def stdio(_params):
        try:
            opened.set()
            yield None, None
        finally:
            closing.set()
            if shutdown_during_cleanup:
                await release.wait()
            closed.set()

    @asynccontextmanager
    async def session(_read, _write):
        async def initialize():
            await asyncio.Event().wait()

        yield SimpleNamespace(initialize=initialize)

    monkeypatch.setattr("mcp.client.stdio.stdio_client", stdio)
    monkeypatch.setattr("mcp.ClientSession", session)
    monkeypatch.setattr(mcp_runtime, "_STARTUP_TIMEOUT_SECONDS", 0.05)
    provider, registry = _make_provider()
    try:
        async with asyncio.timeout(2):
            if shutdown_during_cleanup:
                connect = asyncio.create_task(provider.connect())
                await closing.wait()
                shutdown = asyncio.create_task(provider.aclose())
                done, _ = await asyncio.wait((shutdown,), timeout=0.05)
                assert not done, "gateway shutdown must drain the transport owner"
                release.set()
                await shutdown
                await connect
            else:
                await provider.connect()
                assert provider.runtime_status() == {"test": "startup_timeout"}
        assert opened.is_set()
        assert closed.is_set()
        assert not registry.get_definitions()
    finally:
        release.set()
        await provider.aclose()


@pytest.mark.asyncio
async def test_reload_cancels_removed_discovery_and_publishes_new_configuration(monkeypatch):
    stale_started = asyncio.Event()
    stale_closed = AsyncMock()
    configs = {"test": _stdio_server("old-mcp")}
    registry = ToolRegistry()
    provider = MCPProvider(configs, registry, server_loader=lambda: (configs, NetworkConfig()))

    async def connect(name, config, *, network, stdio_slots):
        if config.command == "old-mcp":
            stale_started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                return MCPServerConnection(stale_closed, (_FakeMcpTool(f"mcp_{name}_old"),))
        return MCPServerConnection(AsyncMock(), (_FakeMcpTool(f"mcp_{name}_new"),))

    monkeypatch.setattr(mcp_runtime, "connect_mcp_server", connect)
    work = asyncio.create_task(provider.connect())
    try:
        async with asyncio.timeout(2):
            await stale_started.wait()
            configs["test"] = _stdio_server("new-mcp")
            assert (await provider.reload())["connected"] == ["test"]
            await work
            assert await registry.execute("mcp_test_new", {}) == "ok"
            assert is_tool_error_result(await registry.execute("mcp_test_old", {}))
            stale_closed.assert_awaited_once()
    finally:
        await provider.aclose()
        await work


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

    async def _fake_connect(name, _cfg, *, network, stdio_slots):
        stack = AsyncExitStack()
        await stack.__aenter__()
        return MCPServerConnection(stack.aclose, (_FakeMcpTool(f"mcp_{name}_navigate"),))

    monkeypatch.setattr("nanobot.agent.tools.mcp.connect_mcp_server", _fake_connect)
    provider, registry = _make_provider(
        mcp_servers={"browserbase": config.tools.mcp_servers["browserbase"]}
    )

    result = await provider.reload()

    assert result["ok"] is True
    assert result["added"] == []
    assert result["changed"] == []
    assert result["retried"] == ["browserbase"]
    assert registry.has("mcp_browserbase_navigate")
    await provider.aclose()


@pytest.mark.asyncio
async def test_reload_mcp_servers_skips_oauth_server_waiting_for_authorization(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
):
    config_path = tmp_path / "config.json"
    monkeypatch.setattr("nanobot.config.loader._current_config_path", config_path)
    config = load_config()
    notion = MCPServerConfig(
        type="streamableHttp",
        auth="oauth",
        url="https://mcp.notion.test/mcp",
    )
    linear = MCPServerConfig(
        type="streamableHttp",
        auth="oauth",
        url="https://mcp.linear.test/mcp",
    )
    config.tools.mcp_servers.update({"notion": notion, "linear": linear})
    save_config(config)

    attempted: list[str] = []

    async def _fake_connect(name, _cfg, *, network, stdio_slots):
        attempted.append(name)
        stack = AsyncExitStack()
        await stack.__aenter__()
        return MCPServerConnection(stack.aclose)

    monkeypatch.setattr("nanobot.agent.tools.mcp.connect_mcp_server", _fake_connect)
    monkeypatch.setattr(
        "nanobot.agent.tools.mcp_oauth.mcp_oauth_has_credentials",
        lambda name, _url: name == "linear",
    )
    provider, _registry = _make_provider(mcp_servers={"notion": notion})

    result = await provider.reload()

    assert attempted == ["linear"]
    assert result["ok"] is True
    assert result["failed"] == []
    assert result["retried"] == []
    assert result["connected"] == ["linear"]
    await provider.aclose()


@pytest.mark.asyncio
async def test_mcp_tool_reconnects_before_submission_after_session_terminated(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
):
    provider, registry = _make_provider(
        mcp_servers={"remote": _stdio_server("remote")}
    )
    closed: list[str] = []
    sessions: list[Any] = []
    connect_count = 0

    async def _mark_closed(name: str) -> None:
        closed.append(name)

    class _FakeSession:
        def __init__(self, index: int) -> None:
            self.index = index
            self.call_count = 0

        async def send_ping(self) -> None:
            if self.index == 1:
                raise McpError(ErrorData(code=-32000, message="Session terminated"))

        async def call_tool(self, _name: str, arguments: dict[str, Any]) -> Any:
            self.call_count += 1
            assert arguments == {"symbol": "AAPL"}
            return SimpleNamespace(
                content=[mcp_types.TextContent(type="text", text="recovered")]
            )

    async def _fake_connect(name, _cfg, *, network, stdio_slots):
        nonlocal connect_count
        connect_count += 1
        session = _FakeSession(connect_count)
        sessions.append(session)
        tool_def = SimpleNamespace(
            name="quote",
            description="quote tool",
            inputSchema={"type": "object", "properties": {}},
        )
        tool = MCPToolWrapper(session, name, tool_def, tool_timeout=5)
        stack = AsyncExitStack()
        await stack.__aenter__()
        stack.push_async_callback(_mark_closed, name)
        return MCPServerConnection(stack.aclose, (tool,))

    monkeypatch.setattr("nanobot.agent.tools.mcp.connect_mcp_server", _fake_connect)

    await provider.connect()
    old_tool = registry.get("mcp_remote_quote")
    assert isinstance(old_tool, MCPToolWrapper)

    output = await old_tool.execute(symbol="AAPL")

    assert output == "recovered"
    assert connect_count == 2
    assert closed == ["remote"]
    assert sessions[0].call_count == 0
    assert sessions[1].call_count == 1
    assert provider.connected_server_names == {"remote"}
    assert registry.get("mcp_remote_quote") is not old_tool


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_during", ["cleanup", "discovery"])
async def test_cancelled_tool_call_does_not_interrupt_shared_reconnect(cancel_during, monkeypatch):
    provider, registry = _make_provider(mcp_servers={"remote": _stdio_server()})
    close_started = asyncio.Event()
    finish_close = asyncio.Event()
    old_closed = asyncio.Event()
    discovery_started = asyncio.Event()
    finish_discovery = asyncio.Event()
    attempts = 0

    async def connect(name, _cfg, *, network, stdio_slots):
        nonlocal attempts
        attempts += 1
        first = attempts == 1
        if not first:
            assert old_closed.is_set()
            discovery_started.set()
            await finish_discovery.wait()
        session = SimpleNamespace(
            send_ping=AsyncMock(side_effect=(
                McpError(ErrorData(code=-32000, message="Session terminated")) if first else None
            )),
            call_tool=AsyncMock(return_value=mcp_types.CallToolResult(
                content=[mcp_types.TextContent(type="text", text="recovered")],
            )),
        )

        async def close():
            if first:
                close_started.set()
                await finish_close.wait()
                old_closed.set()

        tool = MCPToolWrapper(session, name, mcp_types.Tool(
            name="echo", inputSchema={"type": "object"},
        ))
        return MCPServerConnection(close, (tool,))

    monkeypatch.setattr(mcp_runtime, "connect_mcp_server", connect)
    initial = asyncio.Event()
    worker = asyncio.create_task(provider.maintain(initial))
    call = None
    try:
        async with asyncio.timeout(2):
            await initial.wait()
            call = asyncio.create_task(registry.execute("mcp_remote_echo", {}))
            await close_started.wait()
            if cancel_during == "discovery":
                finish_close.set()
                await discovery_started.wait()
            call.cancel()
            with pytest.raises(asyncio.CancelledError):
                await call
            finish_close.set()
            await discovery_started.wait()
            finish_discovery.set()
            while not registry.has("mcp_remote_echo"):
                await asyncio.sleep(0)
            assert await registry.execute("mcp_remote_echo", {}) == "recovered"
            assert attempts == 2
            assert provider.runtime_status() == {"remote": "connected"}
    finally:
        finish_close.set()
        finish_discovery.set()
        if call is not None:
            call.cancel()
            await asyncio.gather(call, return_exceptions=True)
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)
        await provider.aclose()


@pytest.mark.asyncio
async def test_mcp_reconnect_handler_uses_sanitized_server_prefix(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
):
    provider, registry = _make_provider(
        mcp_servers={"remote_": _stdio_server("remote")}
    )
    connect_count = 0

    class _FakeSession:
        def __init__(self, index: int) -> None:
            self.index = index

        async def send_ping(self) -> None:
            if self.index == 1:
                raise McpError(ErrorData(code=-32000, message="Session terminated"))

        async def call_tool(self, _name: str, arguments: dict[str, Any]) -> Any:
            assert arguments == {}
            return SimpleNamespace(
                content=[mcp_types.TextContent(type="text", text="recovered")]
            )

    async def _fake_connect(name, _cfg, *, network, stdio_slots):
        nonlocal connect_count
        connect_count += 1
        tool_def = SimpleNamespace(
            name="quote",
            description="quote tool",
            inputSchema={"type": "object", "properties": {}},
        )
        tool = MCPToolWrapper(_FakeSession(connect_count), name, tool_def)
        stack = AsyncExitStack()
        await stack.__aenter__()
        return MCPServerConnection(stack.aclose, (tool,))

    monkeypatch.setattr("nanobot.agent.tools.mcp.connect_mcp_server", _fake_connect)

    await provider.connect()
    old_tool = registry.get("mcp_remote_quote")
    assert isinstance(old_tool, MCPToolWrapper)

    output = await old_tool.execute()

    assert output == "recovered"
    assert connect_count == 2
    assert registry.get("mcp_remote_quote") is not old_tool


@pytest.mark.asyncio
async def test_concurrent_mcp_reconnect_reuses_fresh_session(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
):
    provider, registry = _make_provider(
        mcp_servers={"remote": _stdio_server("remote")}
    )
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

    async def _fake_connect(name, _cfg, *, network, stdio_slots):
        nonlocal connect_count
        connect_count += 1
        session = _DeadSession() if connect_count == 1 else _LiveSession()
        tools = []
        for resource_name in ("alpha", "beta"):
            resource_def = SimpleNamespace(
                name=resource_name,
                uri=f"file:///{resource_name}",
                description=f"{resource_name} resource",
            )
            tools.append(MCPResourceWrapper(session, name, resource_def))
        stack = AsyncExitStack()
        await stack.__aenter__()
        stack.push_async_callback(_mark_closed, name)
        return MCPServerConnection(stack.aclose, tuple(tools))

    monkeypatch.setattr("nanobot.agent.tools.mcp.connect_mcp_server", _fake_connect)

    await provider.connect()
    old_alpha = registry.get("mcp_remote_resource_alpha")
    old_beta = registry.get("mcp_remote_resource_beta")
    assert isinstance(old_alpha, MCPResourceWrapper)
    assert isinstance(old_beta, MCPResourceWrapper)

    outputs = await asyncio.gather(old_alpha.execute(), old_beta.execute())

    assert outputs == ["fresh:alpha", "fresh:beta"]
    assert connect_count == 2
    assert closed == ["remote"]


@pytest.mark.asyncio
async def test_shared_proxy_snapshot_survives_reconnect_and_reloads_only_opted_in_servers(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
):
    config = Config()
    config.agents.defaults.workspace = str(tmp_path / "workspace")
    config.network.proxy = "http://proxy-a.example:8080"
    config.tools.mcp_servers = {
        "proxied": MCPServerConfig(url="https://mcp.example.com/mcp", use_proxy=True),
        "independent": MCPServerConfig(url="https://other.example.com/mcp"),
    }
    next_network = NetworkConfig(proxy="http://proxy-b.example:8080")
    attempts: list[tuple[str, str | None, str | None]] = []
    closed: list[str] = []
    sessions: dict[str, Any] = {}

    class Session:
        expired = False

        async def send_ping(self) -> None:
            if self.expired:
                raise McpError(ErrorData(code=-32000, message="Session terminated"))

        async def call_tool(self, _name: str, arguments: dict[str, Any]) -> Any:
            return SimpleNamespace(content=[mcp_types.TextContent(type="text", text="ok")])

    async def mark_closed(name: str) -> None:
        closed.append(name)

    async def connect(name, cfg, *, network, stdio_slots):
        attempts.append((name, network.proxy, network.resolve_proxy(cfg.use_proxy)))
        sessions[name] = Session()
        tool = MCPToolWrapper(sessions[name], name, SimpleNamespace(
            name="echo", description="echo", inputSchema={"type": "object"},
        ))
        stack = AsyncExitStack()
        await stack.__aenter__()
        stack.push_async_callback(mark_closed, name)
        return MCPServerConnection(stack.aclose, (tool,))

    monkeypatch.setattr(mcp_runtime, "connect_mcp_server", connect)
    registry = ToolRegistry()
    provider = MCPProvider.from_config(
        config,
        registry,
        server_loader=lambda: (config.tools.mcp_servers, next_network),
    )
    try:
        await provider.connect()
        independent_tool = registry.get("mcp_independent_echo")
        assert attempts == [
            ("proxied", "http://proxy-a.example:8080", "http://proxy-a.example:8080"),
            ("independent", "http://proxy-a.example:8080", None),
        ]

        config.network.proxy = "http://not-live.example:8080"
        sessions["proxied"].expired = True
        old_tool = registry.get("mcp_proxied_echo")
        assert isinstance(old_tool, MCPToolWrapper)
        assert await old_tool.execute() == "ok"
        assert attempts[-1] == (
            "proxied", "http://proxy-a.example:8080", "http://proxy-a.example:8080"
        )

        result = await provider.reload()
        assert result["ok"] is True
        assert result["changed"] == ["proxied"]
        assert result["connected"] == ["independent", "proxied"]
        assert result["tools_removed"] == 1
        assert attempts[-1] == (
            "proxied", "http://proxy-b.example:8080", "http://proxy-b.example:8080"
        )
        assert closed == ["proxied", "proxied"]
        assert registry.get("mcp_independent_echo") is independent_tool

        next_network.proxy = "http://proxy-c.example:8080"
        sessions["proxied"].expired = True
        current_tool = registry.get("mcp_proxied_echo")
        assert isinstance(current_tool, MCPToolWrapper)
        assert await current_tool.execute() == "ok"
        assert attempts[-1] == (
            "proxied", "http://proxy-b.example:8080", "http://proxy-b.example:8080"
        )
        result = await provider.reload()
        assert result["changed"] == ["proxied"]
        assert attempts[-1] == (
            "proxied", "http://proxy-c.example:8080", "http://proxy-c.example:8080"
        )
        assert registry.get("mcp_independent_echo") is independent_tool
        assert closed == ["proxied"] * 4
    finally:
        await provider.aclose()
