import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.runner_helpers import make_run_spec
from nanobot.agent.progress_hook import AgentProgressHook
from nanobot.agent.runner import AgentRunner
from nanobot.agent.tools.base import ToolResult
from nanobot.agent.tools.registry import with_tool_error_hint
from nanobot.config.schema import AgentDefaults
from nanobot.providers.base import LLMResponse, ToolCallRequest
from nanobot.utils.progress_events import output_events

_DEFAULTS = AgentDefaults()


@pytest.mark.asyncio
async def test_tool_error_code_is_display_metadata_not_model_content() -> None:
    provider, tools = MagicMock(), MagicMock()
    tool_call = ToolCallRequest(id="sandbox-call", name="exec", arguments={"command": "printf test"})
    responses = iter([
        LLMResponse(content="", tool_calls=[tool_call]),
        LLMResponse(content="Please check the installation.", tool_calls=[]),
    ])
    provider.chat_stream_with_retry = AsyncMock(side_effect=lambda *a, **kw: next(responses))
    tools.get_definitions.return_value = []
    tools.prepare_call.return_value = (None, tool_call.arguments, None)
    text = "Error: sandbox launcher not found: bwrap"
    tools.execute = AsyncMock(return_value=ToolResult.error(text, error_code="sandbox_launcher_missing"))
    events: list[dict] = []

    async def on_progress(content: str, *, tool_hint: bool = False, tool_events: list[dict] | None = None) -> None:
        events.extend(tool_events or [])

    await AgentRunner().run(make_run_spec(
        provider, tools=tools, model="test", initial_messages=[{"role": "user", "content": "Run a command"}],
        max_iterations=3, max_tool_result_chars=_DEFAULTS.max_tool_result_chars,
        hook=AgentProgressHook(output_events(on_progress=on_progress)),
    ))

    finished = events[-1]
    assert finished["phase"] == "error"
    assert finished["error_code"] == "sandbox_launcher_missing"
    assert finished["error"] == with_tool_error_hint(text)
    request = provider.chat_stream_with_retry.call_args.kwargs
    tool_message = next(message for message in request["messages"] if message["role"] == "tool")
    assert tool_message["content"] == with_tool_error_hint(text)
    assert "error_code" not in tool_message


@pytest.mark.asyncio
async def test_start_and_finish_events_emitted() -> None:
    provider = MagicMock()
    tools = MagicMock()
    tool_call = ToolCallRequest(id="call1", name="custom_tool", arguments={"path": "foo.txt"})
    calls = iter([
        LLMResponse(content="Visible", tool_calls=[tool_call]),
        LLMResponse(content="Done", tool_calls=[]),
    ])
    provider.chat_stream_with_retry = AsyncMock(side_effect=lambda *a, **kw: next(calls))
    tools.get_definitions.return_value = []
    tools.prepare_call.return_value = (None, {"path": "foo.txt"}, None)
    tools.execute = AsyncMock(return_value="ok")

    progress: list[tuple[str, bool, list[dict] | None]] = []

    async def on_progress(
        content: str,
        *,
        tool_hint: bool = False,
        tool_events: list[dict] | None = None,
    ) -> None:
        progress.append((content, tool_hint, tool_events))

    result = await AgentRunner().run(make_run_spec(
        provider,
        initial_messages=[],
        tools=tools,
        model="test-model",
        max_iterations=_DEFAULTS.max_tool_iterations,
        max_tool_result_chars=_DEFAULTS.max_tool_result_chars,
        concurrent_tools=True,
        hook=AgentProgressHook(output_events(on_progress=on_progress)),
    ))

    assert result.final_content == "Done"
    assert progress == [
        ("Visible", False, None),
        (
            "",
            True,
            [{
                "version": 1,
                "phase": "start",
                "call_id": "call1",
                "name": "custom_tool",
                "arguments": {"path": "foo.txt"},
                "result": None,
                "error": None,
                "files": [],
                "embeds": [],
                "working_directory": str(Path.cwd()),
            }],
        ),
        (
            "",
            False,
            [{
                "version": 1,
                "phase": "end",
                "call_id": "call1",
                "name": "custom_tool",
                "arguments": {"path": "foo.txt"},
                "result": "ok",
                "error": None,
                "files": [],
                "embeds": [],
                "working_directory": str(Path.cwd()),
            }],
        ),
    ]


