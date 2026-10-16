from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.session_helpers import save_completed_subagent
from nanobot.agent.loop import AgentLoop
from nanobot.agent.turn_delivery import TurnDeliveryFactory
from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import GenerationSettings, LLMResponse, ToolCallRequest
from nanobot.session.manager import SessionManager
from nanobot.session.recovery import (
    RECOVERY_METADATA_KEY,
    REQUEST_ORIGIN_METADATA_KEY,
)
from nanobot.session.turn_continuation import INTERNAL_CONTINUATION_META
from nanobot.session.webui_turns import WebuiTurnCoordinator, WebuiTurnRoutePolicy
from nanobot.webui.recovery import RecoveryCoordinator
from nanobot.webui.transcript import WebUITranscriptRecorder


@pytest.mark.asyncio
async def test_recovery_continuation_runs_without_a_sustained_goal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bus = MessageBus()
    sessions = SessionManager(tmp_path)
    session = sessions.get_or_create("websocket:chat")
    session.metadata.update({
        "webui": True,
        RECOVERY_METADATA_KEY: {
            "status": "awaiting_user",
            "recovery_id": "recovery-1",
            "attempts": 0,
        },
    })
    sessions.save(session)
    recovery = RecoveryCoordinator(sessions, bus)

    loop = AgentLoop.__new__(AgentLoop)
    loop.sessions = sessions
    loop._unified_session = False
    loop._recovery_admission = recovery
    loop._session_locks = {}
    loop._concurrency_gate = None
    loop._automation_turn_coordinators = []
    loop._discarding_sessions = set()
    loop._preserve_inflight_turns_on_shutdown = False
    loop.turn_delivery_factory = TurnDeliveryFactory(bus)
    process_message = AsyncMock(return_value=OutboundMessage(
        channel="websocket",
        chat_id="chat",
        content="done",
    ))
    monkeypatch.setattr(loop, "_process_message", process_message)

    await recovery.handle_action(
        "continue",
        {"chat_id": "chat", "recovery_id": "recovery-1"},
    )
    continuation = bus.inbound.get_nowait()

    assert continuation.metadata[INTERNAL_CONTINUATION_META] is True
    await loop._dispatch_one(continuation, asyncio.Queue())

    process_message.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("late_result", [False, True], ids=["user_request", "late_subagent_result"])
