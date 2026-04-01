from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack, asynccontextmanager
import sys
from types import ModuleType, SimpleNamespace

import pytest

from nanobot.agent.tools.mcp import (
    MCPToolWrapper,
    connect_mcp_servers,
    refresh_mcp_tools,
    setup_tools_list_changed_handler,
)
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.config.schema import MCPServerConfig


class _FakeTextContent:
    def __init__(self, text: str) -> None:
        self.text = text


@pytest.fixture
def fake_mcp_runtime() -> dict[str, object | None]:
    return {"session": None}


@pytest.fixture(autouse=True)
def _fake_mcp_module(
    monkeypatch: pytest.MonkeyPatch, fake_mcp_runtime: dict[str, object | None]
) -> None:
    mod = ModuleType("mcp")
    mod.types = SimpleNamespace(TextContent=_FakeTextContent)

    class _FakeStdioServerParameters:
        def __init__(self, command: str, args: list[str], env: dict | None = None) -> None:
            self.command = command
            self.args = args
            self.env = env

    class _FakeClientSession:
        def __init__(self, _read: object, _write: object) -> None:
            self._session = fake_mcp_runtime["session"]

        async def __aenter__(self) -> object:
            return self._session

        async def __aexit__(self, exc_type, exc, tb) -> bool:
            return False

    @asynccontextmanager
    async def _fake_stdio_client(_params: object):
        yield object(), object()

    @asynccontextmanager
    async def _fake_sse_client(_url: str, httpx_client_factory=None):
        yield object(), object()

    @asynccontextmanager
    async def _fake_streamable_http_client(_url: str, http_client=None):
        yield object(), object(), object()

    mod.ClientSession = _FakeClientSession
    mod.StdioServerParameters = _FakeStdioServerParameters
    monkeypatch.setitem(sys.modules, "mcp", mod)

    client_mod = ModuleType("mcp.client")
    stdio_mod = ModuleType("mcp.client.stdio")
    stdio_mod.stdio_client = _fake_stdio_client
    sse_mod = ModuleType("mcp.client.sse")
    sse_mod.sse_client = _fake_sse_client
    streamable_http_mod = ModuleType("mcp.client.streamable_http")
    streamable_http_mod.streamable_http_client = _fake_streamable_http_client

    monkeypatch.setitem(sys.modules, "mcp.client", client_mod)
    monkeypatch.setitem(sys.modules, "mcp.client.stdio", stdio_mod)
    monkeypatch.setitem(sys.modules, "mcp.client.sse", sse_mod)
    monkeypatch.setitem(sys.modules, "mcp.client.streamable_http", streamable_http_mod)


def _make_wrapper(session: object, *, timeout: float = 0.1) -> MCPToolWrapper:
    tool_def = SimpleNamespace(
        name="demo",
        description="demo tool",
        inputSchema={"type": "object", "properties": {}},
    )
    return MCPToolWrapper(session, "test", tool_def, tool_timeout=timeout)


def test_wrapper_preserves_non_nullable_unions() -> None:
    tool_def = SimpleNamespace(
        name="demo",
        description="demo tool",
        inputSchema={
            "type": "object",
            "properties": {
                "value": {
                    "anyOf": [{"type": "string"}, {"type": "integer"}],
                }
            },
        },
    )

    wrapper = MCPToolWrapper(SimpleNamespace(call_tool=None), "test", tool_def)

    assert wrapper.parameters["properties"]["value"]["anyOf"] == [
        {"type": "string"},
        {"type": "integer"},
    ]


def test_wrapper_normalizes_nullable_property_type_union() -> None:
    tool_def = SimpleNamespace(
        name="demo",
        description="demo tool",
        inputSchema={
            "type": "object",
            "properties": {
                "name": {"type": ["string", "null"]},
            },
        },
    )

    wrapper = MCPToolWrapper(SimpleNamespace(call_tool=None), "test", tool_def)

    assert wrapper.parameters["properties"]["name"] == {"type": "string", "nullable": True}


