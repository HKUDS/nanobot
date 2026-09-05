from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from nanobot.bus.events import InboundMessage
from nanobot.bus.outbound_events import RecoveryStateEvent, SessionUpdatedEvent
from nanobot.bus.queue import MessageBus
from nanobot.session.manager import Session, SessionManager
from nanobot.session.recovery import (
    PENDING_FOLLOWUPS_KEY,
    PENDING_USER_TURN_KEY,
    RECOVERY_METADATA_KEY,
    RUNTIME_CHECKPOINT_KEY,
    RecoveryActionError,
    RecoveryCoordinator,
    acknowledge_pending_followups,
    pending_followups,
    record_pending_followup,
)
from nanobot.webui import session_list_index, transcript


def _persist(manager: SessionManager, session: Session) -> None:
    session.metadata["webui"] = True
    manager.save(session)


def _coordinator(workspace: Path) -> tuple[RecoveryCoordinator, MessageBus, SessionManager]:
    bus = MessageBus()
    sessions = SessionManager(workspace)
    return RecoveryCoordinator(sessions, bus), bus, sessions


@pytest.mark.asyncio
async def test_restart_before_model_call_waits_for_confirmation(tmp_path: Path) -> None:
    sessions = SessionManager(tmp_path)
    session = sessions.get_or_create("websocket:chat")
    session.messages.append({"role": "user", "content": "finish this"})
    session.metadata[PENDING_USER_TURN_KEY] = True
    _persist(sessions, session)

    coordinator, bus, restarted = _coordinator(tmp_path)
    await coordinator.scan()

    assert bus.inbound.empty()
    restored = restarted.get_or_create("websocket:chat")
    assert restored.metadata[PENDING_USER_TURN_KEY] is True
    assert restored.metadata[RECOVERY_METADATA_KEY]["status"] == "awaiting_user"
    assert restored.metadata[RECOVERY_METADATA_KEY]["reason"] == "restart_requires_confirmation"


@pytest.mark.asyncio
async def test_stale_incomplete_transcript_waits_for_confirmation(tmp_path: Path, monkeypatch) -> None:
    """A materialized shutdown must not reappear as an endless Working state."""
    sessions = SessionManager(tmp_path)
    session = sessions.get_or_create("websocket:chat")
    _persist(sessions, session)
    monkeypatch.setattr(
        "nanobot.webui.transcript.has_unfinished_transcript_tail",
        lambda _key: True,
    )

    coordinator, bus, restarted = _coordinator(tmp_path)
    await coordinator.scan()

    assert bus.inbound.empty()
    state = restarted.get_or_create("websocket:chat").metadata[RECOVERY_METADATA_KEY]
    assert state["status"] == "awaiting_user"
    assert state["reason"] == "interrupted_without_checkpoint"
    event = bus.outbound.get_nowait().event
    assert isinstance(event, RecoveryStateEvent)
    assert event.status == "awaiting_user"