@pytest.mark.asyncio
async def test_streamed_content_is_not_repeated_before_tool_execution() -> None:
    provider = MagicMock()
    tools = MagicMock()
    tool_call = ToolCallRequest(id="call1", name="custom_tool", arguments={"path": "foo.txt"})
    calls = iter([
        LLMResponse(content="I will inspect it.", tool_calls=[tool_call]),
        LLMResponse(content="Done", tool_calls=[]),
    ])

    async def chat_stream_with_retry(*, on_content_delta, **kwargs):
        response = next(calls)
        if response.tool_calls:
            await on_content_delta("I will ")
            await on_content_delta("inspect it.")
        return response

    provider.chat_stream_with_retry = chat_stream_with_retry
    provider.chat_with_retry = AsyncMock()
    tools.get_definitions.return_value = []
    tools.prepare_call.return_value = (None, {"path": "foo.txt"}, None)
    tools.execute = AsyncMock(return_value="ok")

    streamed: list[str] = []
    progress: list[tuple[str, bool, list[dict] | None]] = []

    async def on_stream(delta: str) -> None:
        streamed.append(delta)

    async def on_progress(
        content: str,
        *,
        tool_hint: bool = False,
        tool_events: list[dict] | None = None,
    ) -> None:
        progress.append((content, tool_hint, tool_events))

    result = await AgentRunner().run(make_run_spec(
        provider,
        initial_messages=[],
        tools=tools,
        model="test-model",
        max_iterations=_DEFAULTS.max_tool_iterations,
        max_tool_result_chars=_DEFAULTS.max_tool_result_chars,
        concurrent_tools=True,
        hook=AgentProgressHook(
            output_events(on_progress=on_progress, on_stream=on_stream),
            streaming=True,
        ),
    ))

    assert result.final_content == "Done"
    assert streamed == ["I will", " inspect it."]
    assert progress[0] == ("", True, [{
        "version": 1, "phase": "start", "call_id": "call1", "name": "custom_tool",
        "arguments": {"path": "foo.txt"}, "result": None, "error": None,
        "files": [], "embeds": [], "working_directory": str(Path.cwd()),
    }])
    assert all(item[0] != "I will inspect it." for item in progress)


@pytest.mark.asyncio
async def test_batched_file_reads_keep_each_call_and_complete_arguments() -> None:
    provider = MagicMock()
    calls = [
        ToolCallRequest(
            id=f"read-{offset}", name="read_file",
            arguments={"path": "src/" + "very-long-directory/" * 8 + "说明.md", "offset": offset},
        )
        for offset in (1, 200)
    ]
    responses = iter([
        LLMResponse(content="", tool_calls=calls),
        LLMResponse(content="Done", tool_calls=[]),
    ])
    provider.chat_stream_with_retry = AsyncMock(side_effect=lambda *a, **kw: next(responses))
    tools = MagicMock()
    tools.get_definitions.return_value = []
    tools.prepare_call.side_effect = lambda _name, args: (None, args, None)
    tools.execute = AsyncMock(return_value="file contents")
    progress = []

    async def on_progress(content, *, tool_hint=False, tool_events=None):
        progress.append((content, tool_hint, tool_events))

    result = await AgentRunner().run(make_run_spec(
        provider, initial_messages=[], tools=tools, model="test-model",
        max_iterations=2, max_tool_result_chars=_DEFAULTS.max_tool_result_chars,
        concurrent_tools=True, hook=AgentProgressHook(output_events(on_progress=on_progress)),
    ))

    assert result.final_content == "Done"
    assert len(progress) == 4
    for phase, hint in (("start", True), ("end", False)):
        events = [item for content, is_hint, items in progress if is_hint == hint for item in items]
        assert [(item["call_id"], item["name"], item["arguments"]) for item in events] == [
            (call.id, call.name, call.arguments) for call in calls
        ]
        assert [item["phase"] for item in events] == [phase, phase]
        if phase == "end":
            assert [item["result"] for item in events] == ["file contents", "file contents"]


