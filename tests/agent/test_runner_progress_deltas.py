"""Tests for provider progress delta routing in the shared runner."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.runner_helpers import make_run_spec
from nanobot.agent.hooks import FileEditActivityHook
from nanobot.agent.runner import AgentRunner
from nanobot.agent.tools.filesystem import EditFileTool, WriteFileTool
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

    runner = AgentRunner()
    result = await runner.run(make_run_spec(provider,
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

    runner = AgentRunner()
    result = await runner.run(make_run_spec(provider,
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
async def test_runner_emits_write_file_diff_from_tool_execution_snapshots(tmp_path):
    provider = MagicMock()
    provider.supports_progress_deltas = True
    call_count = 0
    progress_events: list[dict] = []
    (tmp_path / "big.txt").write_text("old\n", encoding="utf-8")

    async def progress_cb(content, *, file_edit_events=None, **kwargs):
        if file_edit_events:
            progress_events.extend(file_edit_events)

    tool = WriteFileTool(workspace=tmp_path)

    class Tools:
        def get_definitions(self):
            return [{"type": "function", "function": {"name": "write_file"}}]

        def prepare_call(self, name, params):
            return tool, params, None

    async def chat_stream_with_retry(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
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
    tools = Tools()

    runner = AgentRunner()
    result = await runner.run(make_run_spec(provider,
        initial_messages=[{"role": "user", "content": "write a large file"}],
        tools=tools,
        model="test-model",
        max_iterations=2,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        progress_callback=progress_cb,
        workspace=tmp_path,
        hook=FileEditActivityHook(on_progress=progress_cb, workspace=tmp_path),
    ))

    assert result.final_content == "done"
    assert progress_events[0]["phase"] == "start"
    assert progress_events[0]["added"] == 0
    assert progress_events[0]["deleted"] == 0
    assert any(
        not event["approximate"]
        and event["phase"] == "end"
        and event["added"] == 24
        and event["deleted"] == 1
        and event["diff"]["format"] == "unified"
        for event in progress_events
    )
    provider.chat_with_retry.assert_not_awaited()


@pytest.mark.asyncio
async def test_runner_emits_edit_file_diff_from_tool_execution_snapshots(tmp_path):
    provider = MagicMock()
    provider.supports_progress_deltas = True
    call_count = 0
    progress_events: list[dict] = []
    target = tmp_path / "notes.txt"
    target.write_text("old\nkeep\n", encoding="utf-8")

    async def progress_cb(content, *, file_edit_events=None, **kwargs):
        if file_edit_events:
            progress_events.extend(file_edit_events)

    tool = EditFileTool(workspace=tmp_path)

    class Tools:
        def get_definitions(self):
            return [{"type": "function", "function": {"name": "edit_file"}}]

        def prepare_call(self, name, params):
            return tool, params, None

    async def chat_stream_with_retry(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
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
    tools = Tools()

    runner = AgentRunner()
    result = await runner.run(make_run_spec(provider,
        initial_messages=[{"role": "user", "content": "edit a file"}],
        tools=tools,
        model="test-model",
        max_iterations=2,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        progress_callback=progress_cb,
        workspace=tmp_path,
        hook=FileEditActivityHook(on_progress=progress_cb, workspace=tmp_path),
    ))

    assert result.final_content == "done"
    assert any(
        event["tool"] == "edit_file"
        and not event["approximate"]
        and event["phase"] == "end"
        and event["added"] == 2
        and event["deleted"] == 1
        and event["diff"]["format"] == "unified"
        for event in progress_events
    )
    provider.chat_with_retry.assert_not_awaited()


@pytest.mark.asyncio
async def test_runner_marks_file_edit_activity_failed_when_tool_errors(tmp_path):
    provider = MagicMock()
    provider.supports_progress_deltas = True
    call_count = 0
    progress_events: list[dict] = []

    async def progress_cb(content, *, file_edit_events=None, **kwargs):
        if file_edit_events:
            progress_events.extend(file_edit_events)

    tool = WriteFileTool(workspace=tmp_path)

    class Tools:
        def get_definitions(self):
            return [{"type": "function", "function": {"name": "write_file"}}]

        def prepare_call(self, name, params):
            return tool, params, None

    async def chat_stream_with_retry(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return LLMResponse(
                content=None,
                tool_calls=[
                    ToolCallRequest(
                        id="call-write",
                        name="write_file",
                        arguments={"path": "aborted.txt"},
                    )
                ],
                usage={},
            )
        return LLMResponse(content="done", tool_calls=[], usage={})

    provider.chat_stream_with_retry = chat_stream_with_retry
    provider.chat_with_retry = AsyncMock()
    tools = Tools()

    runner = AgentRunner()
    result = await runner.run(make_run_spec(provider,
        initial_messages=[{"role": "user", "content": "write a file"}],
        tools=tools,
        model="test-model",
        max_iterations=2,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        progress_callback=progress_cb,
        workspace=tmp_path,
        hook=FileEditActivityHook(on_progress=progress_cb, workspace=tmp_path),
    ))

    assert result.stop_reason == "completed"
    assert progress_events[-1]["path"] == "aborted.txt"
    assert progress_events[-1]["phase"] == "error"
    assert progress_events[-1]["status"] == "error"
    provider.chat_with_retry.assert_not_awaited()


@pytest.mark.asyncio
async def test_runner_marks_file_edit_activity_failed_when_cancelled(tmp_path):
    provider = MagicMock()
    provider.supports_progress_deltas = True
    progress_events: list[dict] = []
    executing = asyncio.Event()
    target = tmp_path / "cancelled.txt"
    target.write_text("old\n", encoding="utf-8")

    async def progress_cb(content, *, file_edit_events=None, **kwargs):
        if file_edit_events:
            progress_events.extend(file_edit_events)

    class SlowWriteTool(WriteFileTool):
        async def execute(self, path=None, content=None, **kwargs):
            executing.set()
            await asyncio.sleep(60)
            return "ok"

    tool = SlowWriteTool(workspace=tmp_path)

    class Tools:
        def get_definitions(self):
            return [{"type": "function", "function": {"name": "write_file"}}]

        def prepare_call(self, name, params):
            return tool, params, None

    async def chat_stream_with_retry(**kwargs):
        return LLMResponse(
            content=None,
            tool_calls=[
                ToolCallRequest(
                    id="call-write",
                    name="write_file",
                    arguments={"path": "cancelled.txt", "content": "new\n"},
                )
            ],
            usage={},
        )

    provider.chat_stream_with_retry = chat_stream_with_retry
    provider.chat_with_retry = AsyncMock()
    tools = Tools()

    runner = AgentRunner()
    task = asyncio.create_task(runner.run(make_run_spec(provider,
        initial_messages=[{"role": "user", "content": "write a file"}],
        tools=tools,
        model="test-model",
        max_iterations=2,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        progress_callback=progress_cb,
        workspace=tmp_path,
        hook=FileEditActivityHook(on_progress=progress_cb, workspace=tmp_path),
    )))
    await asyncio.wait_for(executing.wait(), timeout=1)

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert [event["phase"] for event in progress_events] == ["start", "error"]
    assert progress_events[-1]["path"] == "cancelled.txt"
    assert progress_events[-1]["status"] == "error"
    assert progress_events[-1]["error"] == "Task interrupted before this tool finished."
    provider.chat_with_retry.assert_not_awaited()