@pytest.mark.asyncio
async def test_materialized_interruption_can_continue_from_saved_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Older shutdowns may have cleared the checkpoint after saving partial history."""
    sessions = SessionManager(tmp_path)
    session = sessions.get_or_create("websocket:chat")
    session.messages.extend(
        [
            {"role": "user", "content": "research this"},
            {"role": "assistant", "content": "I will check."},
            {"role": "tool", "tool_call_id": "search-1", "content": "saved result"},
        ]
    )
    _persist(sessions, session)
    monkeypatch.setattr(
        "nanobot.webui.transcript.has_unfinished_transcript_tail",
        lambda _key: True,
    )

    coordinator, bus, restarted = _coordinator(tmp_path)
    await coordinator.scan()

    state = restarted.get_or_create("websocket:chat").metadata[RECOVERY_METADATA_KEY]
    assert state["status"] == "awaiting_user"
    assert state["reason"] == "interrupted_with_saved_context"
    assert "can_continue" not in state
    event = bus.outbound.get_nowait().event
    assert isinstance(event, RecoveryStateEvent)
    assert event.can_continue is None

    await coordinator.handle_action(
        "continue",
        {"chat_id": "chat", "recovery_id": state["recovery_id"]},
    )

    continuation = bus.inbound.get_nowait()
    assert continuation.session_key_override == "websocket:chat"


@pytest.mark.asyncio
async def test_transcript_only_interruption_is_discovered_without_materializing_completed_history(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    webui_dir = tmp_path / "webui"
    webui_dir.mkdir()
    monkeypatch.setattr(session_list_index, "get_webui_dir", lambda: webui_dir)
    monkeypatch.setattr(transcript, "get_webui_dir", lambda: webui_dir)
    unfinished_key = "websocket:unfinished"
    completed_key = "websocket:completed"
    (webui_dir / f"{SessionManager.safe_key(unfinished_key)}.jsonl").write_text(
        '{"event":"user","chat_id":"unfinished","text":"keep going"}\n'
        '{"event":"message","chat_id":"unfinished","kind":"progress","text":"Working"}\n',
        encoding="utf-8",
    )
    (webui_dir / f"{SessionManager.safe_key(completed_key)}.jsonl").write_text(
        '{"event":"user","chat_id":"completed","text":"done"}\n'
        '{"event":"message","chat_id":"completed","text":"finished"}\n'
        '{"event":"turn_end","chat_id":"completed"}\n',
        encoding="utf-8",
    )
    coordinator, bus, sessions = _coordinator(tmp_path / "workspace")

    await coordinator.scan()

    restored = sessions.get_or_create(unfinished_key)
    assert restored.metadata[RECOVERY_METADATA_KEY]["status"] == "awaiting_user"
    assert restored.metadata[RECOVERY_METADATA_KEY]["reason"] == "interrupted_without_checkpoint"
    assert restored.metadata[RECOVERY_METADATA_KEY]["can_continue"] is False
    assert sessions.read_session_metadata(completed_key) is None
    event = bus.outbound.get_nowait().event
    assert isinstance(event, RecoveryStateEvent)
    assert event.status == "awaiting_user"
    assert event.can_continue is False
    assert bus.outbound.get_nowait().event.scope == "thread"
    assert bus.outbound.empty()

    with pytest.raises(RecoveryActionError, match="context is unavailable"):
        await coordinator.handle_action(
            "continue",
            {"chat_id": "unfinished", "recovery_id": event.recovery_id},
        )


@pytest.mark.asyncio
async def test_scan_loads_only_sessions_that_need_webui_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sessions = SessionManager(tmp_path)
    for key in ("telegram:idle", "discord:pending", "websocket:idle"):
        session = sessions.get_or_create(key)
        if key == "discord:pending":
            session.metadata[PENDING_USER_TURN_KEY] = True
        _persist(sessions, session)
    pending = sessions.get_or_create("websocket:pending")
    pending.metadata[PENDING_USER_TURN_KEY] = True
    _persist(sessions, pending)

    coordinator, _, restarted = _coordinator(tmp_path)
    loaded: list[str] = []
    get_or_create = restarted.get_or_create_async

    async def tracked_get_or_create(key: str) -> Session:
        loaded.append(key)
        return await get_or_create(key)

    monkeypatch.setattr(restarted, "get_or_create_async", tracked_get_or_create)
    monkeypatch.setattr(
        "nanobot.webui.transcript.has_unfinished_transcript_tail",
        lambda _key: False,
    )

    await coordinator.scan()

    assert loaded == ["websocket:pending"]


@pytest.mark.asyncio
async def test_live_turn_followup_survives_restart_until_it_is_committed(tmp_path: Path) -> None:
    """A message injected mid-turn is not lost between checkpoints."""
    sessions = SessionManager(tmp_path)
    session = sessions.get_or_create("websocket:chat")
    _persist(sessions, session)
    followup_id = record_pending_followup(
        session,
        InboundMessage(
            channel="websocket",
            sender_id="user",
            chat_id="chat",
            content="also check the logs",
            metadata={"webui": True},
        ),
    )
    assert followup_id is not None
    sessions.save(session)

    coordinator, bus, restarted = _coordinator(tmp_path)
    await coordinator.scan()

    queued = bus.inbound.get_nowait()
    assert queued.content == "also check the logs"
    assert queued.metadata["_recovery_followup_id"] == followup_id
    restored = restarted.get_or_create("websocket:chat")
    assert len(pending_followups(restored)) == 1

    acknowledge_pending_followups(restored, [followup_id])
    assert PENDING_FOLLOWUPS_KEY not in restored.metadata


def test_followup_journal_keeps_every_uncommitted_message(tmp_path: Path) -> None:
    """A live queue limit must never truncate durable WebUI follow-ups."""
    sessions = SessionManager(tmp_path)
    session = sessions.get_or_create("websocket:chat")
    followup_ids = [
        record_pending_followup(
            session,
            InboundMessage(
                channel="websocket",
                sender_id="user",
                chat_id="chat",
                content=f"follow-up-{index}",
                metadata={"webui": True},
            ),
        )
        for index in range(21)
    ]

    assert all(followup_ids)
    sessions.save(session)
    restarted = SessionManager(tmp_path)
    restored = restarted.get_or_create("websocket:chat")
    assert [message.content for message in pending_followups(restored)] == [
        f"follow-up-{index}" for index in range(21)
    ]


def test_requeued_followup_preserves_its_journal_id(tmp_path: Path) -> None:
    """Routing a recovered follow-up into a live turn must remain idempotent."""
    sessions = SessionManager(tmp_path)
    session = sessions.get_or_create("websocket:chat")
    original_id = record_pending_followup(
        session,
        InboundMessage(
            channel="websocket",
            sender_id="user",
            chat_id="chat",
            content="also check the logs",
            metadata={"webui": True},
        ),
    )
    assert original_id is not None

    recovered = pending_followups(session)[0]
    assert record_pending_followup(session, recovered) == original_id
    assert [record["id"] for record in session.metadata[PENDING_FOLLOWUPS_KEY]] == [
        original_id
    ]


@pytest.mark.asyncio
async def test_completed_tools_wait_for_confirmation_after_restart(tmp_path: Path) -> None:
    sessions = SessionManager(tmp_path)
    session = sessions.get_or_create("websocket:chat")
    session.messages.append({"role": "user", "content": "inspect"})
    session.metadata[PENDING_USER_TURN_KEY] = True
    session.metadata[RUNTIME_CHECKPOINT_KEY] = {
        "phase": "tools_completed",
        "assistant_message": {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "call-1", "function": {"name": "read_file"}}],
        },
        "completed_tool_results": [
            {
                "role": "tool",
                "tool_call_id": "call-1",
                "name": "read_file",
                "content": "saved result",
            }
        ],
        "pending_tool_calls": [],
    }
    _persist(sessions, session)

    coordinator, bus, restarted = _coordinator(tmp_path)
    await coordinator.scan()

    assert bus.inbound.empty()
    restored = restarted.get_or_create("websocket:chat")
    assert restored.messages[-1]["content"] == "saved result"
    assert RUNTIME_CHECKPOINT_KEY not in restored.metadata
    assert restored.metadata[RECOVERY_METADATA_KEY]["status"] == "awaiting_user"


@pytest.mark.asyncio
async def test_uncertain_tool_is_never_replayed(tmp_path: Path) -> None:
    sessions = SessionManager(tmp_path)
    session = sessions.get_or_create("websocket:chat")
    session.messages.append({"role": "user", "content": "send it"})
    session.metadata[PENDING_USER_TURN_KEY] = True
    session.metadata[RUNTIME_CHECKPOINT_KEY] = {
        "phase": "awaiting_tools",
        "assistant_message": {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "call-1", "function": {"name": "send_email"}}],
        },
        "completed_tool_results": [],
        "pending_tool_calls": [
            {"id": "call-1", "function": {"name": "send_email"}}
        ],
    }
    _persist(sessions, session)

    coordinator, bus, restarted = _coordinator(tmp_path)
    await coordinator.scan()

    assert bus.inbound.empty()
    restored = restarted.get_or_create("websocket:chat")
    assert restored.metadata[RECOVERY_METADATA_KEY]["status"] == "awaiting_user"
    assert restored.metadata[RECOVERY_METADATA_KEY]["reason"] == "tool_state_unknown"
    assert restored.messages[-1]["_recovery_interrupted"] is True
    event = bus.outbound.get_nowait().event
    assert isinstance(event, RecoveryStateEvent)
    assert event.status == "awaiting_user"


@pytest.mark.asyncio
async def test_unknown_checkpoint_waits_for_confirmation(tmp_path: Path) -> None:
    """Malformed or newer checkpoint phases fail closed pending confirmation."""
    sessions = SessionManager(tmp_path)
    session = sessions.get_or_create("websocket:chat")
    session.messages.append({"role": "user", "content": "deploy it"})
    session.metadata[PENDING_USER_TURN_KEY] = True
    session.metadata[RUNTIME_CHECKPOINT_KEY] = {"phase": "future_phase"}
    _persist(sessions, session)

    coordinator, bus, restarted = _coordinator(tmp_path)
    await coordinator.scan()

    assert bus.inbound.empty()
    restored = restarted.get_or_create("websocket:chat")
    assert restored.metadata[RECOVERY_METADATA_KEY]["status"] == "awaiting_user"
    assert restored.metadata[RECOVERY_METADATA_KEY]["reason"] == "checkpoint_unknown"
    assert restored.metadata[RECOVERY_METADATA_KEY]["can_continue"] is False
    assert RUNTIME_CHECKPOINT_KEY not in restored.metadata
    assert PENDING_USER_TURN_KEY not in restored.metadata
    assert [message["role"] for message in restored.messages] == ["user", "assistant"]
    assert restored.messages[-1]["_recovery_interrupted"] is True

    with pytest.raises(RecoveryActionError, match="context is unavailable"):
        await coordinator.handle_action(
            "continue",
            {
                "chat_id": "chat",
                "recovery_id": restored.metadata[RECOVERY_METADATA_KEY]["recovery_id"],
            },
        )

    dismissed = await coordinator.handle_action(
        "dismiss",
        {
            "chat_id": "chat",
            "recovery_id": restored.metadata[RECOVERY_METADATA_KEY]["recovery_id"],
        },
    )
    assert dismissed["status"] == "recovered"


@pytest.mark.asyncio
async def test_malformed_checkpoint_can_always_be_dismissed(tmp_path: Path) -> None:
    """Corrupt private state must not trap the user in a failed recovery notice."""
    sessions = SessionManager(tmp_path)
    session = sessions.get_or_create("websocket:chat")
    session.messages.append({"role": "user", "content": "deploy it"})
    session.metadata[PENDING_USER_TURN_KEY] = True
    session.metadata[RUNTIME_CHECKPOINT_KEY] = {
        "phase": "future_phase",
        "assistant_message": "invalid",
        "completed_tool_results": 3,
        "pending_tool_calls": [{"id": "call-1", "function": "invalid"}],
    }
    _persist(sessions, session)

    coordinator, _, restarted = _coordinator(tmp_path)
    await coordinator.scan()
    restored = restarted.get_or_create("websocket:chat")
    state = restored.metadata[RECOVERY_METADATA_KEY]

    result = await coordinator.handle_action(
        "dismiss",
        {"chat_id": "chat", "recovery_id": state["recovery_id"]},
    )

    assert result["status"] == "recovered"
    assert RUNTIME_CHECKPOINT_KEY not in restored.metadata


@pytest.mark.asyncio
async def test_known_but_malformed_checkpoint_cannot_continue(tmp_path: Path) -> None:
    """A known phase does not make corrupt tool state safe to resume."""
    sessions = SessionManager(tmp_path)
    session = sessions.get_or_create("websocket:chat")
    session.messages.append({"role": "user", "content": "send it"})
    session.metadata[PENDING_USER_TURN_KEY] = True
    session.metadata[RUNTIME_CHECKPOINT_KEY] = {
        "phase": "tools_completed",
        "assistant_message": {"role": "assistant", "content": "working"},
        "completed_tool_results": "missing durable results",
        "pending_tool_calls": [],
    }
    _persist(sessions, session)

    coordinator, _, restarted = _coordinator(tmp_path)
    await coordinator.scan()
    restored = restarted.get_or_create("websocket:chat")
    state = restored.metadata[RECOVERY_METADATA_KEY]

    assert state["status"] == "awaiting_user"
    assert state["reason"] == "checkpoint_invalid"
    assert state["can_continue"] is False
    with pytest.raises(RecoveryActionError, match="context is unavailable"):
        await coordinator.handle_action(
            "continue",
            {"chat_id": "chat", "recovery_id": state["recovery_id"]},
        )


@pytest.mark.asyncio
async def test_malformed_final_response_is_not_reported_as_restored(tmp_path: Path) -> None:
    sessions = SessionManager(tmp_path)
    session = sessions.get_or_create("websocket:chat")
    session.messages.append({"role": "user", "content": "answer"})
    session.metadata[PENDING_USER_TURN_KEY] = True
    session.metadata[RUNTIME_CHECKPOINT_KEY] = {
        "phase": "final_response",
        "assistant_message": "not an answer row",
        "completed_tool_results": [],
        "pending_tool_calls": [],
    }
    _persist(sessions, session)

    coordinator, _, restarted = _coordinator(tmp_path)
    await coordinator.scan()

    state = restarted.get_or_create("websocket:chat").metadata[RECOVERY_METADATA_KEY]
    assert state["status"] == "awaiting_user"
    assert state["reason"] == "checkpoint_invalid"
    assert state["can_continue"] is False
    restored = restarted.get_or_create("websocket:chat")
    assert RUNTIME_CHECKPOINT_KEY not in restored.metadata
    assert PENDING_USER_TURN_KEY not in restored.metadata
    assert [message["role"] for message in restored.messages] == ["user", "assistant"]
    assert restored.messages[-1]["_recovery_interrupted"] is True
    assert all("tool_calls" not in message for message in restored.messages)


@pytest.mark.asyncio
async def test_checkpoint_with_missing_tool_result_cannot_continue(tmp_path: Path) -> None:
    """Never resume when persisted results do not cover every requested tool."""
    sessions = SessionManager(tmp_path)
    session = sessions.get_or_create("websocket:chat")
    session.messages.append({"role": "user", "content": "send both"})
    session.metadata[PENDING_USER_TURN_KEY] = True
    session.metadata[RUNTIME_CHECKPOINT_KEY] = {
        "phase": "tools_completed",
        "assistant_message": {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "call-1", "function": {"name": "send_email"}},
                {"id": "call-2", "function": {"name": "send_email"}},
            ],
        },
        "completed_tool_results": [
            {
                "role": "tool",
                "tool_call_id": "call-1",
                "name": "send_email",
                "content": "sent",
            }
        ],
        "pending_tool_calls": [],
    }
    _persist(sessions, session)

    coordinator, _, restarted = _coordinator(tmp_path)
    await coordinator.scan()

    restored = restarted.get_or_create("websocket:chat")
    state = restored.metadata[RECOVERY_METADATA_KEY]
    assert state["status"] == "awaiting_user"
    assert state["reason"] == "checkpoint_invalid"
    assert state["can_continue"] is False
    assert RUNTIME_CHECKPOINT_KEY not in restored.metadata
    assert PENDING_USER_TURN_KEY not in restored.metadata
    assert [message["role"] for message in restored.messages] == ["user", "assistant"]
    assert restored.messages[-1]["_recovery_interrupted"] is True
    assert all("tool_calls" not in message for message in restored.messages)


@pytest.mark.asyncio
async def test_empty_final_response_is_not_reported_as_restored(tmp_path: Path) -> None:
    sessions = SessionManager(tmp_path)
    session = sessions.get_or_create("websocket:chat")
    session.messages.append({"role": "user", "content": "answer"})
    session.metadata[PENDING_USER_TURN_KEY] = True
    session.metadata[RUNTIME_CHECKPOINT_KEY] = {
        "phase": "final_response",
        "assistant_message": {"role": "assistant", "content": ""},
        "completed_tool_results": [],
        "pending_tool_calls": [],
    }
    _persist(sessions, session)

    coordinator, _, restarted = _coordinator(tmp_path)
    await coordinator.scan()

    state = restarted.get_or_create("websocket:chat").metadata[RECOVERY_METADATA_KEY]
    assert state["status"] == "awaiting_user"
    assert state["reason"] == "checkpoint_invalid"
    assert state["can_continue"] is False


@pytest.mark.asyncio
async def test_final_answer_is_restored_without_model_call(tmp_path: Path) -> None:
    sessions = SessionManager(tmp_path)
    session = sessions.get_or_create("websocket:chat")
    session.messages.append({"role": "user", "content": "answer"})
    session.metadata[PENDING_USER_TURN_KEY] = True
    session.metadata[RUNTIME_CHECKPOINT_KEY] = {
        "phase": "final_response",
        "assistant_message": {"role": "assistant", "content": "already finished"},
        "completed_tool_results": [],
        "pending_tool_calls": [],
    }
    _persist(sessions, session)

    coordinator, bus, restarted = _coordinator(tmp_path)
    await coordinator.scan()

    assert bus.inbound.empty()
    restored = restarted.get_or_create("websocket:chat")
    assert restored.messages[-1]["content"] == "already finished"
    first = bus.outbound.get_nowait().event
    second = bus.outbound.get_nowait().event
    assert isinstance(first, RecoveryStateEvent) and first.status == "recovered"
    assert isinstance(second, SessionUpdatedEvent)


@pytest.mark.asyncio
async def test_explicit_recovery_continue_queues_once(tmp_path: Path) -> None:
    sessions = SessionManager(tmp_path)
    session = sessions.get_or_create("websocket:chat")
    session.messages.append({"role": "user", "content": "continue"})
    session.metadata[PENDING_USER_TURN_KEY] = True
    _persist(sessions, session)

    coordinator, bus, restarted = _coordinator(tmp_path)
    await coordinator.scan()
    assert bus.inbound.empty()

    state = restarted.get_or_create("websocket:chat").metadata[RECOVERY_METADATA_KEY]
    result = await coordinator.handle_action(
        "continue",
        {"chat_id": "chat", "recovery_id": state["recovery_id"]},
    )
    assert result["status"] == "resuming"
    assert bus.inbound.get_nowait().metadata["_webui_recovery_id"] == state["recovery_id"]


@pytest.mark.asyncio
async def test_new_user_message_supersedes_waiting_recovery(tmp_path: Path) -> None:
    coordinator, bus, sessions = _coordinator(tmp_path)
    session = sessions.get_or_create("websocket:chat")
    session.messages.append({"role": "user", "content": "old request"})
    session.metadata[PENDING_USER_TURN_KEY] = True
    _persist(sessions, session)
    await coordinator.scan()

    newer = InboundMessage(
        channel="websocket",
        sender_id="user",
        chat_id="chat",
        content="new request",
    )
    assert await coordinator.admit(newer) is True
    restored = sessions.get_or_create("websocket:chat")
    assert restored.messages[-1]["_recovery_interrupted"] is True
    assert sum(
        message.get("_recovery_interrupted") is True
        for message in restored.messages
    ) == 1
    assert restored.metadata[RECOVERY_METADATA_KEY]["reason"] == "superseded"


@pytest.mark.asyncio
async def test_new_user_message_cancels_active_recovery_task(tmp_path: Path) -> None:
    coordinator, bus, sessions = _coordinator(tmp_path)
    session = sessions.get_or_create("websocket:chat")
    session.metadata[RECOVERY_METADATA_KEY] = {
        "status": "resuming",
        "recovery_id": "active",
        "attempts": 1,
    }
    _persist(sessions, session)

    started = asyncio.Event()

    async def _active_recovery() -> None:
        started.set()
        await asyncio.Event().wait()

    task = asyncio.create_task(_active_recovery())
    await started.wait()
    coordinator.register_recovery_task("websocket:chat", task)

    newer = InboundMessage(
        channel="websocket",
        sender_id="user",
        chat_id="chat",
        content="new request",
    )
    assert await coordinator.admit(newer) is True
    assert task.cancelled()
    restored = sessions.get_or_create("websocket:chat")
    assert restored.metadata[RECOVERY_METADATA_KEY]["reason"] == "superseded"
    assert restored.messages[-1]["_recovery_interrupted"] is True
    first = bus.outbound.get_nowait().event
    second = bus.outbound.get_nowait().event
    assert isinstance(first, RecoveryStateEvent)
    assert isinstance(second, SessionUpdatedEvent)
    assert bus.outbound.empty()


@pytest.mark.asyncio
async def test_recovery_action_rejects_stale_page_and_continues_current_state(
    tmp_path: Path,
) -> None:
    coordinator, bus, sessions = _coordinator(tmp_path)
    session = sessions.get_or_create("websocket:chat")
    session.metadata[RECOVERY_METADATA_KEY] = {
        "status": "awaiting_user",
        "recovery_id": "current",
        "attempts": 0,
    }
    _persist(sessions, session)

    with pytest.raises(RecoveryActionError, match="stale"):
        await coordinator.handle_action(
            "continue",
            {"chat_id": "chat", "recovery_id": "old"},
        )

    result = await coordinator.handle_action(
        "continue",
        {"chat_id": "chat", "recovery_id": "current"},
    )
    assert result["status"] == "resuming"
    assert bus.inbound.get_nowait().metadata["_webui_recovery_id"] == "current"


@pytest.mark.asyncio
async def test_persisted_completion_wins_over_stale_resuming_marker(tmp_path: Path) -> None:
    sessions = SessionManager(tmp_path)
    session = sessions.get_or_create("websocket:chat")
    session.messages.extend(
        [
            {"role": "user", "content": "work"},
            {"role": "assistant", "content": "done"},
        ]
    )
    session.metadata[RECOVERY_METADATA_KEY] = {
        "status": "resuming",
        "recovery_id": "recovery",
        "attempts": 1,
        "resume_message_count": 1,
    }
    _persist(sessions, session)

    coordinator, bus, restarted = _coordinator(tmp_path)
    await coordinator.scan()

    assert bus.inbound.empty()
    state = restarted.get_or_create("websocket:chat").metadata[RECOVERY_METADATA_KEY]
    assert state["status"] == "recovered"
    assert state["reason"] == "committed"


@pytest.mark.asyncio
async def test_dismiss_does_not_queue_work(tmp_path: Path) -> None:
    coordinator, bus, sessions = _coordinator(tmp_path)
    session = sessions.get_or_create("websocket:chat")
    session.metadata[RECOVERY_METADATA_KEY] = {
        "status": "awaiting_user",
        "recovery_id": "current",
        "attempts": 0,
    }
    _persist(sessions, session)

    result = await coordinator.handle_action(
        "dismiss",
        {"chat_id": "chat", "recovery_id": "current"},
    )

    assert result["status"] == "recovered"
    assert bus.inbound.empty()


@pytest.mark.asyncio
async def test_scan_failure_is_visible_instead_of_aborting_other_sessions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    coordinator, bus, sessions = _coordinator(tmp_path)
    session = sessions.get_or_create("websocket:chat")
    session.metadata[PENDING_USER_TURN_KEY] = True
    _persist(sessions, session)

    async def fail(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(RecoveryCoordinator, "_recover_session", fail)
    await coordinator.scan()

    state = sessions.get_or_create("websocket:chat").metadata[RECOVERY_METADATA_KEY]
    assert state["status"] == "failed"
    assert state["can_continue"] is False
    assert isinstance(bus.outbound.get_nowait().event, RecoveryStateEvent)

    with pytest.raises(RecoveryActionError, match="context is unavailable"):
        await coordinator.handle_action(
            "continue",
            {"chat_id": "chat", "recovery_id": state["recovery_id"]},
        )


@pytest.mark.asyncio
async def test_bus_remains_quiet_after_recovered_state(tmp_path: Path) -> None:
    coordinator, bus, sessions = _coordinator(tmp_path)
    session = sessions.get_or_create("websocket:chat")
    session.metadata[RECOVERY_METADATA_KEY] = {
        "status": "recovered",
        "recovery_id": "done",
        "attempts": 1,
    }
    _persist(sessions, session)

    await coordinator.scan()

    await asyncio.sleep(0)
    assert bus.inbound.empty()
    assert bus.outbound.empty()
