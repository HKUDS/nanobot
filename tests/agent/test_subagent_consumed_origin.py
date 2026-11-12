from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import textwrap
from copy import deepcopy
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.runner_helpers import make_run_spec
from agent.session_helpers import save_completed_subagent
from nanobot.agent.context import TranscriptInput
from nanobot.agent.loop import AgentLoop
from nanobot.agent.runner import AgentRunner
from nanobot.agent.subagent_sessions import TASK_METADATA_KEY
from nanobot.agent.tools.context import RequestContext, request_context
from nanobot.agent.tools.subagent import SubagentTool
from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import (
    GenerationSettings,
    LLMResponse,
    ProviderConversationState,
    ToolCallRequest,
)
from nanobot.session.input_keys import MODEL_INPUT_ROLE_KEY
from nanobot.session.manager import Session, SessionManager
from nanobot.session.message_metadata import (
    CONSUMED_INPUT_CURSOR_KEY,
    CONSUMED_INPUT_ID_KEY,
    consumed_input_cursor,
)
from nanobot.session.recovery import RUNTIME_CHECKPOINT_KEY, restore_runtime_checkpoint
from nanobot.session.session_messages import SESSION_MESSAGE_METADATA_KEY


def user(content: str, turn: str | None, *, chat: str = "chat") -> InboundMessage:
    metadata = {"message_id": f"ui-{content}"}
    if turn is not None:
        metadata["webui_turn_id"] = turn
    return InboundMessage(channel="websocket", sender_id="user", chat_id=chat, content=content, metadata=metadata)


def system_result(task_id: str, *, chat: str = "chat") -> InboundMessage:
    key = f"websocket:{chat}"
    return InboundMessage(
        channel="system", sender_id="subagent", chat_id=key, session_key_override=key,
        require_existing_session=True, content=f"Result from {task_id}",
        metadata={"injected_event": "subagent_result", "subagent_task_id": task_id},
    )


def provider() -> MagicMock:
    result = MagicMock(aclose=AsyncMock())
    result.get_default_model.return_value = "test-model"
    result.generation = GenerationSettings()
    result.can_resume_conversation_state.return_value = False
    return result


def main_request(kwargs: dict) -> bool:
    return any(item["function"]["name"] == "subagent" for item in kwargs["tools"])


def create_call(label: str, *, wait: bool = True) -> LLMResponse:
    return LLMResponse(content=None, tool_calls=[ToolCallRequest(
        label, "subagent", {"action": "create", "task": label, "label": label, "wait": wait},
    )])


async def dispatch_and_wait(loop: AgentLoop, message: InboundMessage) -> None:
    await loop._dispatch_inbound(message)
    tasks = tuple(loop._active_tasks.get(message.session_key, ()))
    if tasks:
        await asyncio.wait_for(asyncio.gather(*tasks), 10)


@pytest.mark.parametrize("arrival", ["model", "tool"])
async def test_creation_uses_request_snapshot_not_later_queued_input(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, arrival: str,
) -> None:
    backend = provider()
    entered, release = asyncio.Event(), asyncio.Event()
    main_calls = []

    async def respond(**kwargs):
        if not main_request(kwargs):
            return LLMResponse(content="child done")
        main_calls.append(deepcopy(kwargs["messages"]))
        if len(main_calls) == 1:
            if arrival == "model":
                entered.set()
                await release.wait()
            return create_call("first")
        if len(main_calls) == 2:
            return create_call("second")
        return LLMResponse(content="finished")

    backend.chat_stream_with_retry = AsyncMock(side_effect=respond)
    loop = AgentLoop(bus=MessageBus(), provider=backend, workspace=tmp_path, model="test-model")
    run_inline = loop.subagents.run_inline

    async def delayed_child(*args, **kwargs):
        if kwargs["label"] == "first" and arrival == "tool":
            entered.set()
            await release.wait()
        return await run_inline(*args, **kwargs)

    monkeypatch.setattr(loop.subagents, "run_inline", delayed_child)
    try:
        await save_completed_subagent(loop, "queued-result", "websocket:chat")
        await loop._dispatch_inbound(user("A", "turn-a"))
        await asyncio.wait_for(entered.wait(), 5)
        await loop._dispatch_inbound(user("B", "turn-b"))
        await loop._dispatch_inbound(system_result("queued-result"))
        assert loop._pending_queues["websocket:chat"].qsize() == 2
        release.set()
        await asyncio.wait_for(asyncio.gather(*loop._active_tasks["websocket:chat"]), 10)
        statuses = {
            status.label: status for status in loop.subagents.statuses_for_session("websocket:chat").values()
            if status.label in {"first", "second"}
        }
        assert {name: status.origin_input_id for name, status in statuses.items()} == {
            "first": "user:turn-a", "second": "user:turn-b",
        }
        assert all(status.origin_message_id == "ui-A" for status in statuses.values())
        assert not any(row.get("_meta", {}).get("input_id") == "user:turn-b" for row in main_calls[0])
        assert any(row.get("_meta", {}).get("input_id") == "user:turn-b" for row in main_calls[1])
        stored = await loop.sessions.state.get("websocket:chat")
        tool_responses = [row for row in stored.messages if row.get("tool_calls")]
        # The existing response-input semantics stop at a system result; they
        # intentionally differ from the last consumed user-input cursor.
        assert [row["response_input_ids"] for row in tool_responses] == [["user:turn-a"], []]
        reloaded = SessionManager(tmp_path)
        try:
            from nanobot.agent.subagent_sessions import SubagentSessions
            children = SubagentSessions(reloaded).load("websocket:chat")
            assert {
                status.label: status.as_dict()["origin_input_id"] for status in children.values()
                if status.label in {"first", "second"}
            } == {"first": "user:turn-a", "second": "user:turn-b"}
        finally:
            await reloaded.state.aclose()
    finally:
        release.set()
        await loop.aclose()


