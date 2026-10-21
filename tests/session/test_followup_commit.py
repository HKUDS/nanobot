"""Follow-up consumption commits against the owner, not an old turn snapshot."""

import sqlite3
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.context import TranscriptInput
from nanobot.agent.loop import AgentLoop
from nanobot.agent.tools.context import RequestContext
from nanobot.bus.events import INBOUND_META_TURN_ID, InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import GenerationSettings, LLMResponse
from nanobot.runtime_context import public_history_message
from nanobot.session.manager import SessionManager
from nanobot.session.recovery import PENDING_FOLLOWUP_ID_KEY, pending_followups
from nanobot.webui.recovery import RecoveryCoordinator


def _loop(sessions):
    loop = AgentLoop.__new__(AgentLoop)
    loop.sessions = sessions
    return loop


def _input(text, turn_id):
    return InboundMessage(
        channel="websocket", sender_id="user", chat_id="chat", content=text,
        timestamp=datetime(2026, 10, 18, 19, 0, 0),
        metadata={INBOUND_META_TURN_ID: turn_id},
    )


@pytest.mark.parametrize("count", [1, 2])
@pytest.mark.parametrize("leave_unconsumed", [False, True])
async def test_late_consumption_commits_history_and_only_its_ids(tmp_path, monkeypatch, count, leave_unconsumed):
    monkeypatch.setattr("nanobot.webui.transcript.get_webui_dir", lambda: tmp_path / "webui")
    sessions = SessionManager(tmp_path / "workspace", sessions_root=tmp_path / "sessions")
    state = sessions.state
    try:
        draft = await state.get("websocket:chat")
        draft.add_message("user", "initial input")
        await state.prepare_input(draft)
        consumed = []
        for index in range(count):
            message = _input(f"follow-up {index}", f"input-{index}")
            consumed.append(await state.queue_followup(draft.key, message))
        await state.checkpoint_view(draft, {"phase": "final_response"})
        _loop(sessions)._save_turn(draft, [
            *[
                {"role": "user", "content": f"follow-up {index}", PENDING_FOLLOWUP_ID_KEY: identifier}
                for index, identifier in enumerate(consumed)
            ],
            {"role": "assistant", "content": "completed answer"},
        ], skip=0)
        if leave_unconsumed:
            await state.queue_followup(draft.key, _input("arrived after model boundary", "late-input"))
        await state.finish_turn(draft)
        committed = await state.get(draft.key)
        expected = ["arrived after model boundary"] if leave_unconsumed else []
        assert [item.content for item in pending_followups(committed)] == expected
        assert [item["content"] for item in committed.messages] == [
            "initial input", *[f"follow-up {index}" for index in range(count)], "completed answer",
        ]
    finally:
        await state.aclose()

    reopened = SessionManager(tmp_path / "workspace", sessions_root=tmp_path / "sessions")
    try:
        bus = MessageBus()
        await RecoveryCoordinator(reopened, bus).scan()
        queued = []
        while not bus.inbound.empty():
            queued.append(bus.inbound.get_nowait().content)
        assert queued == expected
        assert (await reopened.state.get(draft.key)).messages == committed.messages
    finally:
        await reopened.state.aclose()