def test_wrapper_normalizes_nullable_property_anyof() -> None:
    tool_def = SimpleNamespace(
        name="demo",
        description="demo tool",
        inputSchema={
            "type": "object",
            "properties": {
                "name": {
                    "anyOf": [{"type": "string"}, {"type": "null"}],
                    "description": "optional name",
                },
            },
        },
    )

    wrapper = MCPToolWrapper(SimpleNamespace(call_tool=None), "test", tool_def)

    assert wrapper.parameters["properties"]["name"] == {
        "type": "string",
        "description": "optional name",
        "nullable": True,
    }


@pytest.mark.asyncio
async def test_execute_returns_text_blocks() -> None:
    async def call_tool(_name: str, arguments: dict) -> object:
        assert arguments == {"value": 1}
        return SimpleNamespace(content=[_FakeTextContent("hello"), 42])

    wrapper = _make_wrapper(SimpleNamespace(call_tool=call_tool))

    result = await wrapper.execute(value=1)

    assert result == "hello\n42"


@pytest.mark.asyncio
async def test_execute_returns_timeout_message() -> None:
    async def call_tool(_name: str, arguments: dict) -> object:
        await asyncio.sleep(1)
        return SimpleNamespace(content=[])

    wrapper = _make_wrapper(SimpleNamespace(call_tool=call_tool), timeout=0.01)

    result = await wrapper.execute()

    assert result == "(MCP tool call timed out after 0.01s)"


@pytest.mark.asyncio
async def test_execute_handles_server_cancelled_error() -> None:
    async def call_tool(_name: str, arguments: dict) -> object:
        raise asyncio.CancelledError()

    wrapper = _make_wrapper(SimpleNamespace(call_tool=call_tool))

    result = await wrapper.execute()

    assert result == "(MCP tool call was cancelled)"


@pytest.mark.asyncio
async def test_execute_re_raises_external_cancellation() -> None:
    started = asyncio.Event()

    async def call_tool(_name: str, arguments: dict) -> object:
        started.set()
        await asyncio.sleep(60)
        return SimpleNamespace(content=[])

    wrapper = _make_wrapper(SimpleNamespace(call_tool=call_tool), timeout=10)
    task = asyncio.create_task(wrapper.execute())
    await started.wait()

    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_execute_handles_generic_exception() -> None:
    async def call_tool(_name: str, arguments: dict) -> object:
        raise RuntimeError("boom")

    wrapper = _make_wrapper(SimpleNamespace(call_tool=call_tool))

    result = await wrapper.execute()

    assert result == "(MCP tool call failed: RuntimeError)"


def _make_tool_def(name: str) -> SimpleNamespace:
    return SimpleNamespace(
        name=name,
        description=f"{name} tool",
        inputSchema={"type": "object", "properties": {}},
    )


def _make_fake_session(tool_names: list[str]) -> SimpleNamespace:
    async def initialize() -> None:
        return None

    async def list_tools() -> SimpleNamespace:
        return SimpleNamespace(tools=[_make_tool_def(name) for name in tool_names])

    return SimpleNamespace(initialize=initialize, list_tools=list_tools)


@pytest.mark.asyncio
async def test_connect_mcp_servers_enabled_tools_supports_raw_names(
    fake_mcp_runtime: dict[str, object | None],
) -> None:
    fake_mcp_runtime["session"] = _make_fake_session(["demo", "other"])
    registry = ToolRegistry()
    stack = AsyncExitStack()
    await stack.__aenter__()
    try:
        await connect_mcp_servers(
            {"test": MCPServerConfig(command="fake", enabled_tools=["demo"])},
            registry,
            stack,
        )
    finally:
        await stack.aclose()

    assert registry.tool_names == ["mcp_test_demo"]


