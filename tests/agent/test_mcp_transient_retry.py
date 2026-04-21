"""Tests for MCP tool/resource/prompt transient error retry."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

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


def test_is_transient_recognizes_closed_resource():
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
# MCPToolWrapper retry behaviour
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
async def test_tool_retries_on_transient_error():
    """Tool should retry once when a transient error occurs, then succeed."""
    session = AsyncMock()
    result = _make_tool_result("ok")
    exc = _FakeClosedResourceError("connection lost")
    session.call_tool = AsyncMock(side_effect=[exc, result])

    wrapper = MCPToolWrapper(session, "test_server", _make_tool_def(), tool_timeout=5)

    with patch("nanobot.agent.tools.mcp.asyncio.sleep", new_callable=AsyncMock):
        output = await wrapper.execute(foo="bar")

    assert output == "ok"
    assert session.call_tool.call_count == 2


@pytest.mark.asyncio
async def test_tool_fails_after_retry_exhausted():
    """Tool should fail with retry message when both attempts hit transient errors."""
    session = AsyncMock()
    exc1 = _FakeClosedResourceError("still dead")
    exc2 = _FakeClosedResourceError("still dead again")
    session.call_tool = AsyncMock(side_effect=[exc1, exc2])

    wrapper = MCPToolWrapper(session, "test_server", _make_tool_def(), tool_timeout=5)

    with patch("nanobot.agent.tools.mcp.asyncio.sleep", new_callable=AsyncMock):
        output = await wrapper.execute()

    assert "failed after retry" in output
    assert "ClosedResourceError" in output
    assert session.call_tool.call_count == 2


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
async def test_tool_success_on_first_try_no_retry():
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
    """`asyncio.CancelledError` must short-circuit the retry loop.

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

    with patch("nanobot.agent.tools.mcp.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        output = await wrapper.execute()

    assert "cancelled" in output
    assert session.call_tool.call_count == 1
    mock_sleep.assert_not_called()


@pytest.mark.asyncio
async def test_tool_retry_on_connection_reset():
    """ConnectionResetError (a stdlib exception) should also trigger retry."""
    session = AsyncMock()
    result = _make_tool_result("recovered")
    session.call_tool = AsyncMock(
        side_effect=[ConnectionResetError("reset by peer"), result]
    )

    wrapper = MCPToolWrapper(session, "test_server", _make_tool_def(), tool_timeout=5)

    with patch("nanobot.agent.tools.mcp.asyncio.sleep", new_callable=AsyncMock):
        output = await wrapper.execute()

    assert output == "recovered"
    assert session.call_tool.call_count == 2


@pytest.mark.asyncio
async def test_tool_retry_on_end_of_stream():
    """EndOfStream (anyio) should trigger retry."""
    session = AsyncMock()
    result = _make_tool_result("back")
    session.call_tool = AsyncMock(side_effect=[_FakeEndOfStreamError("eof"), result])

    wrapper = MCPToolWrapper(session, "test_server", _make_tool_def(), tool_timeout=5)

    with patch("nanobot.agent.tools.mcp.asyncio.sleep", new_callable=AsyncMock):
        output = await wrapper.execute()

    assert output == "back"
    assert session.call_tool.call_count == 2


# ---------------------------------------------------------------------------
# MCPResourceWrapper retry behaviour
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
async def test_resource_retries_on_transient_error():
    """Resource should retry once on transient connection error."""
    session = AsyncMock()
    result = _make_resource_result("data")
    exc = _FakeClosedResourceError("gone")
    session.read_resource = AsyncMock(side_effect=[exc, result])

    wrapper = MCPResourceWrapper(session, "test_server", _make_resource_def())

    with patch("nanobot.agent.tools.mcp.asyncio.sleep", new_callable=AsyncMock):
        output = await wrapper.execute()

    assert output == "data"
    assert session.read_resource.call_count == 2


@pytest.mark.asyncio
async def test_resource_fails_after_retry_exhausted():
    """Resource should fail with retry message when both attempts fail."""
    session = AsyncMock()
    exc = _FakeClosedResourceError("dead")
    session.read_resource = AsyncMock(side_effect=[exc, exc])

    wrapper = MCPResourceWrapper(session, "test_server", _make_resource_def())

    with patch("nanobot.agent.tools.mcp.asyncio.sleep", new_callable=AsyncMock):
        output = await wrapper.execute()

    assert "failed after retry" in output
    assert session.read_resource.call_count == 2


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
# MCPPromptWrapper retry behaviour
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
async def test_prompt_retries_on_transient_error():
    """Prompt should retry once on transient connection error."""
    session = AsyncMock()
    result = _make_prompt_result("prompt text")
    exc = _FakeClosedResourceError("gone")
    session.get_prompt = AsyncMock(side_effect=[exc, result])

    wrapper = MCPPromptWrapper(session, "test_server", _make_prompt_def())

    with patch("nanobot.agent.tools.mcp.asyncio.sleep", new_callable=AsyncMock):
        output = await wrapper.execute()

    assert output == "prompt text"
    assert session.get_prompt.call_count == 2


@pytest.mark.asyncio
async def test_prompt_fails_after_retry_exhausted():
    """Prompt should fail with retry message when both attempts fail."""
    session = AsyncMock()
    exc = _FakeClosedResourceError("dead")
    session.get_prompt = AsyncMock(side_effect=[exc, exc])

    wrapper = MCPPromptWrapper(session, "test_server", _make_prompt_def())

    with patch("nanobot.agent.tools.mcp.asyncio.sleep", new_callable=AsyncMock):
        output = await wrapper.execute()

    assert "failed after retry" in output
    assert session.get_prompt.call_count == 2


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