async def test_system_run_unknown_input_session_message_and_reset(tmp_path: Path) -> None:
    backend = provider()
    next_label: str | None = None

    async def respond(**kwargs):
        nonlocal next_label
        if main_request(kwargs) and next_label is not None:
            label, next_label = next_label, None
            return create_call(label)
        return LLMResponse(content="done")

    backend.chat_stream_with_retry = AsyncMock(side_effect=respond)
    loop = AgentLoop(bus=MessageBus(), provider=backend, workspace=tmp_path, model="test-model")
    key = "websocket:chat"
    try:
        await dispatch_and_wait(loop, user("A", "turn-a"))
        await save_completed_subagent(loop, "background-1", key)
        next_label = "independent"
        await dispatch_and_wait(loop, system_result("background-1"))
        status = next(s for s in loop.subagents.statuses_for_session(key).values() if s.label == "independent")
        assert status.origin_input_id == "user:turn-a"

        # Bound automation is delivered on the user's channel, but it is not a
        # user input even when it carries a turn identifier.
        next_label = "scheduled"
        await dispatch_and_wait(loop, InboundMessage(
            channel="websocket", sender_id="cron", chat_id="chat", content="scheduled check",
            metadata={"webui_turn_id": "scheduled-turn", "_cron_trigger": {"job_id": "job"}},
        ))
        status = next(s for s in loop.subagents.statuses_for_session(key).values() if s.label == "scheduled")
        assert status.origin_input_id == "user:turn-a"
        await save_completed_subagent(loop, "background-after-scheduled", key)
        next_label = "after-scheduled"
        await dispatch_and_wait(loop, system_result("background-after-scheduled"))
        status = next(s for s in loop.subagents.statuses_for_session(key).values() if s.label == "after-scheduled")
        assert status.origin_input_id == "user:turn-a"

        envelope = {
            "message_id": "session-1", "created_at_ms": 1, "expect_reply": False,
            "source_handle": "peer", "source_session_key": "websocket:peer", "target_session_key": key,
        }
        next_label = "session-input"
        await dispatch_and_wait(loop, InboundMessage(
            channel="system", sender_id="session", chat_id=key, session_key_override=key,
            input_role="user", content="B", metadata={SESSION_MESSAGE_METADATA_KEY: envelope},
        ))
        status = next(s for s in loop.subagents.statuses_for_session(key).values() if s.label == "session-input")
        assert status.origin_input_id == "session-message:session-1"

        next_label = "unknown"
        await dispatch_and_wait(loop, user("C", None))
        status = next(s for s in loop.subagents.statuses_for_session(key).values() if s.label == "unknown")
        assert status.origin_message_id == "ui-C"
        assert status.as_dict()["origin_input_id"] is None
        await save_completed_subagent(loop, "background-2", key)
        next_label = "after-unknown"
        await dispatch_and_wait(loop, system_result("background-2"))
        status = next(s for s in loop.subagents.statuses_for_session(key).values() if s.label == "after-unknown")
        assert status.as_dict()["origin_input_id"] is None

        await loop.sessions.state.reset(key)
        await save_completed_subagent(loop, "background-after-reset", key)
        next_label = "after-reset"
        await dispatch_and_wait(loop, system_result("background-after-reset"))
        status = next(s for s in loop.subagents.statuses_for_session(key).values() if s.label == "after-reset")
        assert status.as_dict()["origin_input_id"] is None
    finally:
        await loop.aclose()


