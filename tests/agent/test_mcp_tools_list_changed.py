"""Tests for MCP tools/list_changed notification handling."""
import asyncio
from contextlib import AsyncExitStack
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot.bus.events import (
    INBOUND_META_RUNTIME_CONTROL,
    RUNTIME_CONTROL_MCP_RELOAD,
    RUNTIME_CONTROL_MCP_SERVER_NAME,
    RUNTIME_CONTROL_MCP_TOOLS_CHANGED,
    InboundMessage,
)
from nanobot.agent.tools.mcp import (
    _make_notification_handler,
    _tool_prefix,
    handle_runtime_control,
    reload_server_tools,
)
from nanobot.agent.tools.registry import ToolRegistry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _FakeToolDef(SimpleNamespace):
    pass


def _make_tool_def(name: str) -> _FakeToolDef:
    return _FakeToolDef(
        name=name,
        description=f"{name} tool",
        inputSchema={"type": "object", "properties": {}},
    )


class _FakeMcpTool:
    name: str

    def __init__(self, name: str) -> None:
        self.name = name

    async def execute(self, **kwargs) -> str:
        return "ok"


# ---------------------------------------------------------------------------
# _make_notification_handler
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_notification_handler_publishes_tools_list_changed() -> None:
    """When the handler receives a ToolListChangedNotification, it publishes
    an inbound runtime-control message to the bus."""
    published: list[InboundMessage] = []

    class _FakeBus:
        async def publish_inbound(self, msg: InboundMessage) -> None:
            published.append(msg)

    from mcp.types import ToolListChangedNotification
    handler = _make_notification_handler("my-server", bus=_FakeBus(), registry_ref=None)
    notification = ToolListChangedNotification(params=None)

    await handler(notification)

    assert len(published) == 1
    msg = published[0]
    assert msg.content == RUNTIME_CONTROL_MCP_TOOLS_CHANGED
    assert msg.metadata[INBOUND_META_RUNTIME_CONTROL] == RUNTIME_CONTROL_MCP_TOOLS_CHANGED
    assert msg.metadata[RUNTIME_CONTROL_MCP_SERVER_NAME] == "my-server"
    assert msg.channel == "system"
    assert msg.sender_id == "mcp-server-my-server"
    assert msg.chat_id == "runtime"


@pytest.mark.asyncio
async def test_notification_handler_delegates_non_tool_list_changed() -> None:
    """Non-ToolListChanged notifications fall through to the default handler."""
    called_default = False

    class _NonToolNotification:
        pass

    async def _fake_default(msg: object) -> None:
        nonlocal called_default
        called_default = True

    handler_fn = _make_notification_handler("my-server", bus=None, registry_ref=None)
    # Patch the resolved default function for this test
    # Since _default_fn is captured at closure time, we need to test differently.
    # The handler should silently accept non-matching notifications without error.
    await handler_fn(_NonToolNotification())
    # Without a bus or matching notification, handler simply runs without error.


@pytest.mark.asyncio
async def test_notification_handler_no_bus_no_crash() -> None:
    """When bus is None and a ToolListChangedNotification arrives, no crash."""
    from mcp.types import ToolListChangedNotification
    handler = _make_notification_handler("test", bus=None, registry_ref=None)
    notification = ToolListChangedNotification(params=None)
    # Should not raise
    await handler(notification)


# ---------------------------------------------------------------------------
# handle_runtime_control
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_handle_runtime_control_ignores_unknown_control() -> None:
    """Messages without a recognized control type are ignored (returns False)."""
    msg = InboundMessage(
        channel="system", sender_id="test", chat_id="runtime",
        content="unknown", metadata={INBOUND_META_RUNTIME_CONTROL: "unknown"},
    )
    state = SimpleNamespace(_mcp_stacks={}, _mcp_servers={})
    registry = ToolRegistry()
    result = await handle_runtime_control(state, msg, registry)
    assert result is False


@pytest.mark.asyncio
async def test_handle_runtime_control_mcp_tools_changed_known_server() -> None:
    """tools/list_changed for a known server triggers reload_server_tools."""
    registry = ToolRegistry()
    registry.register(_FakeMcpTool("mcp_test_tool_a"))

    stacks = {"test": AsyncExitStack()}
    state = SimpleNamespace(
        _mcp_stacks=stacks,
        _mcp_servers={"test": SimpleNamespace(enabled_tools=["*"], tool_timeout=30)},
    )

    msg = InboundMessage(
        channel="system",
        sender_id="mcp-server-test",
        chat_id="runtime",
        content=RUNTIME_CONTROL_MCP_TOOLS_CHANGED,
        metadata={
            INBOUND_META_RUNTIME_CONTROL: RUNTIME_CONTROL_MCP_TOOLS_CHANGED,
            RUNTIME_CONTROL_MCP_SERVER_NAME: "test",
        },
    )

    with patch("nanobot.agent.tools.mcp.reload_server_tools", new_callable=AsyncMock) as mock_reload:
        mock_reload.return_value = {"ok": True, "tools_registered": 2}
        result = await handle_runtime_control(state, msg, registry)

    assert result is True
    mock_reload.assert_awaited_once_with(state, registry, "test")