async def test_recovery_preserves_turn_origin_until_the_next_user_turn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, late_result: bool,
) -> None:
    monkeypatch.setattr("nanobot.webui.transcript.get_webui_dir", lambda: tmp_path / "webui")
    monkeypatch.setattr("nanobot.webui.session_list_index.get_webui_dir", lambda: tmp_path / "webui")
    bus = MessageBus()
    provider = MagicMock(aclose=AsyncMock())
    provider.get_default_model.return_value = "test-model"
    provider.generation = GenerationSettings()
    provider.can_resume_conversation_state.return_value = False
    entered = asyncio.Event()
    model_calls = 0
    persisted_origin = None

    async def interrupted(**kwargs):
        nonlocal model_calls, persisted_origin
        model_calls += 1
        if model_calls == 1:
            persisted_origin = SessionManager(tmp_path).get_or_create(request.session_key).metadata[
                REQUEST_ORIGIN_METADATA_KEY
            ]
        if late_result and model_calls == 1:
            return LLMResponse(content=None, tool_calls=[ToolCallRequest(
                "read-result", "read_file", {"path": str(tmp_path / "result.txt")},
            )])
        entered.set()
        await asyncio.Event().wait()

    loop = AgentLoop(bus=bus, provider=provider, workspace=tmp_path, model="test-model")
    loop.turn_delivery_factory = TurnDeliveryFactory(bus, WebuiTurnRoutePolicy(loop.sessions))
    coordinator = WebuiTurnCoordinator(bus, loop.sessions, loop.schedule_background)
    request = InboundMessage(
        channel="websocket", sender_id="user", chat_id="chat", content="Inspect configuration",
        metadata={"webui": True, "webui_turn_id": "user-request", "message_id": "user-message"},
    )
    await loop.sessions.state.get(request.session_key)
    await loop.sessions.state.update_metadata(request.session_key, {"title": "Configuration"})
    with coordinator.connected():
        if late_result:
            provider.chat_stream_with_retry = AsyncMock(side_effect=[
                LLMResponse(content="Background check started"), LLMResponse(content="New request answered"),
            ])
            await loop._dispatch_one(request, asyncio.Queue())
            await loop._dispatch_one(InboundMessage(
                channel="websocket", sender_id="user", chat_id="chat", content="New request B",
                metadata={"webui": True, "webui_turn_id": "request-b", "message_id": "message-b"},
            ), asyncio.Queue())
            await save_completed_subagent(loop, "task-a", request.session_key)
            request = InboundMessage(
                channel="system", sender_id="subagent", chat_id=request.session_key,
                content="Background check for the original request completed",
                session_key_override=request.session_key,
                metadata={
                    "injected_event": "subagent_result", "subagent_task_id": "task-a",
                    "origin_message_id": "user-message",
                },
            )
            (tmp_path / "result.txt").write_text("Configuration verified", encoding="utf-8")
        existing_tasks = set(loop.subagents.statuses_for_session(request.session_key))
        provider.chat_stream_with_retry = AsyncMock(side_effect=interrupted)
        delivery = loop.turn_delivery_factory.create(request, request.session_key)
        expected_origin = {
            "message_id": None if late_result else "user-message",
            "turn_id": delivery.route.turn_id,
        }
        recorder = WebUITranscriptRecorder()

        async def record_progress(content, **kwargs):
            recorder.prepare_and_append(
                "chat", {"event": "message", "chat_id": "chat", "text": content, "kind": "progress"},
                metadata=delivery.route.metadata, phase="activity",
            )

        task = asyncio.create_task(loop._process_message(
            request, delivery=delivery, on_progress=record_progress,
        ))
        try:
            await asyncio.wait_for(entered.wait(), 5)
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            await loop.aclose()

    bus = MessageBus()
    sessions = SessionManager(tmp_path)
    recovery = RecoveryCoordinator(sessions, bus)
    await recovery.scan()
    state = sessions.get_or_create(request.session_key).metadata[RECOVERY_METADATA_KEY]
    assert state["status"] == "awaiting_user"
    await recovery.handle_action("continue", {"chat_id": "chat", "recovery_id": state["recovery_id"]})
    continuation = bus.inbound.get_nowait()

    provider.chat_stream_with_retry = AsyncMock(side_effect=[
        LLMResponse(content=None, tool_calls=[ToolCallRequest(
            "delegate", "subagent", {"action": "create", "task": "Inspect configuration", "wait": True},
        )]),
        LLMResponse(content="Configuration verified"),
        LLMResponse(content="Inspection complete"),
        LLMResponse(content=None, tool_calls=[ToolCallRequest(
            "delegate-next", "subagent", {"action": "create", "task": "Inspect logs", "wait": True},
        )]),
        LLMResponse(content="Logs verified"),
        LLMResponse(content="Log inspection complete"),
    ])
    loop = AgentLoop(
        bus=bus, provider=provider, workspace=tmp_path, model="test-model",
        session_manager=sessions, recovery_admission=recovery,
    )
    loop.turn_delivery_factory = TurnDeliveryFactory(bus, WebuiTurnRoutePolicy(sessions))
    coordinator = WebuiTurnCoordinator(bus, sessions, loop.schedule_background, recovery=recovery)
    try:
        with coordinator.connected():
            await loop._dispatch_one(continuation, asyncio.Queue())
        statuses = loop.subagents.statuses_for_session(request.session_key)
        children = [status for task_id, status in statuses.items() if task_id not in existing_tasks]
        assert len(children) == 1
        child = children[0]
        assert child.state == "done"
        assert child.origin_message_id == expected_origin["message_id"]
        assert child.origin_turn_id == expected_origin["turn_id"]
        assert persisted_origin == expected_origin
        assert continuation.metadata["webui_turn_id"] == f"recovery:{state['recovery_id']}"
        assert sessions.get_or_create(request.session_key).metadata[RECOVERY_METADATA_KEY]["status"] == "recovered"
        with coordinator.connected():
            await loop._dispatch_one(InboundMessage(
                channel="websocket", sender_id="user", chat_id="chat", content="Inspect logs",
                metadata={"webui": True, "webui_turn_id": "next-request", "message_id": "next-message"},
            ), asyncio.Queue())
        statuses = loop.subagents.statuses_for_session(request.session_key)
        assert {
            (status.origin_message_id, status.origin_turn_id)
            for task_id, status in statuses.items() if task_id not in existing_tasks
        } == {
            (expected_origin["message_id"], expected_origin["turn_id"]), ("next-message", "next-request"),
        }
    finally:
        await loop.aclose()
