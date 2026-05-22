"""Tests for provider progress delta routing in the shared runner."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.runner import AgentRunner, AgentRunSpec
from nanobot.config.schema import AgentDefaults
from nanobot.providers.base import LLMResponse, ToolCallRequest

_MAX_TOOL_RESULT_CHARS = AgentDefaults().max_tool_result_chars


@pytest.mark.asyncio
async def test_runner_can_disable_provider_progress_delta_streaming():
    """AgentLoop disables token progress streaming for non-streaming channels."""
    provider = MagicMock()
    provider.supports_progress_deltas = True
    provider.chat_with_retry = AsyncMock(
        return_value=LLMResponse(content="done", tool_calls=[], usage={})
    )
    provider.chat_stream_with_retry = AsyncMock()
    tools = MagicMock()
    tools.get_definitions.return_value = []
    progress_cb = AsyncMock()

    runner = AgentRunner(provider)
    result = await runner.run(AgentRunSpec(
        initial_messages=[
            {"role": "system", "content": "system"},
            {"role": "user", "content": "hi"},
        ],
        tools=tools,
        model="test-model",
        max_iterations=1,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        progress_callback=progress_cb,
        stream_progress_deltas=False,
    ))

    assert result.final_content == "done"
    provider.chat_with_retry.assert_awaited_once()
    provider.chat_stream_with_retry.assert_not_awaited()
    progress_cb.assert_not_awaited()


@pytest.mark.asyncio
async def test_runner_streams_provider_progress_deltas_by_default():
    """Direct runner users keep the existing opt-in provider progress behavior."""
    provider = MagicMock()
    provider.supports_progress_deltas = True

    async def chat_stream_with_retry(*, on_content_delta, **kwargs):
        await on_content_delta("he")
        await on_content_delta("llo")
        return LLMResponse(content="hello", tool_calls=[], usage={})

    provider.chat_stream_with_retry = chat_stream_with_retry
    provider.chat_with_retry = AsyncMock()
    tools = MagicMock()
    tools.get_definitions.return_value = []
    progress_cb = AsyncMock()

    runner = AgentRunner(provider)
    result = await runner.run(AgentRunSpec(
        initial_messages=[
            {"role": "system", "content": "system"},
            {"role": "user", "content": "hi"},
        ],
        tools=tools,
        model="test-model",
        max_iterations=1,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        progress_callback=progress_cb,
    ))

    assert result.final_content == "hello"
    assert [call.args[0] for call in progress_cb.await_args_list] == ["he", "llo"]
    provider.chat_with_retry.assert_not_awaited()


@pytest.mark.asyncio
async def test_runner_streams_live_write_file_activity_from_tool_argument_deltas(tmp_path):
    provider = MagicMock()
    provider.supports_progress_deltas = True
    call_count = 0
    progress_events: list[dict] = []

    async def progress_cb(content, *, file_edit_events=None, **kwargs):
        if file_edit_events:
            progress_events.extend(file_edit_events)

    class Tools:
        def get_definitions(self):
            return [{"type": "function", "function": {"name": "write_file"}}]

        def get(self, name):
            return None

        async def execute(self, name, params):
            assert name == "write_file"
            assert any(event["approximate"] and event["added"] == 24 for event in progress_events)
            target = tmp_path / params["path"]
            target.write_text(params["content"], encoding="utf-8")
            return "ok"

    async def chat_stream_with_retry(*, on_tool_call_delta=None, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            assert on_tool_call_delta is not None
            await on_tool_call_delta({
                "index": 0,
                "call_id": "call-write",
                "name": "write_file",
                "arguments_delta": '{"path":"big.txt","content":"',
            })
            await on_tool_call_delta({"index": 0, "arguments_delta": "line\\n" * 24})
            return LLMResponse(
                content=None,
                tool_calls=[
                    ToolCallRequest(
                        id="call-write",
                        name="write_file",
                        arguments={"path": "big.txt", "content": "line\n" * 24},
                    )
                ],
                usage={},
            )
        return LLMResponse(content="done", tool_calls=[], usage={})

    provider.chat_stream_with_retry = chat_stream_with_retry
    provider.chat_with_retry = AsyncMock()

    runner = AgentRunner(provider)
    result = await runner.run(AgentRunSpec(
        initial_messages=[{"role": "user", "content": "write a large file"}],
        tools=Tools(),
        model="test-model",
        max_iterations=2,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        progress_callback=progress_cb,
        workspace=tmp_path,
    ))

    assert result.final_content == "done"
    assert any(event["approximate"] and event["added"] == 24 for event in progress_events)
    assert any(
        not event["approximate"] and event["phase"] == "end" and event["added"] == 24
        for event in progress_events
    )
    provider.chat_with_retry.assert_not_awaited()


@pytest.mark.asyncio
async def test_runner_streams_live_edit_file_activity_from_tool_argument_deltas(tmp_path):
    provider = MagicMock()
    provider.supports_progress_deltas = True
    call_count = 0
    progress_events: list[dict] = []
    target = tmp_path / "notes.txt"
    target.write_text("old\nkeep\n", encoding="utf-8")

    async def progress_cb(content, *, file_edit_events=None, **kwargs):
        if file_edit_events:
            progress_events.extend(file_edit_events)

    class Tools:
        def get_definitions(self):
            return [{"type": "function", "function": {"name": "edit_file"}}]

        def get(self, name):
            return None

        async def execute(self, name, params):
            assert name == "edit_file"
            assert any(
                event["tool"] == "edit_file"
                and event["approximate"]
                and event["added"] == 3
                and event["deleted"] == 2
                for event in progress_events
            )
            target.write_text(params["new_text"], encoding="utf-8")
            return "ok"

    async def chat_stream_with_retry(*, on_tool_call_delta=None, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            assert on_tool_call_delta is not None
            await on_tool_call_delta({
                "index": 0,
                "call_id": "call-edit",
                "name": "edit_file",
                "arguments_delta": (
                    '{"path":"notes.txt","old_text":"old\\nkeep\\n","new_text":"'
                ),
            })
            await on_tool_call_delta({
                "index": 0,
                "arguments_delta": "new\\nkeep\\nextra\\n",
            })
            await on_tool_call_delta({"index": 0, "arguments_delta": '"}'})
            return LLMResponse(
                content=None,
                tool_calls=[
                    ToolCallRequest(
                        id="call-edit",
                        name="edit_file",
                        arguments={
                            "path": "notes.txt",
                            "old_text": "old\nkeep\n",
                            "new_text": "new\nkeep\nextra\n",
                        },
                    )
                ],
                usage={},
            )
        return LLMResponse(content="done", tool_calls=[], usage={})

    provider.chat_stream_with_retry = chat_stream_with_retry
    provider.chat_with_retry = AsyncMock()

    runner = AgentRunner(provider)
    result = await runner.run(AgentRunSpec(
        initial_messages=[{"role": "user", "content": "edit a file"}],
        tools=Tools(),
        model="test-model",
        max_iterations=2,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        progress_callback=progress_cb,
        workspace=tmp_path,
    ))

    assert result.final_content == "done"
    assert any(
        event["tool"] == "edit_file"
        and event["approximate"]
        and event["added"] == 3
        and event["deleted"] == 2
        for event in progress_events
    )
    assert any(
        event["tool"] == "edit_file"
        and not event["approximate"]
        and event["phase"] == "end"
        and event["added"] == 2
        and event["deleted"] == 1
        for event in progress_events
    )
    provider.chat_with_retry.assert_not_awaited()


@pytest.mark.asyncio
async def test_runner_marks_unfinished_live_write_file_activity_failed(tmp_path):
    provider = MagicMock()
    provider.supports_progress_deltas = True
    progress_events: list[dict] = []

    async def progress_cb(content, *, file_edit_events=None, **kwargs):
        if file_edit_events:
            progress_events.extend(file_edit_events)

    async def chat_stream_with_retry(*, on_tool_call_delta=None, **kwargs):
        assert on_tool_call_delta is not None
        await on_tool_call_delta({
            "index": 0,
            "call_id": "call-write",
            "name": "write_file",
            "arguments_delta": '{"path":"aborted.txt","content":"partial\\n',
        })
        return LLMResponse(content="stopped", tool_calls=[], finish_reason="stop", usage={})

    provider.chat_stream_with_retry = chat_stream_with_retry
    provider.chat_with_retry = AsyncMock()
    tools = MagicMock()
    tools.get_definitions.return_value = [{"type": "function", "function": {"name": "write_file"}}]
    tools.get.return_value = None

    runner = AgentRunner(provider)
    result = await runner.run(AgentRunSpec(
        initial_messages=[{"role": "user", "content": "write a large file"}],
        tools=tools,
        model="test-model",
        max_iterations=1,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        progress_callback=progress_cb,
        workspace=tmp_path,
    ))

    assert result.final_content == "stopped"
    assert progress_events[-1]["path"] == "aborted.txt"
    assert progress_events[-1]["phase"] == "error"
    assert progress_events[-1]["status"] == "error"
    provider.chat_with_retry.assert_not_awaited()
