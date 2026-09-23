import asyncio
from unittest.mock import AsyncMock, MagicMock
from weakref import WeakValueDictionary

import pytest

from nanobot.agent.hook import AgentHookContext
from nanobot.agent.runner import AgentRunResult
from nanobot.agent.subagent import SubagentManager, _SubagentHook
from nanobot.agent.tools.context import RequestContext, request_context
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import GenerationSettings, LLMProvider, LLMResponse, ToolCallRequest
from nanobot.session import subtask_outputs as outputs
from nanobot.session.manager import SessionManager
from nanobot.utils.llm_runtime import LLMRuntime


@pytest.fixture
def sessions(tmp_path):
    return SessionManager(tmp_path / "workspace", sessions_root=tmp_path / "state")


def test_bounded_allowlisted_snapshots_do_not_leak_internal_fields(sessions):
    session = sessions.get_or_create("websocket:parent")
    for i in range(40):
        observer = outputs.SubtaskOutput(sessions, session.key, str(i), "x" * 300, "turn")
        for tool in range(25):
            observer.update(tool=f"tool-{tool}")
        observer.update(state="completed", output="x" * 20_000)
    rows = outputs.public_subtasks(session.metadata)
    assert len(rows) == 32
    assert rows[0]["task_id"] == "8"
    assert len(rows[-1]["output"]) == 12_000
    assert len(rows[-1]["tools"]) == 20
    assert len(rows[-1]["label"]) == 120
    assert rows[-1]["truncated"]
    assert "runtime_id" not in rows[-1]
    rows[-1]["tools"].clear()
    assert outputs.public_subtasks(session.metadata)[-1]["tools"]


def test_existing_save_reload_restart_fork_and_invalidation(sessions, tmp_path, monkeypatch):
    session = sessions.get_or_create("websocket:parent")
    session.add_message("user", "Synthetic task")
    observer = outputs.SubtaskOutput(sessions, session.key, "task", "Review", "turn")
    observer.update(state="running", output="Visible output")
    sessions.save(session)
    restarted = SessionManager(tmp_path / "workspace", sessions_root=tmp_path / "state")
    monkeypatch.setattr(outputs, "_LIVE", WeakValueDictionary())
    raw = restarted.read_session_metadata(session.key)
    assert outputs.public_subtasks(raw["metadata"])[0]["state"] == "interrupted"
    forked = sessions.fork_session_before_user_index(session.key, "websocket:fork", 1)
    assert outputs.SUBTASK_OUTPUTS_KEY not in forked.metadata
    sessions.invalidate(session.key)
    previous = session.metadata[outputs.SUBTASK_OUTPUTS_KEY]
    observer.update(state="completed", output="late")
    assert session.metadata[outputs.SUBTASK_OUTPUTS_KEY] == previous
    assert sessions.get_cached(session.key) is None


def test_transient_observer_never_writes_and_closed_parent_not_recreated(sessions):
    session = sessions.get_or_create_transient("websocket:private")
    observer = outputs.SubtaskOutput(sessions, session.key, "task", "Synthetic", "turn")
    observer.update(state="completed", output="Synthetic output")
    sessions.save(session)
    assert sessions.read_session_metadata(session.key) is None
    sessions.invalidate(session.key)
    observer.update(output="late")
    assert sessions.get_cached(session.key) is None
    assert sessions.read_session_metadata(session.key) is None


def test_parallel_updates_keep_creation_order_and_parent_isolation(sessions):
    parent = sessions.get_or_create("websocket:parent")
    other = sessions.get_or_create("websocket:other")
    first = outputs.SubtaskOutput(sessions, parent.key, "first", "First", "turn")
    second = outputs.SubtaskOutput(sessions, parent.key, "second", "Second", "turn")
    for _ in range(20):
        second.update(output="Second output")
        first.update(output="First output")
    rows = outputs.public_subtasks(parent.metadata)
    assert [row["task_id"] for row in rows] == ["first", "second"]
    assert [row["output"] for row in rows] == ["First output", "Second output"]
    assert outputs.public_subtasks(other.metadata) == []


