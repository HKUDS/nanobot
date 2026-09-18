"""Delegated sessions exercise the same context and execution path as chat."""

import asyncio
import os
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.session_helpers import run_session
from nanobot.agent.loop import AgentLoop
from nanobot.agent.tools.context import current_request_context
from nanobot.agent.tools.filesystem import FileToolsConfig
from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import ToolsConfig
from nanobot.llm_usage.context import current_llm_usage_source, llm_usage_source
from nanobot.providers.base import GenerationSettings, LLMProvider, LLMResponse, ToolCallRequest
from nanobot.security.workspace_access import build_workspace_scope, current_workspace_scope


def _loop(tmp_path, **kwargs):
    provider = MagicMock(spec=LLMProvider)
    provider.get_default_model.return_value = "test-model"
    provider.generation = GenerationSettings(max_tokens=4096)
    provider.can_resume_conversation_state.return_value = False
    return AgentLoop(
        bus=MessageBus(), provider=provider, workspace=tmp_path,
        context_window_tokens=128_000, **kwargs,
    )


@pytest.mark.parametrize("mode", ["child", "temporary"])
async def test_private_sessions_compact_without_writing_memory(tmp_path, monkeypatch, mode):
    loop = _loop(tmp_path)
    (tmp_path / "note.txt").write_text("private tool evidence", encoding="utf-8")
    loop.context.memory.write_memory("PARENT MEMORY MUST NOT BE INJECTED")
    parent = loop.sessions.get_or_create("websocket:parent")
    parent.add_message("user", "PARENT TRANSCRIPT MUST NOT BE INHERITED")
    loop.sessions.save(parent)
    before = loop.sessions.list_sessions()
    checkpoint = "private-checkpoint: inspected note.txt; finish the task"
    requests = []
    responses = iter([
        LLMResponse(content=None, tool_calls=[ToolCallRequest(
            id="read-1", name="read_file", arguments={"path": "note.txt"},
        )]),
        LLMResponse(content=checkpoint),
        LLMResponse(content="finished"),
        LLMResponse(content="continued"),
    ])

    async def respond(**kwargs):
        requests.append(kwargs["messages"])
        return next(responses)

    def count(_provider, _model, messages, _tools):
        pressured = (
            any(m.get("role") == "tool" for m in messages)
            and checkpoint not in messages[0]["content"]
        )
        return (130_000 if pressured else 100), "test-counter"

    monkeypatch.setattr("nanobot.agent.context_governance.estimate_prompt_tokens_chain", count)
    loop.provider.chat_stream_with_retry = AsyncMock(side_effect=respond)
    if mode == "child":
        result = await loop.subagents.run_inline(
            "Inspect note.txt and finish", runtime=loop.llm_runtime(), session_key=parent.key,
        )
        assert result == "finished"
    else:
        key = "websocket:temporary"
        temporary = loop.sessions.get_or_create_transient(key)
        result = await loop.process_direct("Inspect note.txt and finish", session_key=key)
        assert result.content == "finished"
        await loop.process_direct("Continue", session_key=key)
        assert checkpoint in str(requests[-1])
        assert temporary.messages
        assert loop.sessions.read_session_file(key) is None

    assert "SNIP" in str(requests[1][-1])
    assert checkpoint in requests[2][0]["content"]
    assert "private tool evidence" in str(requests[2])
    assert "PARENT MEMORY MUST NOT BE INJECTED" not in str(requests)
    assert "PARENT TRANSCRIPT MUST NOT BE INHERITED" not in str(requests)
    assert loop.sessions.list_sessions() == before
    assert not loop.context.memory.history_file.exists()
    assert loop.context.memory.read_memory() == "PARENT MEMORY MUST NOT BE INJECTED"
    await loop.aclose()