def _notification_run_spec(execute, on_progress, calls, checkpoints):
    provider = MagicMock()
    provider.chat_stream_with_retry = AsyncMock(side_effect=[
        LLMResponse(content=None, tool_calls=calls),
        LLMResponse(content="Done"),
    ])
    tools = MagicMock()
    tools.get_definitions.return_value = []
    tools.prepare_call.return_value = (None, {}, None)
    tools.execute = execute

    async def checkpoint(payload):
        checkpoints.append(payload)

    return make_run_spec(
        provider, initial_messages=[], tools=tools, model="test-model",
        max_iterations=2, max_tool_result_chars=_DEFAULTS.max_tool_result_chars,
        concurrent_tools=True, hook=AgentProgressHook(output_events(on_progress=on_progress)),
        checkpoint_callback=checkpoint,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_phase", ["start", "end"])
async def test_tool_notification_failure_settles_results_and_cancels_siblings(failure_phase):
    entered = asyncio.Event()
    release = asyncio.Event()
    stopped = asyncio.Event()
    effects = []
    checkpoints = []
    error = BrokenPipeError("progress consumer closed")

    async def execute(name, arguments):
        if name == "slow":
            entered.set()
            try:
                await release.wait()
                effects.append("slow")
                return "slow result"
            finally:
                stopped.set()
        effects.append("fast")
        return "fast result"

    async def progress(content, *, tool_events=None, **kwargs):
        if any(event["call_id"] == "fast" and event["phase"] == failure_phase
               for event in tool_events or []):
            await entered.wait()
            raise error

    task = asyncio.create_task(AgentRunner().run(_notification_run_spec(
        execute, progress,
        [ToolCallRequest("slow", "slow", {}), ToolCallRequest("fast", "fast", {})],
        checkpoints,
    )))
    try:
        with pytest.raises(BrokenPipeError) as raised:
            await asyncio.wait_for(task, 2)
        assert raised.value is error
        assert stopped.is_set()
        assert effects == (["fast"] if failure_phase == "end" else [])
        if failure_phase == "end":
            checkpoint = checkpoints[-1]
            assert checkpoint["phase"] == "tools_completed"
            slow, fast = checkpoint["completed_tool_results"]
            assert (fast["tool_call_id"], fast["content"]) == ("fast", "fast result")
            assert slow["tool_call_id"] == "slow"
            assert slow["_recovery_interrupted"] is True
            assert "outcome is unknown" in slow["content"]
            assert checkpoint["pending_tool_calls"] == []
            from nanobot.session.recovery import runtime_checkpoint_is_well_formed

            assert runtime_checkpoint_is_well_formed(checkpoint)
        else:
            assert [checkpoint["phase"] for checkpoint in checkpoints] == ["awaiting_tools"]
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
        await asyncio.wait_for(stopped.wait(), 2)


@pytest.mark.asyncio
async def test_tool_completion_notification_error_preserves_completed_checkpoint():
    checkpoints = []
    error = BrokenPipeError("progress consumer closed")

    async def progress(content, *, tool_events=None, **kwargs):
        if any(event["phase"] == "end" for event in tool_events or []):
            raise error

    with pytest.raises(BrokenPipeError) as raised:
        await AgentRunner().run(_notification_run_spec(
            AsyncMock(return_value="completed effect"), progress,
            [ToolCallRequest("fast", "fast", {})], checkpoints,
        ))
    assert raised.value is error
    assert [checkpoint["phase"] for checkpoint in checkpoints] == ["awaiting_tools", "tools_completed"]
    assert checkpoints[-1]["completed_tool_results"][0]["content"] == "completed effect"
    assert checkpoints[-1]["pending_tool_calls"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_during", ["start", "execution", "end"])
async def test_tool_cancellation_does_not_wait_for_blocked_progress(cancel_during):
    queue = asyncio.Queue(maxsize=1)
    if cancel_during == "start":
        queue.put_nowait([])
    entered = asyncio.Event()
    release = asyncio.Event()
    stopped = asyncio.Event()
    checkpoints = []
    effects = []
    notifications = set()

    async def execute(name, arguments):
        if cancel_during == "execution":
            entered.set()
            try:
                await release.wait()
            finally:
                stopped.set()
        effects.append(name)
        return "completed effect"

    async def progress(content, *, tool_events=None, **kwargs):
        if tool_events:
            notification = asyncio.current_task()
            notifications.add(notification)
            try:
                if any(event["phase"] == cancel_during for event in tool_events):
                    entered.set()
                await queue.put(tool_events)
            finally:
                notifications.remove(notification)

    task = asyncio.create_task(AgentRunner().run(_notification_run_spec(
        execute, progress, [ToolCallRequest("tool", "tool", {})], checkpoints,
    )))
    try:
        await asyncio.wait_for(entered.wait(), 2)
        task.cancel()
        done, _ = await asyncio.wait({task}, timeout=1)
        assert done, "cancellation must settle without a second cancel or queue consumer"
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not notifications
        assert effects == (["tool"] if cancel_during == "end" else [])
        if cancel_during == "end":
            assert checkpoints[-1]["phase"] == "tools_completed"
            assert checkpoints[-1]["completed_tool_results"][0]["content"] == "completed effect"
        elif cancel_during == "execution":
            assert stopped.is_set()
    finally:
        # Keep the failure reproduction bounded even with the old shielded send.
        if not queue.empty():
            queue.get_nowait()
        release.set()
        await asyncio.gather(task, return_exceptions=True)