async def test_failed_followup_commit_rolls_back_history_and_ack_then_can_retry(tmp_path):
    sessions = SessionManager(tmp_path / "workspace", sessions_root=tmp_path / "sessions")
    state = sessions.state
    try:
        draft = await state.get("websocket:chat")
        draft.add_message("user", "initial input")
        await state.prepare_input(draft)
        identifier = await state.queue_followup(draft.key, _input("consumed input", "follow-up"))
        _loop(sessions)._save_turn(draft, [
            {"role": "user", "content": "consumed input", PENDING_FOLLOWUP_ID_KEY: identifier},
            {"role": "assistant", "content": "completed answer"},
        ], skip=0)
        with sqlite3.connect(sessions._store.path) as db:
            db.execute("""CREATE TRIGGER reject_ack BEFORE DELETE ON pending_inputs
                          BEGIN SELECT RAISE(ABORT, 'failed follow-up commit'); END""")
        with pytest.raises(sqlite3.IntegrityError, match="failed follow-up commit"):
            await state.finish_turn(draft)
        # Both the durable snapshot and published cache remain at the pre-commit boundary.
        for stored in (sessions.read_session_snapshot(draft.key), state.peek(draft.key)):
            assert [row["content"] for row in stored.messages] == ["initial input"]
            assert [item.content for item in pending_followups(stored)] == ["consumed input"]
        with sqlite3.connect(sessions._store.path) as db:
            db.execute("DROP TRIGGER reject_ack")
        await state.finish_turn(draft)
        committed = sessions.read_session_snapshot(draft.key)
        assert [row["content"] for row in committed.messages] == [
            "initial input", "consumed input", "completed answer",
        ]
        assert pending_followups(committed) == []
    finally:
        await state.aclose()


async def test_recovered_input_keeps_admission_identity_and_timestamp(tmp_path):
    sessions = SessionManager(tmp_path / "workspace", sessions_root=tmp_path / "sessions")
    state = sessions.state
    message = _input("queued input", "original-input")
    try:
        draft = await state.get(message.session_key)
        await state.queue_followup(draft.key, message)
        recovered = pending_followups(await state.get(draft.key))[0]
        assert recovered.timestamp == message.timestamp
        assert recovered.metadata[INBOUND_META_TURN_ID] == "original-input"
        assert await _loop(sessions)._persist_user_message_early(recovered, draft)
        row = (await state.get(draft.key)).messages[-1]
        assert row["timestamp"] == message.timestamp.isoformat()
        assert row[INBOUND_META_TURN_ID] == "original-input"
        assert pending_followups(await state.get(draft.key)) == []
    finally:
        await state.aclose()


async def test_injected_inputs_keep_their_own_identity_through_runner_and_commit(tmp_path):
    import asyncio

    provider = MagicMock(aclose=AsyncMock())
    provider.get_default_model.return_value = "test-model"
    provider.generation = GenerationSettings()
    provider.chat_stream_with_retry = AsyncMock(return_value=LLMResponse(content="completed answer"))
    loop = AgentLoop(bus=MessageBus(), provider=provider, workspace=tmp_path / "workspace", model="test-model")
    loop.sessions = SessionManager(tmp_path / "workspace", sessions_root=tmp_path / "sessions")
    try:
        draft = await loop.sessions.state.get("websocket:chat")
        draft.add_message("user", "initial input")
        await loop.sessions.state.prepare_input(draft)
        queue = asyncio.Queue()
        for turn_id in ("first-input", "second-input"):
            message = _input("intentionally identical text", turn_id)
            identifier = await loop.sessions.state.queue_followup(draft.key, message)
            message.metadata[PENDING_FOLLOWUP_ID_KEY] = identifier
            queue.put_nowait(message)
        runtime = loop.llm_runtime()
        result = await loop._run_agent_loop(
            TranscriptInput(history=draft.get_history(), current_message=None),
            runtime=runtime, session=draft, pending_queue=queue,
            request_context=RequestContext(
                channel="websocket", chat_id="chat", session_key=draft.key,
                turn_id="active-run", runtime=runtime,
            ),
        )
        loop._save_turn(draft, result.messages, skip=2)
        await loop.sessions.state.finish_turn(draft)
        stored = await loop.sessions.state.get(draft.key)
        injected = [row for row in stored.messages if row.get("role") == "user"][1:]
        assert [public_history_message(row)["content"] for row in injected] == ["intentionally identical text"] * 2
        assert [row[INBOUND_META_TURN_ID] for row in injected] == ["first-input", "second-input"]
        assert [row["timestamp"] for row in injected] == ["2026-10-18T19:00:00"] * 2
        assert pending_followups(stored) == []
        provider.chat_stream_with_retry.assert_awaited_once()
    finally:
        await loop.aclose()