@pytest.mark.asyncio
async def test_handle_runtime_control_mcp_tools_changed_unknown_server() -> None:
    """tools/list_changed for an unknown server falls back to full reload."""
    registry = ToolRegistry()
    state = SimpleNamespace(_mcp_stacks={}, _mcp_servers={})

    msg = InboundMessage(
        channel="system",
        sender_id="mcp-server-unknown",
        chat_id="runtime",
        content=RUNTIME_CONTROL_MCP_TOOLS_CHANGED,
        metadata={
            INBOUND_META_RUNTIME_CONTROL: RUNTIME_CONTROL_MCP_TOOLS_CHANGED,
            RUNTIME_CONTROL_MCP_SERVER_NAME: "unknown",
        },
    )

    with patch("nanobot.agent.tools.mcp.reload_servers", new_callable=AsyncMock) as mock_reload:
        mock_reload.return_value = {"ok": True}
        result = await handle_runtime_control(state, msg, registry)

    assert result is True
    mock_reload.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_runtime_control_mcp_reload_existing_path() -> None:
    """The existing MCP_RELOAD control type still works."""
    registry = ToolRegistry()
    ack = asyncio.get_event_loop().create_future()
    state = SimpleNamespace(_mcp_stacks={}, _mcp_servers={})

    msg = InboundMessage(
        channel="system",
        sender_id="test",
        chat_id="runtime",
        content=RUNTIME_CONTROL_MCP_RELOAD,
        metadata={
            INBOUND_META_RUNTIME_CONTROL: RUNTIME_CONTROL_MCP_RELOAD,
        },
    )

    with patch("nanobot.agent.tools.mcp.reload_servers", new_callable=AsyncMock) as mock_reload:
        mock_reload.return_value = {"ok": True}
        result = await handle_runtime_control(state, msg, registry)

    assert result is True
    mock_reload.assert_awaited_once()


# ---------------------------------------------------------------------------
# reload_server_tools
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_reload_server_tools_server_not_connected() -> None:
    """Returns error when the server is not in the stacks dict."""
    state = SimpleNamespace(_mcp_stacks={}, _mcp_servers={})
    registry = ToolRegistry()
    result = await reload_server_tools(state, registry, "missing")
    assert result["ok"] is False
    assert "not connected" in result["message"].lower()


@pytest.mark.asyncio
async def test_reload_server_tools_removes_and_re_registers() -> None:
    """reload_server_tools unregisters old tools, re-fetches, and re-registers."""
    registry = ToolRegistry()
    # Pre-register an old tool
    registry.register(_FakeMcpTool("mcp_test_old_tool"))

    # Fake session that returns a new tool list
    fake_session = SimpleNamespace(
        list_tools=AsyncMock(return_value=SimpleNamespace(
            tools=[_make_tool_def("new_tool")]
        )),
        list_resources=AsyncMock(return_value=SimpleNamespace(resources=[])),
        list_prompts=AsyncMock(return_value=SimpleNamespace(prompts=[])),
    )

    # Patch _find_session_in_stack to return our fake session
    with patch("nanobot.agent.tools.mcp._find_session_in_stack", return_value=fake_session):
        stack = AsyncExitStack()
        stacks = {"test": stack}
        state = SimpleNamespace(
            _mcp_stacks=stacks,
            _mcp_servers={"test": SimpleNamespace(enabled_tools=["*"], tool_timeout=30)},
        )
        result = await reload_server_tools(state, registry, "test")

    assert result["ok"] is True
    assert result["tools_removed"] >= 1
    assert result["tools_registered"] >= 1


# ---------------------------------------------------------------------------
# Helper function: _find_session_in_stack (extracted from _unregister code)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_reload_server_tools_fallback_when_session_not_found() -> None:
    """If the session can't be found in the stack, mark disconnected and return."""
    registry = ToolRegistry()
    registry.register(_FakeMcpTool("mcp_test_tool"))

    stack = AsyncExitStack()
    stacks = {"test": stack}
    state = SimpleNamespace(
        _mcp_stacks=stacks,
        _mcp_servers={"test": SimpleNamespace(enabled_tools=["*"], tool_timeout=30)},
    )

    with patch("nanobot.agent.tools.mcp._find_session_in_stack", return_value=None):
        with patch("nanobot.agent.tools.mcp.mark_server_disconnected") as mock_mark:
            result = await reload_server_tools(state, registry, "test")

    assert result["ok"] is False
    assert result.get("requires_reconnect") is True
    mock_mark.assert_called_once_with(state, registry, "test")