async def test_legacy_missing_key_and_new_unknown_survive_persistence(tmp_path: Path) -> None:
    backend = provider()
    calls = 0

    async def respond(**kwargs):
        nonlocal calls
        if main_request(kwargs):
            calls += 1
            if calls == 1:
                return create_call("unknown")
        return LLMResponse(content="done")

    backend.chat_stream_with_retry = AsyncMock(side_effect=respond)
    loop = AgentLoop(bus=MessageBus(), provider=backend, workspace=tmp_path, model="test-model")
    try:
        await dispatch_and_wait(loop, user("no-id", None))
        status = next(iter(loop.subagents.statuses_for_session("websocket:chat").values()))
        sessions = loop.subagents.sessions
        assert sessions is not None
        child_key = sessions.key(status.task_id)
        child = await loop.sessions.state.get(child_key)
        assert child.metadata[TASK_METADATA_KEY]["origin_input_id"] is None
        with request_context(RequestContext(channel="websocket", chat_id="chat", session_key="websocket:chat")):
            public = json.loads(await SubagentTool(loop.subagents).execute(action="check", task_id=status.task_id))
        assert public["origin_input_id"] is None
        legacy = dict(child.metadata[TASK_METADATA_KEY])
        legacy.pop("origin_input_id")
        await loop.sessions.state.update_metadata(child_key, {TASK_METADATA_KEY: legacy})
        restored = sessions.status(status.task_id, "websocket:chat")
        assert restored is not None and not restored.origin_input_id_present
        assert "origin_input_id" not in restored.as_dict()
        await sessions.save(restored)
        child = await loop.sessions.state.get(child_key)
        assert "origin_input_id" not in child.metadata[TASK_METADATA_KEY]
    finally:
        await loop.aclose()

    restarted = AgentLoop(bus=MessageBus(), provider=backend, workspace=tmp_path, model="test-model")
    try:
        with request_context(RequestContext(channel="websocket", chat_id="chat", session_key="websocket:chat")):
            public = json.loads(await SubagentTool(restarted.subagents).execute(action="check", task_id=status.task_id))
        assert "origin_input_id" not in public
    finally:
        await restarted.aclose()


async def test_concurrent_sessions_keep_tool_snapshots_isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    backend = provider()
    seen: set[str] = set()
    both = asyncio.Event()

    async def respond(**kwargs):
        if not main_request(kwargs):
            return LLMResponse(content="child done")
        input_ids = [row.get("_meta", {}).get("input_id") for row in kwargs["messages"]]
        owner = next(value for value in input_ids if value in {"user:one", "user:two"})
        if owner not in seen:
            seen.add(owner)
            if len(seen) == 2:
                both.set()
            await asyncio.wait_for(both.wait(), 5)
            return create_call(owner)
        return LLMResponse(content="done")

    backend.chat_stream_with_retry = AsyncMock(side_effect=respond)
    loop = AgentLoop(bus=MessageBus(), provider=backend, workspace=tmp_path, model="test-model")
    tool_started = 0
    both_tools = asyncio.Event()
    run_inline = loop.subagents.run_inline

    async def overlap(*args, **kwargs):
        nonlocal tool_started
        tool_started += 1
        if tool_started == 2:
            both_tools.set()
        await asyncio.wait_for(both_tools.wait(), 5)
        return await run_inline(*args, **kwargs)

    monkeypatch.setattr(loop.subagents, "run_inline", overlap)
    try:
        await asyncio.gather(
            dispatch_and_wait(loop, user("one", "one", chat="one")),
            dispatch_and_wait(loop, user("two", "two", chat="two")),
        )
        for name in ("one", "two"):
            child = next(iter(loop.subagents.statuses_for_session(f"websocket:{name}").values()))
            assert child.origin_input_id == f"user:{name}"
    finally:
        await loop.aclose()


