import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from loguru import logger
from mcp import types as mcp_types
from mcp.shared.exceptions import McpError
from mcp.types import ErrorData

from agent.runner_helpers import make_run_spec
from nanobot.agent.hook import AgentHook, AgentHookContext
from nanobot.agent.runner import AgentRunner
from nanobot.agent.tools.context import RequestContext, request_context
from nanobot.agent.tools.execution import execute_tool_calls
from nanobot.agent.tools.mcp import (
    MCPPromptWrapper,
    MCPResourceWrapper,
    MCPToolWrapper,
    _is_session_terminated,
    _is_transient,
)
from nanobot.agent.tools.registry import (
    ToolRegistry,
    is_tool_error_result,
    with_tool_error_hint,
)
from nanobot.config.schema import AgentDefaults
from nanobot.providers.base import LLMResponse, ToolCallRequest


class _FakeClosedResourceError(Exception):
    pass


_FakeClosedResourceError.__name__ = "ClosedResourceError"


class _FakeEndOfStreamError(Exception):
    pass


_FakeEndOfStreamError.__name__ = "EndOfStream"


def _session_terminated_error() -> McpError:
    return McpError(ErrorData(code=-32000, message="Session terminated"))


def _connection_closed_error() -> McpError:
    return McpError(ErrorData(code=-32000, message="Connection closed"))


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


def test_is_session_terminated_recognizes_mcp_error():
    assert _is_session_terminated(_session_terminated_error())


def test_is_session_terminated_recognizes_connection_closed_mcp_error():
    assert _is_session_terminated(_connection_closed_error())


def _make_tool_def(name="test_tool"):
    return SimpleNamespace(
        name=name,
        description="A read-only test tool",
        inputSchema={"type": "object", "properties": {}},
        annotations=mcp_types.ToolAnnotations(readOnlyHint=True),
    )


def _make_tool_result(text):
    """Build a mock tool result with proper MCP TextContent."""
    return SimpleNamespace(content=[mcp_types.TextContent(type="text", text=text)])


@pytest.mark.asyncio
async def test_tool_retries_on_transient_error():
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
    session = AsyncMock()
    exc1 = _FakeClosedResourceError("still dead")
    exc2 = _FakeClosedResourceError("still dead again")
    session.call_tool = AsyncMock(side_effect=[exc1, exc2])

    wrapper = MCPToolWrapper(session, "test_server", _make_tool_def(), tool_timeout=5)

    with patch("nanobot.agent.tools.mcp.asyncio.sleep", new_callable=AsyncMock):
        output = await wrapper.execute()

    assert "failed after retry" in output
    assert "ClosedResourceError" in output
    assert is_tool_error_result(output)
    assert session.call_tool.call_count == 2


@pytest.mark.asyncio
async def test_tool_no_retry_on_non_transient_error():
    session = AsyncMock()
    session.call_tool = AsyncMock(side_effect=ValueError("bad input"))

    wrapper = MCPToolWrapper(session, "test_server", _make_tool_def(), tool_timeout=5)
    output = await wrapper.execute()

    assert "ValueError" in output
    assert "retry" not in output
    assert session.call_tool.call_count == 1


@pytest.mark.asyncio
async def test_tool_no_retry_on_timeout():
    session = AsyncMock()
    session.call_tool = AsyncMock(side_effect=asyncio.TimeoutError())

    wrapper = MCPToolWrapper(session, "test_server", _make_tool_def(), tool_timeout=5)
    output = await wrapper.execute()

    assert "timed out" in output
    assert session.call_tool.call_count == 1


@pytest.mark.asyncio
async def test_tool_success_on_first_try_no_retry():
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
    session = AsyncMock()
    result = _make_tool_result("back")
    session.call_tool = AsyncMock(side_effect=[_FakeEndOfStreamError("eof"), result])

    wrapper = MCPToolWrapper(session, "test_server", _make_tool_def(), tool_timeout=5)

    with patch("nanobot.agent.tools.mcp.asyncio.sleep", new_callable=AsyncMock):
        output = await wrapper.execute()

    assert output == "back"
    assert session.call_tool.call_count == 2