@pytest.mark.asyncio
async def test_connect_mcp_servers_enabled_tools_defaults_to_all(
    fake_mcp_runtime: dict[str, object | None],
) -> None:
    fake_mcp_runtime["session"] = _make_fake_session(["demo", "other"])
    registry = ToolRegistry()
    stack = AsyncExitStack()
    await stack.__aenter__()
    try:
        await connect_mcp_servers(
            {"test": MCPServerConfig(command="fake")},
            registry,
            stack,
        )
    finally:
        await stack.aclose()

    assert registry.tool_names == ["mcp_test_demo", "mcp_test_other"]


@pytest.mark.asyncio
async def test_connect_mcp_servers_enabled_tools_supports_wrapped_names(
    fake_mcp_runtime: dict[str, object | None],
) -> None:
    fake_mcp_runtime["session"] = _make_fake_session(["demo", "other"])
    registry = ToolRegistry()
    stack = AsyncExitStack()
    await stack.__aenter__()
    try:
        await connect_mcp_servers(
            {"test": MCPServerConfig(command="fake", enabled_tools=["mcp_test_demo"])},
            registry,
            stack,
        )
    finally:
        await stack.aclose()

    assert registry.tool_names == ["mcp_test_demo"]


@pytest.mark.asyncio
async def test_connect_mcp_servers_enabled_tools_empty_list_registers_none(
    fake_mcp_runtime: dict[str, object | None],
) -> None:
    fake_mcp_runtime["session"] = _make_fake_session(["demo", "other"])
    registry = ToolRegistry()
    stack = AsyncExitStack()
    await stack.__aenter__()
    try:
        await connect_mcp_servers(
            {"test": MCPServerConfig(command="fake", enabled_tools=[])},
            registry,
            stack,
        )
    finally:
        await stack.aclose()

    assert registry.tool_names == []