async def test_restart_does_not_treat_an_unconfirmed_request_as_consumed(tmp_path: Path) -> None:
    backend = provider()
    model_started, release, next_started = asyncio.Event(), asyncio.Event(), asyncio.Event()
    calls = 0

    async def interrupted(**kwargs):
        nonlocal calls
        if not main_request(kwargs):
            return LLMResponse(content="child done")
        calls += 1
        if calls == 1:
            model_started.set()
            await release.wait()
            return create_call("first")
        next_started.set()
        await asyncio.Event().wait()

    backend.chat_stream_with_retry = AsyncMock(side_effect=interrupted)
    loop = AgentLoop(bus=MessageBus(), provider=backend, workspace=tmp_path, model="test-model")
    key = "websocket:chat"
    try:
        await save_completed_subagent(loop, "late-result", key)
        await loop._dispatch_inbound(user("A", "turn-a"))
        await asyncio.wait_for(model_started.wait(), 5)
        await loop._dispatch_inbound(user("B", "turn-b"))
        release.set()
        await asyncio.wait_for(next_started.wait(), 10)
        saved = await loop.sessions.state.get(key)
        assert saved.metadata[RUNTIME_CHECKPOINT_KEY][CONSUMED_INPUT_ID_KEY] == "user:turn-a"
        assert saved.metadata[CONSUMED_INPUT_CURSOR_KEY] == {
            "generation": saved.generation, "input_id": "user:turn-b", "pending": True,
        }
        loop.preserve_inflight_turns_on_shutdown()
    finally:
        release.set()
        await loop.aclose()

    calls = 0

    async def resumed(**kwargs):
        nonlocal calls
        if main_request(kwargs):
            calls += 1
            if calls == 1:
                return create_call("restored")
        return LLMResponse(content="done")

    backend.chat_stream_with_retry = AsyncMock(side_effect=resumed)
    restarted = AgentLoop(bus=MessageBus(), provider=backend, workspace=tmp_path, model="test-model")
    try:
        await dispatch_and_wait(restarted, system_result("late-result"))
        child = next(s for s in restarted.subagents.statuses_for_session(key).values() if s.label == "restored")
        assert child.origin_input_id is None
        saved = await restarted.sessions.state.get(key)
        assert consumed_input_cursor(saved.metadata, saved.generation) is None
    finally:
        await restarted.aclose()


async def test_real_background_completion_starts_independent_run_with_consumed_origin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("nanobot.agent.loop._SUBAGENT_TERMINAL_WAIT_SECONDS", 0.05)
    backend = provider()
    child_started, release = asyncio.Event(), asyncio.Event()
    main_calls = 0

    async def respond(**kwargs):
        nonlocal main_calls
        if not main_request(kwargs):
            if any(row.get("role") == "user" and row.get("content") == "background" for row in kwargs["messages"]):
                child_started.set()
                await release.wait()
            return LLMResponse(content="child done")
        main_calls += 1
        if main_calls == 1:
            return create_call("background", wait=False)
        if main_calls == 3:
            return create_call("after-result")
        return LLMResponse(content="parent done")

    backend.chat_stream_with_retry = AsyncMock(side_effect=respond)
    bus = MessageBus()
    loop = AgentLoop(bus=bus, provider=backend, workspace=tmp_path, model="test-model")
    worker = asyncio.create_task(loop.run())
    key = "websocket:chat"
    try:
        await bus.publish_inbound(user("A", "turn-a"))
        await asyncio.wait_for(child_started.wait(), 5)
        async with asyncio.timeout(10):
            while key in loop._pending_queues:
                await asyncio.sleep(0.01)
        assert main_calls == 2
        release.set()
        async with asyncio.timeout(10):
            while True:
                statuses = loop.subagents.statuses_for_session(key)
                result = next((s for s in statuses.values() if s.label == "after-result"), None)
                if result is not None and result.state == "done" and key not in loop._pending_queues:
                    break
                await asyncio.sleep(0.01)
        assert {s.label: s.origin_input_id for s in statuses.values()} == {
            "background": "user:turn-a", "after-result": "user:turn-a",
        }
    finally:
        release.set()
        loop.stop()
        await asyncio.wait_for(worker, 10)


