"""Tests for runner progress hooks and provider event routing."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.runner_helpers import make_run_spec
from nanobot.agent.hooks import FileEditActivityHook
from nanobot.agent.progress_hook import AgentProgressHook
from nanobot.agent.runner import AgentRunner
from nanobot.agent.tools.filesystem import EditFileTool, WriteFileTool
from nanobot.config.schema import AgentDefaults
from nanobot.providers.base import LLMResponse, ToolCallRequest

_MAX_TOOL_RESULT_CHARS = AgentDefaults().max_tool_result_chars


@pytest.mark.asyncio
async def test_runner_routes_hosted_tool_events_to_structured_progress():
    provider = MagicMock()

    async def chat_stream_with_retry(*, on_content_delta, on_tool_call_delta, **kwargs):
        await on_tool_call_delta({
            "call_id": "local-call",
            "name": "read_file",
            "arguments_delta": "",
        })
        await on_tool_call_delta({
            "kind": "hosted_tool",
            "phase": "start",
            "call_id": "x-search-1",
            "name": "x_search",
            "arguments": {"query": "nanobot oauth"},
            "result": None,
        })
        await on_tool_call_delta({
            "kind": "hosted_tool",
            "phase": "end",
            "call_id": "x-search-1",
            "name": "x_search",
            "arguments": {"query": "nanobot oauth"},
            "result": {"name": "x_semantic_search"},
        })
        await on_content_delta("done")
        return LLMResponse(content="done", tool_calls=[], usage=None)

    provider.chat_stream_with_retry = chat_stream_with_retry
    provider.chat_with_retry = AsyncMock()
    tools = MagicMock()
    tools.get_definitions.return_value = []
    progress_events: list[dict] = []
    progress_text: list[str] = []
    streamed_text: list[str] = []

    async def progress_cb(content, *, tool_events=None, **kwargs):
        progress_text.append(content)
        if tool_events:
            progress_events.extend(tool_events)

    async def stream_cb(content: str) -> None:
        streamed_text.append(content)

    hook = AgentProgressHook(on_progress=progress_cb, on_stream=stream_cb)
    result = await AgentRunner().run(make_run_spec(
        provider,
        initial_messages=[{"role": "user", "content": "search X"}],
        tools=tools,
        model="test-model",
        max_iterations=1,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        hook=hook,
    ))

    assert result.final_content == "done"
    assert result.tools_used == []
    assert result.tool_events == []
    assert progress_events == [
        {
            "version": 1,
            "phase": "start",
            "call_id": "x-search-1",
            "name": "x_search",
            "arguments": {"query": "nanobot oauth"},
            "result": None,
            "error": None,
            "files": [],
            "embeds": [],
        },
        {
            "version": 1,
            "phase": "end",
            "call_id": "x-search-1",
            "name": "x_search",
            "arguments": {"query": "nanobot oauth"},
            "result": {"name": "x_semantic_search"},
            "error": None,
            "files": [],
            "embeds": [],
        },
    ]
    assert progress_text == ['search X "nanobot oauth"', ""]
    assert streamed_text == ["done"]
    provider.chat_with_retry.assert_not_awaited()


@pytest.mark.asyncio
async def test_runner_fails_pending_hosted_tool_when_model_request_fails():
    provider = MagicMock()

    async def chat_stream_with_retry(*, on_tool_call_delta, **kwargs):
        await on_tool_call_delta({
            "kind": "hosted_tool",
            "phase": "start",
            "call_id": "x-search-failed",
            "name": "x_search",
            "arguments": {"query": "nanobot oauth"},
            "result": None,
        })
        return LLMResponse(
            content="hosted search backend failed",
            finish_reason="error",
        )

    provider.chat_stream_with_retry = chat_stream_with_retry
    provider.chat_with_retry = AsyncMock()
    tools = MagicMock()
    tools.get_definitions.return_value = []
    progress_events: list[dict] = []

    async def progress_cb(content, *, tool_events=None, **kwargs):
        if tool_events:
            progress_events.extend(tool_events)

    async def stream_cb(_content: str) -> None:
        pass

    hook = AgentProgressHook(on_progress=progress_cb, on_stream=stream_cb)
    result = await AgentRunner().run(make_run_spec(
        provider,
        initial_messages=[{"role": "user", "content": "search X"}],
        tools=tools,
        model="test-model",
        max_iterations=1,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        hook=hook,
    ))

    assert result.stop_reason == "error"
    assert [(event["phase"], event["call_id"]) for event in progress_events] == [
        ("start", "x-search-failed"),
        ("error", "x-search-failed"),
    ]
    assert progress_events[-1] == {
        "version": 1,
        "phase": "error",
        "call_id": "x-search-failed",
        "name": "x_search",
        "arguments": {"query": "nanobot oauth"},
        "result": None,
        "error": "hosted search backend failed",
        "files": [],
        "embeds": [],
    }
    provider.chat_with_retry.assert_not_awaited()


@pytest.mark.asyncio
async def test_runner_emits_write_file_diff_from_tool_execution_snapshots(tmp_path):
    provider = MagicMock()
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

    async def chat_with_retry(**kwargs):
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
                usage=None,
            )
        return LLMResponse(content="done", tool_calls=[], usage=None)

    provider.chat_with_retry = chat_with_retry
    tools = Tools()

    runner = AgentRunner()
    result = await runner.run(make_run_spec(provider,
        initial_messages=[{"role": "user", "content": "write a large file"}],
        tools=tools,
        model="test-model",
        max_iterations=2,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
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


@pytest.mark.asyncio
async def test_runner_emits_edit_file_diff_from_tool_execution_snapshots(tmp_path):
    provider = MagicMock()
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

    async def chat_with_retry(**kwargs):
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
                usage=None,
            )
        return LLMResponse(content="done", tool_calls=[], usage=None)

    provider.chat_with_retry = chat_with_retry
    tools = Tools()

    runner = AgentRunner()
    result = await runner.run(make_run_spec(provider,
        initial_messages=[{"role": "user", "content": "edit a file"}],
        tools=tools,
        model="test-model",
        max_iterations=2,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
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


@pytest.mark.asyncio
async def test_runner_marks_file_edit_activity_failed_when_tool_errors(tmp_path):
    provider = MagicMock()
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

    async def chat_with_retry(**kwargs):
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
                usage=None,
            )
        return LLMResponse(content="done", tool_calls=[], usage=None)

    provider.chat_with_retry = chat_with_retry
    tools = Tools()

    runner = AgentRunner()
    result = await runner.run(make_run_spec(provider,
        initial_messages=[{"role": "user", "content": "write a file"}],
        tools=tools,
        model="test-model",
        max_iterations=2,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        workspace=tmp_path,
        hook=FileEditActivityHook(on_progress=progress_cb, workspace=tmp_path),
    ))

    assert result.stop_reason == "completed"
    assert progress_events[-1]["path"] == "aborted.txt"
    assert progress_events[-1]["phase"] == "error"
    assert progress_events[-1]["status"] == "error"


@pytest.mark.asyncio
async def test_runner_marks_file_edit_activity_failed_when_cancelled(tmp_path):
    provider = MagicMock()
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

    async def chat_with_retry(**kwargs):
        return LLMResponse(
            content=None,
            tool_calls=[
                ToolCallRequest(
                    id="call-write",
                    name="write_file",
                    arguments={"path": "cancelled.txt", "content": "new\n"},
                )
            ],
            usage=None,
        )

    provider.chat_with_retry = chat_with_retry
    tools = Tools()

    runner = AgentRunner()
    task = asyncio.create_task(runner.run(make_run_spec(provider,
        initial_messages=[{"role": "user", "content": "write a file"}],
        tools=tools,
        model="test-model",
        max_iterations=2,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
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
