"""Tests for MCP tool/resource/prompt transient error handling.

When a transient connection error is detected, wrappers now:
1. Call the ``on_disconnected`` callback to mark the server for reconnection.
2. Return a reconnect message immediately (no retry with stale session).
3. On the next turn, ``connect_missing_servers`` reconnects the server.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from mcp import types as mcp_types
from mcp.shared.exceptions import McpError
from mcp.types import ErrorData

from nanobot.agent.tools.mcp import (
    MCPPromptWrapper,
    MCPResourceWrapper,
    MCPToolWrapper,
    _is_transient,
)

# ---------------------------------------------------------------------------
# _is_transient helper
# ---------------------------------------------------------------------------


class _FakeClosedResourceError(Exception):
    pass


_FakeClosedResourceError.__name__ = "ClosedResourceError"


class _FakeEndOfStreamError(Exception):
    pass


_FakeEndOfStreamError.__name__ = "EndOfStream"


def test_is_transient_recognized_closed_resource():
    assert _is_transient(_FakeClosedResourceError("gone"))


def test_is_transient_recognizes_broken_pipe():
    assert _is_transient(BrokenPipeError("pipe"))


def test_is_transient_recognizes_connection_reset():
    assert _is_transient(ConnectionResetError("reset"))


def test_is_transient_recognizes_connection_refused():
    assert _is_transient(ConnectionRefusedError("refused"))


def test_is_transient_recognizes_end_of_stream():
    assert _is_transient(_FakeEndOfStreamError("eof"))


def test_is_transient_rejects_value_error():
    assert not _is_transient(ValueError("nope"))


def test_is_transient_rejects_runtime_error():
    assert not _is_transient(RuntimeError("nope"))


def test_is_transient_rejects_timeout():
    assert not _is_transient(TimeoutError("timeout"))


# ---------------------------------------------------------------------------
# MCPToolWrapper transient error handling
# ---------------------------------------------------------------------------


def _make_tool_def(name="test_tool"):
    return SimpleNamespace(
        name=name,
        description="A test tool",
        inputSchema={"type": "object", "properties": {}},
    )


def _make_tool_result(text):
    """Build a mock tool result with proper MCP TextContent."""
    return SimpleNamespace(content=[mcp_types.TextContent(type="text", text=text)])


@pytest.mark.asyncio
async def test_tool_calls_on_disconnected_on_transient_error():
    """On transient error, wrapper calls on_disconnected instead of retrying with stale session."""
    session = AsyncMock()
    exc = _FakeClosedResourceError("connection lost")
    session.call_tool = AsyncMock(side_effect=exc)

    on_disconnected = MagicMock()

    wrapper = MCPToolWrapper(
        session, "test_server", _make_tool_def(), tool_timeout=5,
        on_disconnected=on_disconnected,
    )
    output = await wrapper.execute(foo="bar")

    assert "reconnecting" in output
    on_disconnected.assert_called_once_with("test_server")
    # Should NOT retry with the stale session
    assert session.call_tool.call_count == 1


@pytest.mark.asyncio
async def test_tool_reconnect_message_on_transient_error():
    """Wrapper returns reconnection message on transient error."""
    session = AsyncMock()
    exc = _FakeClosedResourceError("connection lost")
    session.call_tool = AsyncMock(side_effect=exc)

    wrapper = MCPToolWrapper(
        session, "test_server", _make_tool_def(), tool_timeout=5,
        on_disconnected=MagicMock(),
    )
    output = await wrapper.execute()

    assert "MCP server connection lost" in output
    assert "reconnecting" in output.lower() or "reconnect" in output.lower()


@pytest.mark.asyncio
async def test_tool_no_on_disconnected_without_callback():
    """Without on_disconnected callback, wrapper still returns reconnection message."""
    session = AsyncMock()
    exc = _FakeClosedResourceError("connection lost")
    session.call_tool = AsyncMock(side_effect=exc)

    wrapper = MCPToolWrapper(session, "test_server", _make_tool_def(), tool_timeout=5)
    output = await wrapper.execute()

    assert "reconnecting" in output


@pytest.mark.asyncio
async def test_tool_on_disconnected_callback_error_suppressed():
    """If on_disconnected callback raises, wrapper still returns reconnection message."""
    session = AsyncMock()
    exc = _FakeClosedResourceError("connection lost")
    session.call_tool = AsyncMock(side_effect=exc)

    failing_callback = MagicMock(side_effect=RuntimeError("callback boom"))

    wrapper = MCPToolWrapper(
        session, "test_server", _make_tool_def(), tool_timeout=5,
        on_disconnected=failing_callback,
    )
    output = await wrapper.execute()

    assert "reconnecting" in output


@pytest.mark.asyncio
async def test_tool_no_retry_on_non_transient_error():
    """Tool should NOT retry on non-transient errors like ValueError."""
    session = AsyncMock()
    session.call_tool = AsyncMock(side_effect=ValueError("bad input"))

    wrapper = MCPToolWrapper(session, "test_server", _make_tool_def(), tool_timeout=5)
    output = await wrapper.execute()

    assert "ValueError" in output
    assert "retry" not in output
    assert session.call_tool.call_count == 1


@pytest.mark.asyncio
async def test_tool_no_retry_on_timeout():
    """Timeouts should not trigger retry (they have their own handling)."""
    session = AsyncMock()
    session.call_tool = AsyncMock(side_effect=asyncio.TimeoutError())

    wrapper = MCPToolWrapper(session, "test_server", _make_tool_def(), tool_timeout=5)
    output = await wrapper.execute()

    assert "timed out" in output
    assert session.call_tool.call_count == 1


@pytest.mark.asyncio
async def test_tool_success_on_first_try():
    """Normal success path — no retry logic involved."""
    session = AsyncMock()
    result = _make_tool_result("hello")
    session.call_tool = AsyncMock(return_value=result)

    wrapper = MCPToolWrapper(session, "test_server", _make_tool_def(), tool_timeout=5)
    output = await wrapper.execute()

    assert output == "hello"
    assert session.call_tool.call_count == 1


@pytest.mark.asyncio
async def test_tool_does_not_retry_on_cancelled_error():
    """``asyncio.CancelledError`` must short-circuit the retry loop.

    Regression guard: the retry branch lives under ``except Exception``,
    but ``CancelledError`` inherits from ``BaseException``, not
    ``Exception``, so it naturally bypasses the retry branch today.  If a
    future refactor ever widens the retry branch to ``BaseException`` (or
    re-orders the handlers), ``/stop`` would start retrying instead of
    cancelling — this test pins that invariant.
    """
    session = AsyncMock()
    session.call_tool = AsyncMock(side_effect=asyncio.CancelledError())

    wrapper = MCPToolWrapper(session, "test_server", _make_tool_def(), tool_timeout=5)

    output = await wrapper.execute()

    assert "cancelled" in output
    assert session.call_tool.call_count == 1


# ---------------------------------------------------------------------------
# MCPResourceWrapper transient error handling
# ---------------------------------------------------------------------------


def _make_resource_def(name="test_resource"):
    return SimpleNamespace(
        name=name,
        uri="file:///test",
        description="A test resource",
    )


def _make_resource_result(text):
    return SimpleNamespace(
        contents=[mcp_types.TextResourceContents(uri="file:///test", text=text)]
    )


@pytest.mark.asyncio
async def test_resource_calls_on_disconnected_on_transient_error():
    """On transient error, resource wrapper calls on_disconnected instead of retrying."""
    session = AsyncMock()
    exc = _FakeClosedResourceError("gone")
    session.read_resource = AsyncMock(side_effect=exc)

    on_disconnected = MagicMock()

    wrapper = MCPResourceWrapper(
        session, "test_server", _make_resource_def(),
        on_disconnected=on_disconnected,
    )
    output = await wrapper.execute()

    assert "reconnecting" in output
    on_disconnected.assert_called_once_with("test_server")
    assert session.read_resource.call_count == 1


@pytest.mark.asyncio
async def test_resource_no_retry_on_non_transient():
    """Resource should not retry on non-transient errors."""
    session = AsyncMock()
    session.read_resource = AsyncMock(side_effect=RuntimeError("bad"))

    wrapper = MCPResourceWrapper(session, "test_server", _make_resource_def())
    output = await wrapper.execute()

    assert "RuntimeError" in output
    assert session.read_resource.call_count == 1


# ---------------------------------------------------------------------------
# MCPPromptWrapper transient error handling
# ---------------------------------------------------------------------------


def _make_prompt_def(name="test_prompt"):
    return SimpleNamespace(
        name=name,
        description="A test prompt",
        arguments=[],
    )


def _make_prompt_result(text):
    return SimpleNamespace(
        messages=[
            SimpleNamespace(
                content=mcp_types.TextContent(type="text", text=text),
            )
        ]
    )


@pytest.mark.asyncio
async def test_prompt_calls_on_disconnected_on_transient_error():
    """On transient error, prompt wrapper calls on_disconnected instead of retrying."""
    session = AsyncMock()
    exc = _FakeClosedResourceError("gone")
    session.get_prompt = AsyncMock(side_effect=exc)

    on_disconnected = MagicMock()

    wrapper = MCPPromptWrapper(
        session, "test_server", _make_prompt_def(),
        on_disconnected=on_disconnected,
    )
    output = await wrapper.execute()

    assert "reconnecting" in output
    on_disconnected.assert_called_once_with("test_server")
    assert session.get_prompt.call_count == 1


@pytest.mark.asyncio
async def test_prompt_no_retry_on_mcp_error():
    """McpError (application-level) should NOT trigger retry."""
    session = AsyncMock()
    session.get_prompt = AsyncMock(
        side_effect=McpError(ErrorData(code=-1, message="not found"))
    )

    wrapper = MCPPromptWrapper(session, "test_server", _make_prompt_def())
    output = await wrapper.execute()

    assert "not found" in output
    assert session.get_prompt.call_count == 1


@pytest.mark.asyncio
async def test_prompt_no_retry_on_non_transient():
    """Non-transient errors should not trigger retry for prompts."""
    session = AsyncMock()
    session.get_prompt = AsyncMock(side_effect=RuntimeError("bad"))

    wrapper = MCPPromptWrapper(session, "test_server", _make_prompt_def())
    output = await wrapper.execute()

    assert "RuntimeError" in output
    assert session.get_prompt.call_count == 1


# ---------------------------------------------------------------------------
# mark_server_disconnected integration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mark_server_disconnected_removes_stack_and_unregisters_tools():
    """mark_server_disconnected pops the stack, unregisters tools, resets _mcp_connected."""
    from nanobot.agent.tools.mcp import mark_server_disconnected
    from nanobot.agent.tools.registry import ToolRegistry

    registry = ToolRegistry()
    # Register a fake tool for the server
    registry.register(MCPToolWrapper(
        AsyncMock(), "my_server", _make_tool_def(), tool_timeout=5,
    ))

    state = SimpleNamespace(
        _mcp_stacks={"my_server": AsyncExitStack()},
        _mcp_servers={"my_server": SimpleNamespace()},
        _mcp_connected=True,
    )

    mark_server_disconnected(state, registry, "my_server")

    assert "my_server" not in state._mcp_stacks
    assert state._mcp_connected is False
    # The tool should be unregistered
    assert not any(t.startswith("mcp_my_server_") for t in registry.tool_names)


from contextlib import AsyncExitStack