@pytest.mark.parametrize("archived", [False, True])
@pytest.mark.parametrize("turn,expected", [("turn-b", "user:turn-b"), (None, None)])
async def test_cancelled_input_replayed_in_later_model_request_advances_cursor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, turn: str | None, expected: str | None, archived: bool,
) -> None:
    backend = provider()
    create_after_replay = False
    main_messages = []

    async def respond(**kwargs):
        nonlocal create_after_replay
        if main_request(kwargs):
            main_messages.append(deepcopy(kwargs["messages"]))
            if create_after_replay:
                create_after_replay = False
                return create_call("after-replay")
        return LLMResponse(content="done")

    backend.chat_stream_with_retry = AsyncMock(side_effect=respond)
    loop = AgentLoop(bus=MessageBus(), provider=backend, workspace=tmp_path, model="test-model")
    saved = asyncio.Event()
    original = loop.sessions.state.update_metadata

    async def pause_after_commit(key, updates, **kwargs):
        await original(key, updates, **kwargs)
        cursor = updates.get(CONSUMED_INPUT_CURSOR_KEY)
        if isinstance(cursor, dict) and cursor.get("input_id") == expected and cursor.get("pending") is True:
            saved.set()
            await asyncio.Event().wait()

    try:
        await dispatch_and_wait(loop, user("A", "turn-a"))
        if archived:
            session = await loop.sessions.state.get("websocket:chat")
            session.commit_summary_checkpoint("Prior user request A")
            await loop.sessions.state.prepare_input(session)
        await save_completed_subagent(loop, "queued-result", "websocket:chat")
        monkeypatch.setattr(loop.sessions.state, "update_metadata", pause_after_commit)
        await loop._dispatch_inbound(user("B", turn))
        await asyncio.wait_for(saved.wait(), 5)
        worker = next(iter(loop._active_tasks["websocket:chat"]))
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)
        assert len(main_messages) == 1
        session = await loop.sessions.state.get("websocket:chat")
        assert session.metadata[CONSUMED_INPUT_CURSOR_KEY]["input_id"] == "user:turn-a"

        monkeypatch.setattr(loop.sessions.state, "update_metadata", original)
        create_after_replay = True
        await dispatch_and_wait(loop, system_result("queued-result"))
        assert any("B" in str(row.get("content")) for row in main_messages[1])
        status = next(s for s in loop.subagents.statuses_for_session("websocket:chat").values() if s.label == "after-replay")
        assert status.origin_input_id == expected
    finally:
        await loop.aclose()