@pytest.mark.parametrize("metadata", [None, [], {}, {outputs.SUBTASK_OUTPUTS_KEY: [None, {}, {"state": []}]}])
def test_bad_metadata_is_ignored(metadata):
    assert outputs.public_subtasks(metadata) == []


async def test_hook_only_observes_answer_text_and_tool_names(sessions):
    session = sessions.get_or_create("websocket:parent")
    observer = outputs.SubtaskOutput(sessions, session.key, "task", "Review", "turn")
    hook = _SubagentHook("task", output=observer)
    context = AgentHookContext(iteration=2, messages=[{"role": "system", "content": "SECRET PROMPT"}],
        tool_calls=[ToolCallRequest(id="call", name="read_file", arguments={"password": "SECRET ARG"})])
    assert hook.wants_streaming()
    await hook.before_iteration(context)
    await hook.emit_reasoning("SECRET REASONING")
    await hook.before_execute_tools(context)
    await hook.on_stream(context, "Visible ")
    await hook.on_stream(context, "progress")
    row = outputs.public_subtasks(session.metadata)[0]
    assert row["output"] == "Visible progress"
    assert row["tools"] == ["read_file"]
    assert "SECRET" not in str(row)
    context.response = LLMResponse(content="Finished")
    await hook.after_iteration(context)
    assert outputs.public_subtasks(session.metadata)[0]["output"] == "Finished"


@pytest.mark.parametrize("inline", [True, False])
@pytest.mark.parametrize("failed", [True, False])
async def test_inline_and_background_keep_terminal_result_after_runtime_cleanup(sessions, tmp_path, inline, failed):
    parent = sessions.get_or_create("websocket:parent")
    provider = MagicMock(spec=LLMProvider)
    provider.generation = GenerationSettings()
    runtime = LLMRuntime.capture(provider, "test", context_window_tokens=128_000)
    manager = SubagentManager(workspace=tmp_path, bus=MessageBus(), max_tool_result_chars=16000, sessions=sessions)
    manager.runner.run = AsyncMock(return_value=AgentRunResult(
        messages=[], final_content="Synthetic result", tools_used=[],
        stop_reason="error" if failed else "completed", error="SECRET token" if failed else None,
    ))
    with request_context(RequestContext(channel="websocket", chat_id="parent", session_key=parent.key, turn_id="turn-1")):
        method = manager.run_inline if inline else manager.spawn
        await method("Task", session_key=parent.key, origin_channel="websocket", origin_chat_id="parent", runtime=runtime)
        await asyncio.gather(*tuple(manager._running_tasks.values()))
        await asyncio.sleep(0)
    assert not manager._task_statuses
    rows = outputs.public_subtasks(parent.metadata)
    assert rows[0]["turn_id"] == "turn-1"
    assert rows[0]["state"] == ("failed" if failed else "completed")
    assert rows[0]["output"] == ("" if failed else "Synthetic result")
    sessions.save(parent)
    assert outputs.public_subtasks(sessions.read_session_metadata(parent.key)["metadata"]) == rows
    await manager.close()


async def test_cancellation_preserves_last_visible_output(sessions, tmp_path):
    parent = sessions.get_or_create("websocket:parent")
    provider = MagicMock(spec=LLMProvider)
    provider.generation = GenerationSettings()
    runtime = LLMRuntime.capture(provider, "test", context_window_tokens=128_000)
    manager = SubagentManager(workspace=tmp_path, bus=MessageBus(), max_tool_result_chars=16000, sessions=sessions)
    started = asyncio.Event()
    async def run(spec):
        await spec.hook.on_stream(AgentHookContext(iteration=1, messages=[]), "Partial output")
        started.set()
        await asyncio.Event().wait()
    manager.runner.run = run
    await manager.spawn("Task", runtime=runtime, session_key=parent.key)
    await started.wait()
    assert await manager.cancel_by_session(parent.key) == 1
    row = outputs.public_subtasks(parent.metadata)[0]
    assert row["state"] == "cancelled"
    assert row["output"] == "Partial output"
    await manager.close()