@pytest.mark.parametrize("outcome", ["done", "error", "cancel"])
async def test_child_cleanup_is_scoped_to_its_own_session(tmp_path, outcome):
    loop = _loop(tmp_path)
    entered = asyncio.Event()
    owners = []
    original_states = []
    terminate = AsyncMock(return_value=0)
    loop._exec_session_manager.terminate_by_owner = terminate

    async def respond(**kwargs):
        ctx = current_request_context()
        owners.append(ctx.session_key)
        original_states.append(loop._file_state_store.for_session(ctx.session_key))
        assert ctx.session_key.startswith("internal:")
        assert loop.sessions.get_cached(ctx.session_key) is None
        assert ctx.runtime is runtime
        assert current_llm_usage_source() == "cron"
        names = {tool["function"]["name"] for tool in kwargs["tools"]}
        assert {"read_file", "grep", "find_files", "exec"} <= names
        assert names.isdisjoint({
            "spawn", "message", "cron", "create_goal", "update_goal", "read_session",
            "list_sessions", "search_sessions", "send_session_message", "my",
        })
        entered.set()
        if outcome == "cancel":
            await asyncio.Event().wait()
        if outcome == "error":
            raise RuntimeError("provider failed")
        return LLMResponse(content="done")

    runtime = loop.llm_runtime()
    loop.provider.chat_stream_with_retry = AsyncMock(side_effect=respond)
    with llm_usage_source("cron"):
        task = asyncio.create_task(loop.subagents.run_inline(
            "task", runtime=runtime, session_key="websocket:parent",
        ))
    await asyncio.wait_for(entered.wait(), timeout=5)
    if outcome == "cancel":
        assert await loop.subagents.cancel_by_session("websocket:parent") == 1
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        result = await task
        assert ("provider failed" if outcome == "error" else "done") in result
    terminate.assert_awaited_once_with(owners[0])
    assert loop._file_state_store.for_session(owners[0]) is not original_states[0]
    assert loop.subagents.get_running_count() == 0
    assert loop.sessions.list_sessions() == []
    await loop.aclose()


async def test_inline_spawn_finishes_with_one_global_request_slot(tmp_path, monkeypatch):
    monkeypatch.setenv("NANOBOT_MAX_CONCURRENT_REQUESTS", "1")
    loop = _loop(tmp_path)
    calls = 0

    async def respond(**kwargs):
        nonlocal calls
        calls += 1
        ctx = current_request_context()
        if ctx.session_key.startswith("internal:"):
            return LLMResponse(content="child answer")
        if calls == 1:
            return LLMResponse(content=None, tool_calls=[ToolCallRequest(
                id="spawn-1", name="spawn", arguments={"task": "consult", "wait": True},
            )])
        assert "child answer" in str(kwargs["messages"])
        return LLMResponse(content="parent answer")

    loop.provider.chat_stream_with_retry = AsyncMock(side_effect=respond)
    await asyncio.wait_for(run_session(loop, InboundMessage(
        channel="cli", chat_id="parent", sender_id="user", content="consult a child",
    )), timeout=10)
    assert calls == 3
    assert loop.sessions.get_or_create("cli:parent").messages[-1]["content"] == "parent answer"
    assert not loop.subagents.get_running_count()
    await loop.aclose()


async def test_child_inherits_workspace_and_uses_shared_prompt(tmp_path):
    agent = tmp_path / "agent"
    project = tmp_path / "project"
    agent.mkdir()
    project.mkdir()
    (project / "AGENTS.md").write_text("PROJECT INSTRUCTION", encoding="utf-8")
    for root, name in ((agent, "global-custom"), (project, "project-custom")):
        skill = root / "skills" / name / "SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_text(f"---\ndescription: {name}\n---\nInstructions", encoding="utf-8")
    loop = _loop(agent)
    scope = build_workspace_scope(project, "restricted", source_channel="websocket")
    captured = []

    async def respond(**kwargs):
        assert current_workspace_scope() == scope
        assert current_request_context().workspace == project
        captured.append(kwargs["messages"])
        if len(captured) == 1:
            return LLMResponse(content=None, tool_calls=[ToolCallRequest(
                id="escape", name="read_file", arguments={"path": str(tmp_path / "secret")},
            )])
        assert "outside" in str(kwargs["messages"]).lower()
        return LLMResponse(content="restricted")

    loop.provider.chat_stream_with_retry = AsyncMock(side_effect=respond)
    result = await loop.subagents.run_inline(
        "inspect", runtime=loop.llm_runtime(), workspace_scope=scope,
    )
    assert result == "restricted"
    assert "PROJECT INSTRUCTION" in captured[0][0]["content"]
    assert "global-custom" in captured[0][0]["content"]
    assert "project-custom" not in captured[0][0]["content"]
    assert "reported back to the main agent" in captured[0][1]["content"]
    await loop.aclose()