async def test_crash_before_provider_dispatch_does_not_claim_unconsumed_input(tmp_path: Path) -> None:
    workspace, runtime = tmp_path / "workspace", tmp_path / "runtime"
    backend = provider()
    backend.chat_stream_with_retry = AsyncMock(return_value=LLMResponse(content="done"))
    loop = AgentLoop(bus=MessageBus(), provider=backend, workspace=workspace, model="test-model",
                     session_manager=SessionManager(workspace, sessions_root=runtime / "sessions"))
    key = "websocket:chat"
    try:
        await dispatch_and_wait(loop, user("A", "turn-a"))
        await save_completed_subagent(loop, "after-crash", key)
    finally:
        await loop.aclose()

    script = textwrap.dedent('''
        import asyncio
        import os
        import sys
        from pathlib import Path
        from unittest.mock import AsyncMock, MagicMock
        from nanobot.agent.loop import AgentLoop
        from nanobot.bus.events import InboundMessage
        from nanobot.bus.queue import MessageBus
        from nanobot.config.home import set_home_path
        from nanobot.providers.base import GenerationSettings, LLMResponse
        from nanobot.session.manager import SessionManager
        from nanobot.session.message_metadata import CONSUMED_INPUT_CURSOR_KEY

        async def main():
            backend = MagicMock(aclose=AsyncMock())
            backend.get_default_model.return_value = "test-model"
            backend.generation = GenerationSettings()
            backend.can_resume_conversation_state.return_value = False
            backend.chat_stream_with_retry = AsyncMock(return_value=LLMResponse(content="unexpected"))
            workspace, runtime = Path(sys.argv[1]), Path(sys.argv[2])
            set_home_path(runtime)
            loop = AgentLoop(bus=MessageBus(), provider=backend, workspace=workspace, model="test-model",
                             session_manager=SessionManager(workspace, sessions_root=runtime / "sessions"))
            update = loop.sessions.state.update_metadata

            async def crash_after_pending(key, updates, **kwargs):
                result = await update(key, updates, **kwargs)
                cursor = updates.get(CONSUMED_INPUT_CURSOR_KEY)
                if isinstance(cursor, dict) and cursor.get("input_id") == "user:turn-b" and cursor.get("pending") is True:
                    os._exit(73)
                return result

            loop.sessions.state.update_metadata = crash_after_pending
            message = InboundMessage(channel="websocket", sender_id="user", chat_id="chat", content="B",
                                     metadata={"webui_turn_id": "turn-b"})
            await loop._dispatch_inbound(message)
            await asyncio.gather(*loop._active_tasks[message.session_key])
            await loop.aclose()

        asyncio.run(main())
    ''')
    creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    child = subprocess.run([sys.executable, "-c", script, str(workspace), str(runtime)], capture_output=True, text=True,
                           timeout=30, creationflags=creationflags, check=False)
    assert child.returncode == 73, child.stderr
    reader = SessionManager(workspace, sessions_root=runtime / "sessions")
    try:
        raw = reader.read_session_metadata(key)
        assert raw is not None
        assert raw["metadata"][CONSUMED_INPUT_CURSOR_KEY]["pending"] is True
    finally:
        await reader.state.aclose()

    next_label = "recovered"
    replayed_messages = []

    async def respond(**kwargs):
        nonlocal next_label
        if main_request(kwargs) and next_label:
            replayed_messages.extend(deepcopy(kwargs["messages"]))
            label, next_label = next_label, ""
            return create_call(label)
        return LLMResponse(content="done")

    backend = provider()
    backend.chat_stream_with_retry = AsyncMock(side_effect=respond)
    restarted = AgentLoop(bus=MessageBus(), provider=backend, workspace=workspace, model="test-model",
                          session_manager=SessionManager(workspace, sessions_root=runtime / "sessions"))
    try:
        session = await restarted.sessions.state.get(key)
        assert consumed_input_cursor(session.metadata, session.generation) is None
        await dispatch_and_wait(restarted, system_result("after-crash"))
        status = next(s for s in restarted.subagents.statuses_for_session(key).values() if s.label == "recovered")
        assert any("B" in str(row.get("content")) for row in replayed_messages)
        assert status.origin_input_id == "user:turn-b"
    finally:
        await restarted.aclose()


@pytest.mark.parametrize("pending,expected", [(False, "user:turn-b"), (True, None)])
def test_recovery_prefers_newer_cursor_to_older_response_checkpoint(pending, expected) -> None:
    session = Session(key="websocket:chat")
    session.metadata[CONSUMED_INPUT_CURSOR_KEY] = {
        "generation": session.generation, "input_id": "user:turn-b", **({"pending": True} if pending else {}),
    }
    session.metadata[RUNTIME_CHECKPOINT_KEY] = {
        "phase": "awaiting_tools", CONSUMED_INPUT_ID_KEY: "user:turn-a",
        "assistant_message": {"role": "assistant", "content": "previous response"},
    }
    assert restore_runtime_checkpoint(session)
    assert consumed_input_cursor(session.metadata, session.generation) == expected


def test_pre_request_compaction_checkpoint_does_not_claim_consumption() -> None:
    session = Session(key="websocket:chat")
    session.metadata[RUNTIME_CHECKPOINT_KEY] = {"phase": "model_input", CONSUMED_INPUT_ID_KEY: "user:turn-a"}
    assert restore_runtime_checkpoint(session)
    assert consumed_input_cursor(session.metadata, session.generation) is None


def attributed_transcript(transcript: TranscriptInput) -> list[dict]:
    summary = transcript.session_summary
    messages = [{"role": "system", "content": summary["text"] if summary else "system"}, *transcript.history]
    if transcript.current_message is not None:
        messages.append({"role": "user", "content": transcript.current_message, "_meta": dict(transcript.input_metadata or {})})
    return messages


