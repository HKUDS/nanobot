from __future__ import annotations

import asyncio
from copy import deepcopy
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.session_helpers import save_completed_subagent
from nanobot.agent.loop import AgentLoop
from nanobot.agent.turn_delivery import TurnDeliveryFactory
from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import GenerationSettings, LLMProvider, LLMResponse, ToolCallRequest
from nanobot.runtime_context import public_history_message
from nanobot.session.manager import SessionManager
from nanobot.session.recovery import (
    PENDING_USER_TURN_KEY,
    RECOVERY_METADATA_KEY,
    REQUEST_ORIGIN_METADATA_KEY,
    RUNTIME_CHECKPOINT_KEY,
)
from nanobot.session.turn_continuation import INTERNAL_CONTINUATION_META
from nanobot.session.webui_turns import WebuiTurnCoordinator, WebuiTurnRoutePolicy
from nanobot.webui.recovery import RecoveryCoordinator
from nanobot.webui.transcript import WebUITranscriptRecorder


@pytest.mark.asyncio
async def test_committed_model_failure_continues_with_tool_results_without_resending(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    bus = MessageBus()
    sessions = SessionManager(tmp_path)
    session = sessions.get_or_create("websocket:chat")
    session.metadata["title"] = "Saved recovery"
    sessions.save(session)
    recovery = RecoveryCoordinator(sessions, bus)
    provider = MagicMock(aclose=AsyncMock())
    provider.get_default_model.return_value = "test-model"
    provider.generation = GenerationSettings()
    provider.can_resume_conversation_state.return_value = False
    requests: list[dict] = []
    responses = iter([
        LLMResponse(content=None, tool_calls=[ToolCallRequest(
            "read-once", "read_file", {"path": str(tmp_path / "note.txt")},
        )]),
        LLMResponse(content="private failure", finish_reason="error", error_kind="connection"),
        LLMResponse(content="Finished from the saved result."),
    ])

    async def respond(**kwargs):
        requests.append(deepcopy({
            "messages": LLMProvider._sanitize_empty_content(kwargs["messages"]),
            "tools": kwargs["tools"],
        }))
        return next(responses)

    provider.chat_stream_with_retry = AsyncMock(side_effect=respond)
    (tmp_path / "note.txt").write_text("saved evidence", encoding="utf-8")
    loop = AgentLoop(
        bus=bus, provider=provider, workspace=tmp_path, model="test-model",
        session_manager=sessions, recovery_admission=recovery,
    )
    loop.turn_delivery_factory = TurnDeliveryFactory(bus, WebuiTurnRoutePolicy(sessions))
    coordinator = WebuiTurnCoordinator(bus, sessions, loop.schedule_background, recovery=recovery)
    read_tool = loop.tools.get("read_file")
    assert read_tool is not None
    execute = AsyncMock(wraps=read_tool.execute)
    monkeypatch.setattr(read_tool, "execute", execute)
    request = InboundMessage(
        channel="websocket", sender_id="user", chat_id="chat", content="Read the note and summarize it",
        metadata={"webui": True, "webui_turn_id": "request-1"},
    )
    try:
        with coordinator.connected():
            await loop._dispatch_one(request, asyncio.Queue())
            state = (await sessions.state.get(request.session_key)).metadata[RECOVERY_METADATA_KEY]
            assert state["status"] == "awaiting_user"
            assert bus.inbound.empty()
            await recovery.handle_action("continue", {"chat_id": "chat", "recovery_id": state["recovery_id"]})
            await loop._dispatch_one(bus.inbound.get_nowait(), asyncio.Queue())
        final = await sessions.state.get(request.session_key)
        assert final.metadata[RECOVERY_METADATA_KEY]["status"] == "recovered"
        assert execute.await_count == 1
        assert sum(message.get("role") == "user" for message in final.messages) == 1
        assert any(message.get("role") == "tool" and "saved evidence" in message["content"] for message in requests[-1]["messages"])
        assert requests[0]["messages"][0] == requests[-1]["messages"][0]
        assert requests[0]["tools"] == requests[-1]["tools"]
        assert requests[-1]["messages"][:len(requests[1]["messages"])] == requests[1]["messages"]
        assert len(requests) == 3
    finally:
        await loop.aclose()


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
    monkeypatch.setattr("nanobot.webui.history.get_webui_dir", lambda: tmp_path / "webui")
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
        recorder = WebUITranscriptRecorder(loop.sessions)

        async def record_progress(content, **kwargs):
            await recorder.prepare_and_append(
                "chat", {"event": "message", "chat_id": "chat", "text": content, "kind": "progress"},
                metadata=delivery.delivery_message.metadata, phase="activity",
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


@pytest.mark.asyncio
@pytest.mark.parametrize("with_tools", [False, True], ids=["before_response", "after_tools"])
@pytest.mark.parametrize("gateway_shutdown", [False, True], ids=["explicit_stop", "gateway_shutdown"])
async def test_recovery_distinguishes_explicit_stop_from_gateway_shutdown(
    tmp_path: Path, with_tools: bool, gateway_shutdown: bool,
) -> None:
    bus = MessageBus()
    sessions = SessionManager(tmp_path)
    recovery = RecoveryCoordinator(sessions, bus)
    provider = MagicMock(aclose=AsyncMock())
    provider.get_default_model.return_value = "test-model"
    provider.generation = GenerationSettings()
    provider.can_resume_conversation_state.return_value = False
    entered = asyncio.Event()
    requests = 0
    note = tmp_path / "note.txt"
    note.write_text("saved evidence", encoding="utf-8")

    async def respond(**kwargs):
        nonlocal requests
        requests += 1
        if with_tools and requests == 1:
            return LLMResponse(content=None, tool_calls=[ToolCallRequest(
                "read-once", "read_file", {"path": str(note)},
            )])
        entered.set()
        await asyncio.Event().wait()

    provider.chat_stream_with_retry = AsyncMock(side_effect=respond)
    loop = AgentLoop(
        bus=bus, provider=provider, workspace=tmp_path, model="test-model",
        session_manager=sessions, recovery_admission=recovery,
        turn_delivery_factory=TurnDeliveryFactory(bus, WebuiTurnRoutePolicy(sessions)),
    )
    coordinator = WebuiTurnCoordinator(bus, sessions, loop.schedule_background, recovery=recovery)
    request = InboundMessage(
        channel="websocket", sender_id="user", chat_id="chat", content="Read the note and summarize",
        metadata={"webui": True, "webui_turn_id": "request-1"},
    )
    try:
        with coordinator.connected():
            await loop._dispatch_inbound(request)
            await asyncio.wait_for(entered.wait(), 5)
            if gateway_shutdown:
                loop.preserve_inflight_turns_on_shutdown()
            else:
                await loop._dispatch_inbound(InboundMessage(
                    channel="websocket", sender_id="user", chat_id="chat", content="/stop",
                    metadata={"webui": True},
                ))
                outbound = [bus.outbound.get_nowait() for _ in range(bus.outbound.qsize())]
                assert any(message.content == "Stopped 1 task(s)." for message in outbound)
    finally:
        await loop.aclose()

    restarted = SessionManager(tmp_path)
    try:
        saved = await restarted.state.get(request.session_key)
        assert bool(saved.metadata.get(PENDING_USER_TURN_KEY)) is gateway_shutdown
        assert (RUNTIME_CHECKPOINT_KEY in saved.metadata) is (gateway_shutdown and with_tools)
        if with_tools and not gateway_shutdown:
            assert any(
                row.get("role") == "tool" and "saved evidence" in row["content"]
                for row in saved.messages
            )

        await RecoveryCoordinator(restarted, MessageBus()).scan()
        restored = await restarted.state.get(request.session_key)
        if gateway_shutdown:
            assert restored.metadata[RECOVERY_METADATA_KEY]["status"] == "awaiting_user"
            assert restored.metadata[RECOVERY_METADATA_KEY]["reason"] == "restart_requires_confirmation"
        else:
            assert RECOVERY_METADATA_KEY not in restored.metadata
    finally:
        await restarted.state.aclose()


def _recovery_loop(tmp_path, provider, sessions=None):
    bus = MessageBus()
    sessions = sessions or SessionManager(tmp_path)
    recovery = RecoveryCoordinator(sessions, bus)
    loop = AgentLoop(
        bus=bus, provider=provider, workspace=tmp_path, model="test-model",
        session_manager=sessions, recovery_admission=recovery,
        turn_delivery_factory=TurnDeliveryFactory(bus, WebuiTurnRoutePolicy(sessions)),
    )
    return loop, recovery


@pytest.mark.parametrize(("boundary", "gateway_shutdown"), [
    ("awaiting_tools", False), ("tools_completed", False), ("final_response", False),
    ("awaiting_tools", True), ("tools_completed", True), ("final_response", True),
    ("completed", False),
])
async def test_multiround_recovery_keeps_completed_work_and_consumed_followup(
    tmp_path, monkeypatch, boundary, gateway_shutdown,
):
    from nanobot.session.recovery import pending_followups

    provider = MagicMock(aclose=AsyncMock())
    provider.get_default_model.return_value = "test-model"
    provider.generation = GenerationSettings()
    provider.can_resume_conversation_state.return_value = False
    requests = []
    responses = iter([
        LLMResponse(content=None, tool_calls=[ToolCallRequest("A", "read_file", {"path": "A.txt"})]),
        LLMResponse(content=None, tool_calls=[ToolCallRequest("B", "read_file", {"path": "B.txt"})]),
        LLMResponse(content="Both results received."),
        LLMResponse(content="Continued without repeating work."),
    ])

    async def respond(**kwargs):
        requests.append(deepcopy(kwargs["messages"]))
        return next(responses)

    provider.chat_stream_with_retry = AsyncMock(side_effect=respond)
    loop, recovery = _recovery_loop(tmp_path, provider)
    first_tool = asyncio.Event()
    release_first = asyncio.Event()
    reached = asyncio.Event()
    attempts = []
    tool = loop.tools.get("read_file")

    async def read(path, **kwargs):
        attempts.append(path)
        if path == "A.txt":
            first_tool.set()
            await release_first.wait()
        elif boundary == "awaiting_tools":
            reached.set()
            await asyncio.Event().wait()
        return f"result for {path}"

    monkeypatch.setattr(tool, "execute", read)
    checkpoint = loop._set_runtime_checkpoint

    async def save_checkpoint(session, payload):
        await checkpoint(session, payload)
        if payload["iteration"] > 0 and payload["phase"] == boundary and boundary != "awaiting_tools":
            reached.set()
            await asyncio.Event().wait()

    monkeypatch.setattr(loop, "_set_runtime_checkpoint", save_checkpoint)
    request = InboundMessage(
        channel="websocket", sender_id="user", chat_id="chat", content="Read two notes",
        metadata={"webui": True, "webui_turn_id": "initial"},
    )
    try:
        await loop._dispatch_inbound(request)
        await asyncio.wait_for(first_tool.wait(), 5)
        await loop._dispatch_inbound(InboundMessage(
            channel="websocket", sender_id="user", chat_id="chat", content="Keep both results",
            metadata={"webui": True, "webui_turn_id": "followup"},
        ))
        release_first.set()
        if boundary == "completed":
            await asyncio.gather(*loop._active_tasks[request.session_key])
        else:
            await asyncio.wait_for(reached.wait(), 5)
            if gateway_shutdown:
                loop.preserve_inflight_turns_on_shutdown()
            else:
                await loop._dispatch_inbound(InboundMessage(
                    channel="websocket", sender_id="user", chat_id="chat", content="/stop",
                ))
    finally:
        await loop.aclose()

    sessions = SessionManager(tmp_path)
    resumed, recovery = _recovery_loop(tmp_path, provider, sessions)
    try:
        await recovery.scan()
        stored = await sessions.state.get(request.session_key)
        tools = [row for row in stored.messages if row["role"] == "tool"]
        assert [row["tool_call_id"] for row in tools] == ["A", "B"]
        assert tools[0]["content"] == "result for A.txt"
        if boundary == "awaiting_tools":
            assert tools[1]["_recovery_interrupted"] is True
            assert "outcome is unknown" in tools[1]["content"]
        else:
            assert tools[1]["content"] == "result for B.txt"
        assert [public_history_message(row)["content"] for row in stored.messages if row["role"] == "user"] == [
            "Read two notes", "Keep both results",
        ]
        assert pending_followups(stored) == []
        assert resumed.bus.inbound.empty()
        calls = [call["id"] for row in stored.messages for call in row.get("tool_calls", [])]
        assert calls == ["A", "B"]
        if boundary in {"final_response", "completed"}:
            assert stored.messages[-1]["content"] == "Both results received."
        if gateway_shutdown and boundary in {"awaiting_tools", "tools_completed"}:
            state = stored.metadata[RECOVERY_METADATA_KEY]
            assert state["status"] == "awaiting_user"
            await recovery.handle_action("continue", {"chat_id": "chat", "recovery_id": state["recovery_id"]})
            await resumed._dispatch_one(resumed.bus.inbound.get_nowait(), asyncio.Queue())
            history = requests[-1]
            assert [row["tool_call_id"] for row in history if row["role"] == "tool"] == ["A", "B"]
        assert attempts == ["A.txt", "B.txt"]
    finally:
        await resumed.aclose()


async def test_new_input_waits_for_real_recovery_cancellation_before_reading_draft(tmp_path, monkeypatch):
    provider = MagicMock(aclose=AsyncMock())
    provider.get_default_model.return_value = "test-model"
    provider.generation = GenerationSettings()
    provider.can_resume_conversation_state.return_value = False
    provider.chat_stream_with_retry = AsyncMock(side_effect=[
        LLMResponse(content=None, tool_calls=[ToolCallRequest("C", "read_file", {"path": "C.txt"})]),
        LLMResponse(content="New input answered."),
    ])
    loop, recovery = _recovery_loop(tmp_path, provider)
    session = await loop.sessions.state.get("websocket:chat")
    session.add_message("user", "Earlier request")
    session.metadata["title"] = "Recovery handoff"
    session.metadata[RECOVERY_METADATA_KEY] = {
        "status": "awaiting_user", "recovery_id": "recover", "attempts": 0,
    }
    await loop.sessions.state.prepare_input(session)
    entered = asyncio.Event()
    cancelled = asyncio.Event()

    async def read(**kwargs):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    monkeypatch.setattr(loop.tools.get("read_file"), "execute", read)
    coordinator = WebuiTurnCoordinator(loop.bus, loop.sessions, loop.schedule_background, recovery=recovery)
    try:
        with coordinator.connected():
            await recovery.handle_action("continue", {"chat_id": "chat", "recovery_id": "recover"})
            await loop._dispatch_inbound(loop.bus.inbound.get_nowait())
            await asyncio.wait_for(entered.wait(), 5)
            old_tasks = tuple(loop._active_tasks[session.key])
            await loop._dispatch_inbound(InboundMessage(
                channel="websocket", sender_id="user", chat_id="chat", content="Replace the old task",
                metadata={"webui": True, "webui_turn_id": "new-input"},
            ))
            assert cancelled.is_set()
            assert all(task.done() for task in old_tasks)
            await asyncio.gather(*loop._active_tasks[session.key])
    finally:
        await loop.aclose()

    reopened = SessionManager(tmp_path)
    try:
        saved = await reopened.state.get(session.key)
        assert [row["tool_call_id"] for row in saved.messages if row["role"] == "tool"] == ["C"]
        assert [call["id"] for row in saved.messages for call in row.get("tool_calls", [])] == ["C"]
        assert [public_history_message(row)["content"] for row in saved.messages if row["role"] == "user"] == [
            "Earlier request", "Replace the old task",
        ]
        assert saved.messages[-1]["content"] == "New input answered."
        assert provider.chat_stream_with_retry.await_count == 2
        assert RUNTIME_CHECKPOINT_KEY not in saved.metadata
    finally:
        await reopened.state.aclose()