async def test_concurrent_children_have_independent_file_read_state(tmp_path):
    loop = _loop(tmp_path)
    (tmp_path / "note.txt").write_text("hello\n", encoding="utf-8")
    readers = set()
    both_read = asyncio.Event()

    async def respond(**kwargs):
        messages = kwargs["messages"]
        if messages[-1]["role"] != "tool":
            return LLMResponse(content=None, tool_calls=[ToolCallRequest(
                id="read", name="read_file", arguments={"path": "note.txt"},
            )])
        assert messages[-1]["content"].startswith("1| hello")
        assert "File unchanged" not in messages[-1]["content"]
        readers.add(current_request_context().session_key)
        if len(readers) == 2:
            both_read.set()
        await both_read.wait()
        return LLMResponse(content="done")

    loop.provider.chat_stream_with_retry = AsyncMock(side_effect=respond)
    try:
        results = await asyncio.wait_for(asyncio.gather(*(
            loop.subagents.run_inline("Read note.txt", runtime=loop.llm_runtime())
            for _ in range(2)
        )), timeout=10)
        assert results == ["done", "done"]
        assert len(readers) == 2
    finally:
        await loop.aclose()


async def test_child_honors_file_tool_configuration(tmp_path):
    loop = _loop(tmp_path, tools_config=ToolsConfig(file=FileToolsConfig(enable=False)))

    async def respond(**kwargs):
        names = {tool["function"]["name"] for tool in kwargs["tools"]}
        assert names.isdisjoint({"read_file", "write_file", "edit_file", "grep", "find_files"})
        return LLMResponse(content="done")

    loop.provider.chat_stream_with_retry = AsyncMock(side_effect=respond)
    assert await loop.subagents.run_inline("task", runtime=loop.llm_runtime()) == "done"
    await loop.aclose()


@pytest.mark.parametrize("outcome", ["done", "cancel"])
async def test_child_reaps_its_process_without_terminating_parent_process(tmp_path, outcome):
    loop = _loop(tmp_path)
    manager = loop._exec_session_manager
    command = f'"{sys.executable}" -c "import sys; sys.stdin.read()"'
    shell = "cmd" if sys.platform == "win32" else "sh"
    entered = asyncio.Event()
    child_processes = []
    child_keys = []

    async def respond(**kwargs):
        key = current_request_context().session_key
        if not any(message.get("role") == "tool" for message in kwargs["messages"]):
            return LLMResponse(content=None, tool_calls=[ToolCallRequest(
                id="start-process", name="exec",
                arguments={"command": command, "shell": shell, "yield_time_ms": 0},
            )])
        sessions = await manager.list(owner_session_key=key)
        assert len(sessions) == 1, kwargs["messages"][-1]
        child_keys.append(key)
        child_processes.append(manager._sessions[sessions[0].session_id].process)
        entered.set()
        if outcome == "cancel":
            await asyncio.Event().wait()
        return LLMResponse(content="done")

    loop.provider.chat_stream_with_retry = AsyncMock(side_effect=respond)
    try:
        parent_id, poll = await manager.start(
            command=command, cwd=str(tmp_path), env=dict(os.environ), timeout=30,
            shell_program=shell, login=False, yield_time_ms=0, max_output_chars=1000,
            owner_session_key="websocket:parent",
        )
        assert not poll.done
        task = asyncio.create_task(loop.subagents.run_inline(
            "Start a process", runtime=loop.llm_runtime(), session_key="websocket:parent",
        ))
        await asyncio.wait_for(entered.wait(), timeout=10)
        if outcome == "cancel":
            assert await loop.subagents.cancel_by_session("websocket:parent") == 1
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            assert await task == "done"
        assert child_processes[0].returncode is not None
        assert await manager.list(owner_session_key=child_keys[0]) == []
        parent_sessions = await manager.list(owner_session_key="websocket:parent")
        assert [session.session_id for session in parent_sessions] == [parent_id]
        assert parent_sessions[0].returncode is None
    finally:
        await loop.aclose()