async def test_compacted_unconsumed_history_does_not_claim_older_origin(monkeypatch: pytest.MonkeyPatch) -> None:
    backend = provider()
    requests = []

    async def respond(**kwargs):
        requests.append(kwargs["messages"])
        return LLMResponse(content="done")

    backend.chat_stream_with_retry = AsyncMock(side_effect=respond)
    big_answer = "prior answer " * 2000
    monkeypatch.setattr(
        "nanobot.agent.context_governance.estimate_prompt_tokens_chain",
        lambda _provider, _model, messages, _tools: (
            (600, "test-counter") if any(message.get("content") == big_answer for message in messages)
            else (100, "test-counter")
        ),
    )
    metadata_a = {MODEL_INPUT_ROLE_KEY: True, "input_id": "user:turn-a"}
    metadata_b = {MODEL_INPUT_ROLE_KEY: True, "input_id": "user:turn-b"}
    record = AsyncMock()
    tools = MagicMock()
    tools.get_definitions.return_value = []
    await AgentRunner().run(make_run_spec(
        backend, model="test-model", tools=tools, max_iterations=1, max_tool_result_chars=8192,
        initial_messages=None,
        transcript_input=TranscriptInput(
            history=[
                {"role": "user", "content": "A", "_meta": metadata_a},
                {"role": "assistant", "content": big_answer},
                {"role": "user", "content": "B", "_meta": metadata_b},
            ],
            current_message="system result", input_metadata={MODEL_INPUT_ROLE_KEY: False},
        ),
        transcript_builder=attributed_transcript,
        consolidate_history=AsyncMock(return_value="summary of prior context"),
        context_window_tokens=1624, max_tokens=100,
        initial_consumed_input_id="user:turn-a", model_input_callback=record,
    ))
    assert all(row.get("content") != "B" for row in requests[0])
    assert record.await_args_list[-1].args == (None, True)


@pytest.mark.parametrize("pending_b,expected", [(True, "user:turn-b"), (False, None)])
async def test_resumed_and_full_request_must_agree_on_replayed_origin(pending_b: bool, expected: str | None) -> None:
    backend = provider()
    backend.can_resume_conversation_state.return_value = True
    observed = []

    async def respond(**kwargs):
        observed.append(kwargs["provider_context"].conversation_state.pending_messages)
        return LLMResponse(content="done")

    backend.chat_stream_with_retry = AsyncMock(side_effect=respond)
    a = {"role": "user", "content": "A", "_meta": {MODEL_INPUT_ROLE_KEY: True, "input_id": "user:turn-a"}}
    b = {"role": "user", "content": "B", "_meta": {MODEL_INPUT_ROLE_KEY: True, "input_id": "user:turn-b"}}
    state = ProviderConversationState(
        kind="openai_responses", provider="openai:test", model="test-model", version=1,
        payload={"items": []}, pending_messages=[b] if pending_b else [],
    )
    record = AsyncMock()
    tools = MagicMock()
    tools.get_definitions.return_value = []
    await AgentRunner().run(make_run_spec(
        backend, model="test-model", tools=tools, max_iterations=1, max_tool_result_chars=8192,
        initial_messages=None,
        transcript_input=TranscriptInput(
            history=[a, {"role": "assistant", "content": "done"}, b],
            current_message="system result", input_metadata={MODEL_INPUT_ROLE_KEY: False},
        ),
        transcript_builder=attributed_transcript, provider_state=state,
        initial_consumed_input_id="user:turn-a", model_input_callback=record,
    ))
    assert bool(observed[0]) is pending_b
    assert record.await_args_list[-1].args == (expected, True)


@pytest.mark.parametrize("resumable", [False, True])
async def test_adjacent_queued_inputs_keep_last_origin_across_tool_rounds(tmp_path: Path, resumable: bool) -> None:
    backend = provider()
    backend.can_resume_conversation_state.return_value = resumable
    provider_state = ProviderConversationState(
        kind="openai_responses", provider="openai:test", model="test-model", version=1, payload={"items": []},
    )
    pending = []
    entered, release = asyncio.Event(), asyncio.Event()
    calls = 0

    async def respond(**kwargs):
        nonlocal calls
        if not main_request(kwargs):
            return LLMResponse(content="child done")
        calls += 1
        context = kwargs["provider_context"]
        if context.conversation_state is not None:
            pending.extend(deepcopy(context.conversation_state.pending_messages))
        if calls == 1:
            entered.set()
            await release.wait()
            response = create_call("before-queue")
        elif calls in (2, 3):
            response = create_call(f"after-queue-{calls}")
        else:
            response = LLMResponse(content="done")
        if resumable:
            response.provider_state = provider_state
        return response

    backend.chat_stream_with_retry = AsyncMock(side_effect=respond)
    loop = AgentLoop(bus=MessageBus(), provider=backend, workspace=tmp_path, model="test-model")
    try:
        await loop._dispatch_inbound(user("A", "turn-a"))
        await asyncio.wait_for(entered.wait(), 5)
        await loop._dispatch_inbound(user("B", "turn-b"))
        await loop._dispatch_inbound(user("C", "turn-c"))
        release.set()
        await asyncio.wait_for(asyncio.gather(*loop._active_tasks["websocket:chat"]), 10)
        assert {s.label: s.origin_input_id for s in loop.subagents.statuses_for_session("websocket:chat").values()} == {
            "before-queue": "user:turn-a", "after-queue-2": "user:turn-c", "after-queue-3": "user:turn-c",
        }
        if resumable:
            pending_inputs = [row.get("_meta", {}).get("input_id") for row in pending if row.get("role") == "user"]
            assert pending_inputs[-1] == "user:turn-c"
    finally:
        release.set()
        await loop.aclose()