@pytest.mark.asyncio
async def test_connect_mcp_servers_enabled_tools_warns_on_unknown_entries(
    fake_mcp_runtime: dict[str, object | None], monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_mcp_runtime["session"] = _make_fake_session(["demo"])
    registry = ToolRegistry()
    warnings: list[str] = []

    def _warning(message: str, *args: object) -> None:
        warnings.append(message.format(*args))

    monkeypatch.setattr("nanobot.agent.tools.mcp.logger.warning", _warning)

    stack = AsyncExitStack()
    await stack.__aenter__()
    try:
        await connect_mcp_servers(
            {"test": MCPServerConfig(command="fake", enabled_tools=["unknown"])},
            registry,
            stack,
        )
    finally:
        await stack.aclose()

    assert registry.tool_names == []
    assert warnings
    assert "enabledTools entries not found: unknown" in warnings[-1]
    assert "Available raw names: demo" in warnings[-1]
    assert "Available wrapped names: mcp_test_demo" in warnings[-1]


# ---------------------------------------------------------------------------
# Helpers for mutable fake sessions used by notification tests
# ---------------------------------------------------------------------------

def _make_mutable_fake_session(
    initial_tools: list[str],
) -> tuple[SimpleNamespace, list[list[str]]]:
    """Create a fake session whose ``list_tools`` output can be changed.

    Returns ``(session, tool_names_ref)`` where *tool_names_ref* is a
    single-element list wrapping the current tool-name list.  Mutate
    ``tool_names_ref[0]`` to change what ``list_tools`` returns.
    """
    tool_names_ref: list[list[str]] = [list(initial_tools)]
    call_count: list[int] = [0]

    async def initialize() -> None:
        return None

    async def list_tools() -> SimpleNamespace:
        call_count[0] += 1
        return SimpleNamespace(
            tools=[_make_tool_def(n) for n in tool_names_ref[0]]
        )

    session = SimpleNamespace(
        initialize=initialize,
        list_tools=list_tools,
        _list_tools_call_count=call_count,
    )
    return session, tool_names_ref


def _make_cfg(enabled: list[str] | None = None) -> MCPServerConfig:
    """Shortcut to build an MCPServerConfig with ``enabled_tools``."""
    if enabled is None:
        return MCPServerConfig(command="fake")
    return MCPServerConfig(command="fake", enabled_tools=enabled)


# ---------------------------------------------------------------------------
# notifications/tools/list_changed tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tools_list_changed_triggers_refresh() -> None:
    """Simulating the notification must call list_tools on ALL servers."""
    sess_a, _ = _make_mutable_fake_session(["alpha"])
    sess_b, _ = _make_mutable_fake_session(["beta"])

    cfg_a = _make_cfg()
    cfg_b = _make_cfg()

    servers: dict[str, tuple[object, object]] = {
        "a": (sess_a, cfg_a),
        "b": (sess_b, cfg_b),
    }
    registry = ToolRegistry()
    lock = asyncio.Lock()

    # Initial registration
    await refresh_mcp_tools(servers, registry)
    assert sorted(registry.tool_names) == ["mcp_a_alpha", "mcp_b_beta"]

    # Reset call counts after initial load
    sess_a._list_tools_call_count[0] = 0
    sess_b._list_tools_call_count[0] = 0

    # Wire up notification handler and trigger it
    setup_tools_list_changed_handler(servers, registry, lock)
    await sess_a._on_tools_list_changed()

    # Both servers must have been queried
    assert sess_a._list_tools_call_count[0] == 1
    assert sess_b._list_tools_call_count[0] == 1
    assert sorted(registry.tool_names) == ["mcp_a_alpha", "mcp_b_beta"]


@pytest.mark.asyncio
async def test_tools_list_changed_registry_reflects_updated_tools() -> None:
    """After the notification, old tools are gone and new tools are present."""
    sess_a, ref_a = _make_mutable_fake_session(["old_tool"])
    sess_b, ref_b = _make_mutable_fake_session(["stable"])

    servers: dict[str, tuple[object, object]] = {
        "a": (sess_a, _make_cfg()),
        "b": (sess_b, _make_cfg()),
    }
    registry = ToolRegistry()
    lock = asyncio.Lock()

    await refresh_mcp_tools(servers, registry)
    assert "mcp_a_old_tool" in registry
    assert "mcp_b_stable" in registry

    # Server "a" changes its tool list
    ref_a[0] = ["new_tool"]

    setup_tools_list_changed_handler(servers, registry, lock)
    await sess_b._on_tools_list_changed()

    assert "mcp_a_old_tool" not in registry
    assert "mcp_a_new_tool" in registry
    # Server "b" is unchanged
    assert "mcp_b_stable" in registry


@pytest.mark.asyncio
async def test_tools_list_changed_does_not_interrupt_sessions() -> None:
    """A mid-flight tool execution must complete even when the notification fires."""
    execution_started = asyncio.Event()
    allow_finish = asyncio.Event()

    async def slow_call_tool(_name: str, arguments: dict) -> SimpleNamespace:
        execution_started.set()
        await allow_finish.wait()
        return SimpleNamespace(content=[_FakeTextContent("done")])

    sess, ref = _make_mutable_fake_session(["slow"])
    sess.call_tool = slow_call_tool

    servers: dict[str, tuple[object, object]] = {
        "srv": (sess, _make_cfg()),
    }
    registry = ToolRegistry()
    lock = asyncio.Lock()

    await refresh_mcp_tools(servers, registry)
    setup_tools_list_changed_handler(servers, registry, lock)

    # Start a tool execution in the background
    wrapper = MCPToolWrapper(sess, "srv", _make_tool_def("slow"))
    exec_task = asyncio.create_task(wrapper.execute())
    await execution_started.wait()

    # Fire the notification while the tool is still running
    ref[0] = ["slow", "extra"]
    refresh_task = asyncio.create_task(
        sess._on_tools_list_changed()
    )

    # Let the tool finish
    allow_finish.set()
    result = await exec_task
    await refresh_task

    assert result == "done"
    # Registry now has the updated tool list
    assert "mcp_srv_slow" in registry
    assert "mcp_srv_extra" in registry