@pytest.mark.asyncio
async def test_tool_reconnects_on_transient_failure():
    old_session = AsyncMock()
    old_session.call_tool = AsyncMock(side_effect=_FakeClosedResourceError("closed"))
    new_session = AsyncMock()
    new_session.call_tool = AsyncMock(return_value=_make_tool_result("fresh"))

    wrapper = MCPToolWrapper(old_session, "test_server", _make_tool_def(), tool_timeout=5)
    replacement = MCPToolWrapper(new_session, "test_server", _make_tool_def(), tool_timeout=5)

    async def reconnect(server_name: str, tool_name: str, stale_tool):
        assert server_name == "test_server"
        assert tool_name == "mcp_test_server_test_tool"
        assert stale_tool is wrapper
        return replacement

    wrapper.set_reconnect_handler(reconnect)

    with patch("nanobot.agent.tools.mcp.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        output = await wrapper.execute(foo="bar")

    assert output == "fresh"
    assert old_session.call_tool.call_count == 1
    assert new_session.call_tool.call_count == 1
    mock_sleep.assert_not_called()


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
    session = AsyncMock()
    session.read_resource = AsyncMock(side_effect=RuntimeError("bad"))

    wrapper = MCPResourceWrapper(session, "test_server", _make_resource_def())
    output = await wrapper.execute()

    assert "RuntimeError" in output
    assert session.read_resource.call_count == 1


@pytest.mark.asyncio
async def test_resource_reconnects_on_session_terminated():
    old_session = AsyncMock()
    old_session.read_resource = AsyncMock(side_effect=_session_terminated_error())
    new_session = AsyncMock()
    new_session.read_resource = AsyncMock(return_value=_make_resource_result("fresh"))

    wrapper = MCPResourceWrapper(old_session, "test_server", _make_resource_def())
    replacement = MCPResourceWrapper(new_session, "test_server", _make_resource_def())

    async def reconnect(server_name: str, tool_name: str, stale_tool):
        assert server_name == "test_server"
        assert tool_name == "mcp_test_server_resource_test_resource"
        assert stale_tool is wrapper
        return replacement

    wrapper.set_reconnect_handler(reconnect)

    output = await wrapper.execute()

    assert output == "fresh"
    assert old_session.read_resource.call_count == 1
    assert new_session.read_resource.call_count == 1


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
    session = AsyncMock()
    session.get_prompt = AsyncMock(side_effect=RuntimeError("bad"))

    wrapper = MCPPromptWrapper(session, "test_server", _make_prompt_def())
    output = await wrapper.execute()

    assert "RuntimeError" in output
    assert session.get_prompt.call_count == 1


@pytest.mark.asyncio
async def test_prompt_reconnects_on_session_terminated():
    old_session = AsyncMock()
    old_session.get_prompt = AsyncMock(side_effect=_session_terminated_error())
    new_session = AsyncMock()
    new_session.get_prompt = AsyncMock(return_value=_make_prompt_result("fresh prompt"))

    wrapper = MCPPromptWrapper(old_session, "test_server", _make_prompt_def())
    replacement = MCPPromptWrapper(new_session, "test_server", _make_prompt_def())

    async def reconnect(server_name: str, tool_name: str, stale_tool):
        assert server_name == "test_server"
        assert tool_name == "mcp_test_server_prompt_test_prompt"
        assert stale_tool is wrapper
        return replacement

    wrapper.set_reconnect_handler(reconnect)

    output = await wrapper.execute()

    assert output == "fresh prompt"
    assert old_session.get_prompt.call_count == 1
    assert new_session.get_prompt.call_count == 1


@pytest.mark.asyncio
async def test_prompt_reconnects_on_connection_closed_exception():
    old_session = AsyncMock()
    old_session.get_prompt = AsyncMock(side_effect=RuntimeError("Connection closed"))
    new_session = AsyncMock()
    new_session.get_prompt = AsyncMock(return_value=_make_prompt_result("fresh prompt"))

    wrapper = MCPPromptWrapper(old_session, "test_server", _make_prompt_def())
    replacement = MCPPromptWrapper(new_session, "test_server", _make_prompt_def())

    async def reconnect(server_name: str, tool_name: str, stale_tool):
        assert server_name == "test_server"
        assert tool_name == "mcp_test_server_prompt_test_prompt"
        assert stale_tool is wrapper
        return replacement

    wrapper.set_reconnect_handler(reconnect)

    output = await wrapper.execute()

    assert output == "fresh prompt"
    assert old_session.get_prompt.call_count == 1
    assert new_session.get_prompt.call_count == 1


@pytest.mark.parametrize("fresh_annotations", [
    mcp_types.ToolAnnotations(idempotentHint=True), None,
    mcp_types.ToolAnnotations(readOnlyHint=False, idempotentHint=False),
], ids=["still-idempotent", "unknown", "non-idempotent"])
async def test_tool_refresh_rechecks_replay_contract_and_keeps_retry_budget(fresh_annotations):
    old, fresh = AsyncMock(), AsyncMock()
    old.call_tool.side_effect = ConnectionResetError("old")
    effects = []

    async def submit_then_lose_response(name, arguments):
        effects.append((name, arguments))
        if len(effects) == 1:
            raise ConnectionResetError("fresh response lost after commit")
        return _make_tool_result("ok")

    fresh.call_tool.side_effect = submit_then_lose_response
    definition = mcp_types.Tool(
        name="test_tool", inputSchema={"type": "object"},
        annotations=mcp_types.ToolAnnotations(idempotentHint=True),
    )
    wrapper = MCPToolWrapper(old, "srv", definition)
    replacement = MCPToolWrapper(fresh, "srv", definition.model_copy(update={"annotations": fresh_annotations}))
    reconnect = AsyncMock(return_value=replacement)
    wrapper.set_reconnect_handler(reconnect)

    with patch("nanobot.agent.tools.mcp.asyncio.sleep", new_callable=AsyncMock) as sleep:
        output = await wrapper.execute(value="unchanged")
        if fresh_annotations is not None and fresh_annotations.idempotentHint:
            assert output == "ok"
            assert effects == [("test_tool", {"value": "unchanged"})] * 2
            sleep.assert_awaited_once_with(1)
        else:
            assert is_tool_error_result(output)
            assert "outcome is unknown" in output
            fresh.call_tool.assert_not_awaited()
            assert effects == []
            sleep.assert_not_awaited()
            # A later authorized operation uses the new contract too: its lost
            # response must not acquire the old wrapper's replay permission.
            later = await wrapper.execute(value="new input")
            assert is_tool_error_result(later)
            assert "outcome is unknown" in later
            assert effects == [("test_tool", {"value": "new input"})]
            fresh.call_tool.assert_awaited_once()
            sleep.assert_not_awaited()

    old.call_tool.assert_awaited_once_with("test_tool", arguments={"value": "unchanged"})
    reconnect.assert_awaited_once_with("srv", wrapper.name, wrapper)


async def test_tool_later_refresh_does_not_reset_transient_budget():
    old, fresh = AsyncMock(), AsyncMock()
    old.call_tool.side_effect = [ConnectionResetError("first"), _session_terminated_error()]
    fresh.call_tool.side_effect = ConnectionResetError("last")
    wrapper = MCPToolWrapper(old, "srv", _make_tool_def())
    replacement = MCPToolWrapper(fresh, "srv", _make_tool_def())
    reconnect = AsyncMock(side_effect=[None, replacement])
    wrapper.set_reconnect_handler(reconnect)

    with patch("nanobot.agent.tools.mcp.asyncio.sleep", new_callable=AsyncMock) as sleep:
        output = await wrapper.execute()

    assert output == "(MCP tool call failed after retry: ConnectionResetError)"
    assert is_tool_error_result(output)
    assert (old.call_tool.await_count, fresh.call_tool.await_count) == (2, 1)
    assert reconnect.await_count == 2
    sleep.assert_awaited_once_with(1)


@pytest.mark.parametrize("phase", ["refresh", "backoff"])
async def test_tool_real_cancellation_during_recovery_propagates(phase):
    entered, finished = asyncio.Event(), asyncio.Event()

    async def block(*_args):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            finished.set()

    session = AsyncMock()
    session.call_tool.side_effect = ConnectionResetError("gone")
    wrapper = MCPToolWrapper(session, "srv", _make_tool_def())
    if phase == "refresh":
        wrapper.set_reconnect_handler(block)
    with patch("nanobot.agent.tools.mcp.asyncio.sleep", side_effect=block):
        task = asyncio.create_task(wrapper.execute())
        try:
            await asyncio.wait_for(entered.wait(), timeout=2)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
    assert task.cancelled() and finished.is_set()
    session.call_tool.assert_awaited_once()


async def test_tool_reconnect_failure_is_not_a_retryable_request_failure():
    session = AsyncMock()
    session.call_tool.side_effect = ConnectionResetError("request")
    wrapper = MCPToolWrapper(session, "srv", _make_tool_def())
    failure = ConnectionResetError("refresh")
    reconnect = AsyncMock(side_effect=failure)
    wrapper.set_reconnect_handler(reconnect)
    with patch("nanobot.agent.tools.mcp.asyncio.sleep", new_callable=AsyncMock) as sleep:
        with pytest.raises(ConnectionResetError) as raised:
            await wrapper.execute()
    assert raised.value is failure
    session.call_tool.assert_awaited_once()
    reconnect.assert_awaited_once()
    sleep.assert_not_awaited()


async def test_tool_transient_render_failure_cannot_replay_a_successful_request():
    session = AsyncMock()
    session.call_tool.return_value = _make_tool_result("ok")
    wrapper = MCPToolWrapper(session, "srv", _make_tool_def())
    reconnect = AsyncMock()
    wrapper.set_reconnect_handler(reconnect)
    with (
        patch.object(wrapper, "_render_call_result", side_effect=ConnectionResetError("Session terminated")),
        patch("nanobot.agent.tools.mcp.asyncio.sleep", new_callable=AsyncMock) as sleep,
    ):
        output = await wrapper.execute()
    assert output == "(MCP tool returned malformed content: ConnectionResetError)"
    assert is_tool_error_result(output)
    session.call_tool.assert_awaited_once()
    reconnect.assert_not_awaited()
    sleep.assert_not_awaited()


@pytest.mark.parametrize("kind", ["tool", "prompt"])
async def test_request_error_logs_hide_content_and_prompt_retains_error_detail(kind):
    session = AsyncMock()
    if kind == "prompt":
        session.get_prompt.side_effect = McpError(ErrorData(code=-32602, message="private-request-content"))
        wrapper = MCPPromptWrapper(session, "srv", _make_prompt_def())
        old = AsyncMock()
        old.get_prompt.side_effect = _session_terminated_error()
        stale = MCPPromptWrapper(old, "srv", _make_prompt_def())
        stale.set_reconnect_handler(AsyncMock(return_value=wrapper))
        wrapper = stale
        expected = "(MCP prompt call failed: private-request-content [code -32602])"
    else:
        session.call_tool.side_effect = ValueError("private-request-content")
        wrapper = MCPToolWrapper(session, "srv", _make_tool_def())
        expected = "(MCP tool call failed: ValueError)"
    records = []
    sink = logger.add(lambda message: records.append(message.record), level="DEBUG")
    try:
        with request_context(RequestContext(channel="test", chat_id="test", log_content=False)):
            output = await wrapper.execute()
    finally:
        logger.remove(sink)
    assert output == expected
    assert is_tool_error_result(output)
    error = next(record for record in records if record["level"].name == "ERROR")
    assert "[content hidden]" in error["message"]
    assert error["exception"] is None
    assert all("private-request-content" not in record["message"] for record in records)


class _RecordingToolHook(AgentHook):
    def __init__(self):
        self.errors = []
        self.successes = []

    async def on_execute_tool_error(self, context, tool_call, tool, params, error):
        self.errors.append(error)

    async def after_execute_tool(self, context, tool_call, tool, params, result):
        self.successes.append(result)


async def _run_mcp_call(registry, call, hook):
    provider = MagicMock()
    provider.chat_stream_with_retry = AsyncMock(side_effect=[
        LLMResponse(content=None, tool_calls=[call]),
        LLMResponse(content="done"),
    ])
    return await AgentRunner().run(make_run_spec(
        provider, tools=registry, model="test-model", max_iterations=2,
        initial_messages=[{"role": "user", "content": "run the MCP operation"}],
        max_tool_result_chars=AgentDefaults().max_tool_result_chars,
        hook=hook,
    ))


@pytest.mark.parametrize("annotations", [None, mcp_types.ToolAnnotations(
    readOnlyHint=False, idempotentHint=False, destructiveHint=False,
)], ids=["unknown", "non-idempotent-additive"])
async def test_submitted_tool_transport_loss_is_unknown_not_replayed(annotations):
    effects = []
    disconnected = False
    old, fresh = AsyncMock(), AsyncMock()

    async def ping():
        if disconnected:
            raise _connection_closed_error()

    async def submit_then_lose_response(name, arguments):
        nonlocal disconnected
        effects.append((name, arguments))
        disconnected = True
        raise McpError(ErrorData(code=-32000, message="Connection closed: private-submission"))

    async def submit(name, arguments):
        effects.append((name, arguments))
        return _make_tool_result("created")

    old.send_ping.side_effect = ping
    old.call_tool.side_effect = submit_then_lose_response
    fresh.call_tool.side_effect = submit
    definition = mcp_types.Tool(name="create", inputSchema={"type": "object"}, annotations=annotations)
    wrapper = MCPToolWrapper(old, "srv", definition)
    replacement = MCPToolWrapper(fresh, "srv", definition)
    reconnect = AsyncMock(return_value=replacement)
    wrapper.set_reconnect_handler(reconnect)
    registry = ToolRegistry()
    registry.register(wrapper)
    hook = _RecordingToolHook()
    records = []
    sink = logger.add(lambda message: records.append(message.record), level="DEBUG")
    try:
        with request_context(RequestContext(channel="test", chat_id="test", log_content=False)):
            result = await _run_mcp_call(
                registry, ToolCallRequest(id="create-1", name=wrapper.name, arguments={"title": "first"}), hook,
            )
    finally:
        logger.remove(sink)

    assert records and all("private-submission" not in record["message"] for record in records)
    assert all(record["exception"] is None for record in records)
    assert effects == [("create", {"title": "first"})]
    assert result.tool_events[0]["status"] == "error"
    assert result.tools_used == []
    assert len(hook.errors) == 1 and not hook.successes
    assert is_tool_error_result(hook.errors[0])
    assert "outcome is unknown" in hook.errors[0]
    assert "duplicate side effects" in hook.errors[0]
    assert "not replayed" in hook.errors[0]
    reconnect.assert_not_awaited()
    fresh.call_tool.assert_not_awaited()

    # A later user-authorized call can repair the connection before submitting,
    # without replaying the first call or inheriting its outcome/retry state.
    assert await registry.execute(wrapper.name, {"title": "second"}) == "created"
    assert effects == [("create", {"title": "first"}), ("create", {"title": "second"})]
    reconnect.assert_awaited_once()
    old.call_tool.assert_awaited_once()
    fresh.call_tool.assert_awaited_once_with("create", arguments={"title": "second"})


async def test_explicitly_idempotent_tool_can_recover_with_the_same_arguments():
    records = {}
    submissions = []

    async def set_record(name, arguments):
        submissions.append((name, arguments.copy()))
        records[arguments["id"]] = arguments["value"]
        if len(submissions) == 1:
            raise ConnectionResetError("response lost after commit")
        return _make_tool_result("saved")

    session = AsyncMock()
    session.call_tool.side_effect = set_record
    definition = mcp_types.Tool(
        name="set_record", inputSchema={"type": "object"},
        annotations=mcp_types.ToolAnnotations(readOnlyHint=False, idempotentHint=True),
    )
    wrapper = MCPToolWrapper(session, "srv", definition)
    registry = ToolRegistry()
    registry.register(wrapper)
    with patch("nanobot.agent.tools.mcp.asyncio.sleep", new_callable=AsyncMock) as sleep:
        output = await registry.execute(wrapper.name, {"id": "one", "value": "saved"})
    assert output == "saved"
    assert not is_tool_error_result(output)
    assert records == {"one": "saved"}
    assert submissions == [("set_record", {"id": "one", "value": "saved"})] * 2
    sleep.assert_awaited_once_with(1)


@pytest.mark.parametrize("case", [
    "resource_timeout", "prompt_mcp_error", "resource_exhausted", "prompt_exhausted",
    "resource_success", "prompt_success",
])
async def test_resource_prompt_results_keep_runtime_classification(case):
    session = AsyncMock()
    is_resource = case.startswith("resource")
    if is_resource:
        wrapper = MCPResourceWrapper(session, "srv", _make_resource_def(), resource_timeout=5)
        request = session.read_resource
    else:
        wrapper = MCPPromptWrapper(session, "srv", _make_prompt_def(), prompt_timeout=5)
        request = session.get_prompt
    failed = not case.endswith("success")
    if case.endswith("timeout"):
        request.side_effect = asyncio.TimeoutError()
        expected = "(MCP resource read timed out after 5s)"
    elif case.endswith("mcp_error"):
        request.side_effect = McpError(ErrorData(code=-32602, message="prompt missing"))
        expected = "(MCP prompt call failed: prompt missing [code -32602])"
    elif case.endswith("exhausted"):
        request.side_effect = ConnectionResetError("lost")
        operation = "resource read" if is_resource else "prompt call"
        expected = f"(MCP {operation} failed after retry: ConnectionResetError)"
    else:
        expected = "Error: is a valid example in this document"
        request.return_value = (
            _make_resource_result(expected) if is_resource else _make_prompt_result(expected)
        )
    registry = ToolRegistry()
    registry.register(wrapper)
    call = ToolCallRequest(id="read-1", name=wrapper.name, arguments={})
    with patch("nanobot.agent.tools.mcp.asyncio.sleep", new_callable=AsyncMock):
        direct = await registry.execute(wrapper.name, {})
        assert is_tool_error_result(direct) is failed
        assert direct == (with_tool_error_hint(expected) if failed else expected)

        hook = _RecordingToolHook()
        settled = []
        await execute_tool_calls(
            registry, [call], concurrent=False, external_lookup_counts={},
            workspace_violation_counts={}, hook=hook,
            context=AgentHookContext(iteration=0, messages=[]),
            on_settled=AsyncMock(side_effect=settled.extend),
        )
        [completed] = settled
        assert completed.event["status"] == ("error" if failed else "ok")
        assert expected in completed.result
        assert hook.errors == ([expected] if failed else [])
        assert hook.successes == ([] if failed else [expected])

        runner_hook = _RecordingToolHook()
        result = await _run_mcp_call(registry, call, runner_hook)
    assert result.tool_events[0]["status"] == ("error" if failed else "ok")
    assert result.tools_used == ([] if failed else [wrapper.name])
    assert runner_hook.errors == ([expected] if failed else [])
    assert runner_hook.successes == ([] if failed else [expected])
    if failed:
        assert is_tool_error_result(runner_hook.errors[0])
    assert expected in next(msg["content"] for msg in result.messages if msg["role"] == "tool")


async def test_unknown_tool_without_reconnect_does_not_retry_after_side_effect():
    effects = []

    async def submit_then_disconnect(name, arguments):
        effects.append((name, arguments))
        raise ConnectionResetError("response lost")

    session = AsyncMock()
    session.call_tool.side_effect = submit_then_disconnect
    wrapper = MCPToolWrapper(session, "srv", mcp_types.Tool(name="send", inputSchema={"type": "object"}))
    registry = ToolRegistry()
    registry.register(wrapper)
    with patch("nanobot.agent.tools.mcp.asyncio.sleep", new_callable=AsyncMock) as sleep:
        output = await registry.execute(wrapper.name, {"message": "hello"})
    assert effects == [("send", {"message": "hello"})]
    assert is_tool_error_result(output)
    assert "outcome is unknown" in output
    sleep.assert_not_awaited()


@pytest.mark.parametrize("kind", ["resource", "prompt"])
async def test_resource_prompt_external_cancellation_propagates_without_hooks(kind):
    entered = asyncio.Event()

    async def block(*args, **kwargs):
        entered.set()
        await asyncio.Event().wait()

    session = AsyncMock()
    if kind == "resource":
        session.read_resource.side_effect = block
        wrapper = MCPResourceWrapper(session, "srv", _make_resource_def())
        request = session.read_resource
    else:
        session.get_prompt.side_effect = block
        wrapper = MCPPromptWrapper(session, "srv", _make_prompt_def())
        request = session.get_prompt
    registry = ToolRegistry()
    registry.register(wrapper)
    hook = _RecordingToolHook()
    task = asyncio.create_task(execute_tool_calls(
        registry, [ToolCallRequest(id="read-1", name=wrapper.name, arguments={})],
        concurrent=False, external_lookup_counts={}, workspace_violation_counts={},
        hook=hook, context=AgentHookContext(iteration=0, messages=[]),
    ))
    try:
        await asyncio.wait_for(entered.wait(), timeout=2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    request.assert_awaited_once()
    assert not hook.errors and not hook.successes


@pytest.mark.parametrize("cancel", [False, True], ids=["timeout", "task-cancellation"])
@pytest.mark.parametrize("submitted", [False, True], ids=["preflight", "submitted"])
async def test_non_replayable_tool_timeout_and_cancellation_do_not_repeat(cancel, submitted):
    entered = asyncio.Event()
    effects = []

    async def block(*args, **kwargs):
        if submitted:
            effects.append("committed before response loss")
        entered.set()
        await asyncio.Event().wait()

    session = AsyncMock()
    if submitted:
        session.call_tool.side_effect = block
    else:
        session.send_ping.side_effect = block
    wrapper = MCPToolWrapper(
        session, "srv", mcp_types.Tool(name="send", inputSchema={"type": "object"}),
        tool_timeout=5 if cancel else 0.01,
    )
    reconnect = AsyncMock()
    wrapper.set_reconnect_handler(reconnect)
    task = asyncio.create_task(wrapper.execute())
    try:
        await asyncio.wait_for(entered.wait(), timeout=2)
        if cancel:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            result = await asyncio.wait_for(task, timeout=2)
            assert is_tool_error_result(result)
            assert "timed out after 0.01s" in result
            assert ("outcome is unknown" in result) is submitted
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    session.send_ping.assert_awaited_once()
    assert session.call_tool.await_count == int(submitted)
    assert effects == (["committed before response loss"] if submitted else [])
    reconnect.assert_not_awaited()