async def test_compaction_continuation_does_not_replace_consumed_user_origin(monkeypatch: pytest.MonkeyPatch) -> None:
    from nanobot.session.summary import SUMMARY_CONTINUATION_TEXT

    backend = provider()
    requests = []
    responses = [
        LLMResponse(content=None, tool_calls=[ToolCallRequest("first", "inspect", {})]),
        LLMResponse(content=None, tool_calls=[ToolCallRequest("second", "inspect", {})]),
        LLMResponse(content="done"),
    ]

    async def respond(**kwargs):
        requests.append(kwargs["messages"])
        return responses.pop(0)

    backend.chat_stream_with_retry = AsyncMock(side_effect=respond)
    monkeypatch.setattr(
        "nanobot.agent.context_governance.estimate_prompt_tokens_chain",
        lambda _provider, _model, messages, _tools: (
            (600, "test-counter")
            if any(m.get("role") == "tool" for m in messages)
            and any(m.get("role") == "system" and m.get("content") == "system" for m in messages)
            else (100, "test-counter")
        ),
    )
    tools = MagicMock()
    tools.get_definitions.return_value = []
    tools.execute = AsyncMock(return_value="tool result")
    record = AsyncMock()
    await AgentRunner().run(make_run_spec(
        backend, model="test-model", tools=tools, max_iterations=3, max_tool_result_chars=8192,
        initial_messages=None,
        transcript_input=TranscriptInput(
            history=[], current_message="A", input_metadata={MODEL_INPUT_ROLE_KEY: True, "input_id": "user:turn-a"},
        ),
        transcript_builder=attributed_transcript, consolidate_history=AsyncMock(return_value="summary of A"),
        context_window_tokens=1624, max_tokens=100, model_input_callback=record,
    ))
    assert any(row.get("content") == SUMMARY_CONTINUATION_TEXT for row in requests[1])
    assert [call.args for call in record.await_args_list if call.args[1]] == [("user:turn-a", True)] * 3


async def test_internal_continuation_with_resumable_state_keeps_origin(tmp_path: Path) -> None:
    backend = provider()
    backend.can_resume_conversation_state.return_value = True
    state = ProviderConversationState(
        kind="openai_responses", provider="openai:test", model="test-model", version=1, payload={"items": []},
    )
    main_calls = 0
    pending = []

    async def respond(**kwargs):
        nonlocal main_calls
        if not main_request(kwargs):
            return LLMResponse(content="child done")
        main_calls += 1
        context = kwargs["provider_context"]
        if context.conversation_state is not None:
            pending.extend(deepcopy(context.conversation_state.pending_messages))
        response = create_call("after-continue") if main_calls == 2 else LLMResponse(content="done")
        response.provider_state = state
        return response

    backend.chat_stream_with_retry = AsyncMock(side_effect=respond)
    loop = AgentLoop(bus=MessageBus(), provider=backend, workspace=tmp_path, model="test-model")
    try:
        await dispatch_and_wait(loop, user("A", "turn-a"))
        await dispatch_and_wait(loop, InboundMessage(
            channel="websocket", sender_id="system:recovery", chat_id="chat", content="Continue the interrupted request",
            metadata={"_internal_continuation": True, "_skip_user_persist": True},
        ))
        status = next(s for s in loop.subagents.statuses_for_session("websocket:chat").values() if s.label == "after-continue")
        assert any("Continue the interrupted" in str(row.get("content")) for row in pending)
        assert status.origin_input_id == "user:turn-a"
    finally:
        await loop.aclose()
