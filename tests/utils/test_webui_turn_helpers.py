"""Tests for WebSocket turn timing events and transcript ownership."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.tools.context import RequestContext, request_context
from nanobot.agent.turn_delivery import TurnDeliveryFactory
from nanobot.bus.events import InboundMessage
from nanobot.bus.outbound_events import (
    GoalStatusEvent,
    RetryStatusEvent,
    TurnEndEvent,
    TurnModelUpdatedEvent,
    UserInputEvent,
)
from nanobot.bus.queue import MessageBus
from nanobot.bus.runtime_events import (
    RuntimeEventContext,
    TurnRuntimeAdmitted,
    UserInputAccepted,
)
from nanobot.providers.base import GenerationSettings
from nanobot.providers.fallback_provider import FallbackModelSelection
from nanobot.session import webui_turns as wth
from nanobot.session.display_history import HISTORY_GENERATION_METADATA_KEY
from nanobot.session.manager import SessionManager
from nanobot.session.session_handles import session_handle_for_name
from nanobot.session.session_messages import SESSION_MESSAGE_METADATA_KEY
from nanobot.utils.llm_runtime import LLMRuntime
from nanobot.webui.metadata import WEBSOCKET_TURN_OWNER_METADATA_KEY


@pytest.fixture(autouse=True)
def _clear_pending_transcripts() -> None:
    with wth._WEBSOCKET_TRANSCRIPT_LOCK:
        wth._WEBSOCKET_PENDING_TRANSCRIPTS.clear()
    yield
    with wth._WEBSOCKET_TRANSCRIPT_LOCK:
        wth._WEBSOCKET_PENDING_TRANSCRIPTS.clear()


@pytest.mark.asyncio
async def test_publish_turn_run_status_running_sends_wall_clock(monkeypatch) -> None:
    monkeypatch.setattr(wth.time, "time", lambda: 1234.5)
    bus = MessageBus()
    bus.publish_outbound = AsyncMock()
    msg = InboundMessage(
        channel="websocket",
        sender_id="u",
        chat_id="chat-a",
        content="hi",
        metadata={"webui_turn_id": "turn-a"},
    )

    await wth.publish_turn_run_status(bus, msg, "running")

    assert wth.has_pending_webui_transcript("chat-a", None) is True
    call = bus.publish_outbound.await_args[0][0]
    assert call.chat_id == "chat-a"
    assert call.metadata["webui_turn_id"] == "turn-a"
    assert isinstance(call.event, GoalStatusEvent)
    assert call.event.started_at == 1234.5


@pytest.mark.asyncio
async def test_publish_turn_run_status_reuses_explicit_wall_clock() -> None:
    bus = MessageBus()
    bus.publish_outbound = AsyncMock()
    msg = InboundMessage(channel="websocket", sender_id="u", chat_id="chat-a", content="hi")

    await wth.publish_turn_run_status(bus, msg, "running", started_at=1234.5)

    call = bus.publish_outbound.await_args[0][0]
    assert isinstance(call.event, GoalStatusEvent)
    assert call.event.started_at == 1234.5


@pytest.mark.asyncio
async def test_queued_idle_status_protects_transcript_until_delivery() -> None:
    bus = MessageBus()
    bus.publish_outbound = AsyncMock()
    msg = InboundMessage(
        channel="websocket",
        sender_id="u",
        chat_id="chat-b",
        content="hi",
        metadata={"webui_turn_id": "turn-b"},
    )

    await wth.publish_turn_run_status(bus, msg, "running")
    assert wth.has_pending_webui_transcript("chat-b", None) is True

    await wth.publish_turn_run_status(bus, msg, "idle")
    assert wth.has_pending_webui_transcript("chat-b", None) is True
    assert bus.publish_outbound.await_args.args[0].event == GoalStatusEvent(status="idle")


async def test_clear_websocket_turn_only_clears_matching_owner() -> None:
    bus = MessageBus()
    msg = InboundMessage(
        channel="websocket", sender_id="u", chat_id="chat-b", content="hi",
        metadata={"webui_turn_id": "turn-new", WEBSOCKET_TURN_OWNER_METADATA_KEY: "owner-new"},
    )
    await wth.publish_turn_run_status(bus, msg, "running", started_at=1234.5)

    assert wth.clear_websocket_turn_if_current("chat-b", "owner-old") is False
    assert wth.has_pending_webui_transcript("chat-b", None) is True

    assert wth.clear_websocket_turn_if_current("chat-b", "owner-new") is True
    assert wth.has_pending_webui_transcript("chat-b", None) is False


@pytest.mark.asyncio
async def test_ownerless_turns_receive_distinct_internal_owners() -> None:
    bus = MessageBus()
    bus.publish_outbound = AsyncMock()
    first = InboundMessage(
        channel="websocket",
        sender_id="u",
        chat_id="chat-ownerless",
        content="first",
    )
    second = InboundMessage(
        channel="websocket",
        sender_id="u",
        chat_id="chat-ownerless",
        content="second",
    )

    await wth.publish_turn_run_status(bus, first, "running")
    first_owner = first.metadata[WEBSOCKET_TURN_OWNER_METADATA_KEY]
    await wth.publish_turn_run_status(bus, second, "running")
    second_owner = second.metadata[WEBSOCKET_TURN_OWNER_METADATA_KEY]

    assert first_owner != second_owner
    assert wth.clear_websocket_turn_if_current("chat-ownerless", first_owner) is True
    assert wth.has_pending_webui_transcript("chat-ownerless", None) is True
    assert wth.clear_websocket_turn_if_current("chat-ownerless", second_owner) is True
    assert wth.has_pending_webui_transcript("chat-ownerless", None) is False


@pytest.mark.asyncio
async def test_new_generation_keeps_new_owner_pending_after_obsolete_failure(history) -> None:
    bus = MessageBus()
    chat_id = "reset-owner"
    key = f"websocket:{chat_id}"
    old_metadata = await history.metadata(chat_id, {
        WEBSOCKET_TURN_OWNER_METADATA_KEY: "owner-old",
    })
    old = InboundMessage(
        channel="websocket", sender_id="u", chat_id=chat_id, content="old",
        metadata=old_metadata,
    )
    await wth.publish_turn_run_status(bus, old, "running")
    await history.sessions.state.reset(key)
    new_metadata = await history.metadata(chat_id, {
        WEBSOCKET_TURN_OWNER_METADATA_KEY: "owner-new",
    })
    new = InboundMessage(
        channel="websocket", sender_id="u", chat_id=chat_id, content="new",
        metadata=new_metadata,
    )
    await wth.publish_turn_run_status(bus, new, "running")
    old_generation = old_metadata[HISTORY_GENERATION_METADATA_KEY]
    new_generation = new_metadata[HISTORY_GENERATION_METADATA_KEY]
    assert new_generation != old_generation

    # A delayed old completion can fail after reset while the new owner is running.
    wth.mark_websocket_turn_transcript_persistence_failed(chat_id, "owner-old", old_generation)
    assert wth.has_pending_webui_transcript(chat_id, new_generation) is True
    assert wth.clear_websocket_turn_if_current(chat_id, "owner-new") is True
    assert wth.has_pending_webui_transcript(chat_id, new_generation) is False


@pytest.mark.asyncio
async def test_publish_turn_run_status_non_websocket_is_quiet() -> None:
    bus = MessageBus()
    bus.publish_outbound = AsyncMock()
    msg = InboundMessage(channel="telegram", sender_id="u", chat_id="1", content="hi")

    await wth.publish_turn_run_status(bus, msg, "running")

    bus.publish_outbound.assert_not_awaited()


@pytest.mark.asyncio
async def test_fallback_model_is_scoped_to_its_websocket_chat() -> None:
    bus = MessageBus()
    bus.publish_outbound = AsyncMock()
    observer = wth.build_webui_fallback_model_observer(bus)

    runtime = LLMRuntime(
        provider=MagicMock(),
        model="openai/gpt-4.1",
        generation=GenerationSettings(),
        context_window_tokens=16_000,
        model_preset="Deep Research",
    )
    with request_context(
        RequestContext(
            channel="websocket",
            chat_id="chat-model",
            runtime=runtime,
            metadata={"webui": True},
        )
    ):
        await observer(FallbackModelSelection("deepseek/deepseek-chat", "openai_codex"))

    outbound = bus.publish_outbound.await_args.args[0]
    assert outbound.channel == "websocket"
    assert outbound.chat_id == "chat-model"
    assert outbound.metadata == {"webui": True}
    assert isinstance(outbound.event, TurnModelUpdatedEvent)
    assert outbound.event.model == "deepseek/deepseek-chat"
    assert outbound.event.model_preset == "Deep Research"
    assert outbound.event.reauth_provider == "openai_codex"


@pytest.mark.asyncio
async def test_coordinator_connections_end_on_scope_exit_and_can_reconnect(tmp_path):
    from nanobot.bus.runtime_events import RuntimeModelChanged

    bus = MessageBus()
    bus.publish_outbound = AsyncMock()
    coordinator = wth.WebuiTurnCoordinator(
        bus=bus, sessions=SessionManager(tmp_path),
        schedule_background=lambda coro: coro.close(),
    )
    event = RuntimeModelChanged("model", None)
    with pytest.raises(RuntimeError, match="shutdown"):
        with coordinator.connected():
            await bus.publish(event)
            raise RuntimeError("shutdown")
    bus.publish_outbound.assert_awaited_once()
    await bus.publish(event)
    bus.publish_outbound.assert_awaited_once()
    with coordinator.connected():
        bus.publish_nowait(event)
        await bus.drain()
    assert bus.publish_outbound.await_count == 2


async def test_admitted_runtime_publishes_chat_scoped_model_and_preset(tmp_path) -> None:
    bus = MessageBus()
    bus.publish_outbound = AsyncMock()
    coordinator = wth.WebuiTurnCoordinator(
        bus=bus,
        sessions=SessionManager(tmp_path),
        schedule_background=lambda coro: coro.close(),
    )
    coordinator.subscribe()
    runtime = LLMRuntime(
        provider=MagicMock(),
        model="openai-codex/gpt-5.6",
        generation=GenerationSettings(),
        context_window_tokens=262_144,
        model_preset="Codex",
    )

    await bus.publish(
        TurnRuntimeAdmitted(
            context=RuntimeEventContext(
                channel="websocket",
                chat_id="chat-model",
                session_key="websocket:chat-model",
                metadata={"webui": True},
            ),
            runtime=runtime,
        )
    )

    outbound = bus.publish_outbound.await_args.args[0]
    assert outbound.channel == "websocket"
    assert outbound.chat_id == "chat-model"
    assert isinstance(outbound.event, TurnModelUpdatedEvent)
    assert outbound.event.model == "openai-codex/gpt-5.6"
    assert outbound.event.model_preset == "Codex"


@pytest.mark.asyncio
@pytest.mark.parametrize(("states", "terminal_kind", "expected_kind", "attempts"), [
    (("exhausted",), None, "connection", 4),
    (("waiting", "recovered"), None, None, None),
    (("waiting",), "billing", "billing", None),
    (("exhausted", "cleared"), "billing", "billing", None),
])
async def test_turn_retry_cause_survives_only_actual_exhaustion(
    tmp_path, states, terminal_kind, expected_kind, attempts,
) -> None:
    bus = MessageBus()
    coordinator = wth.WebuiTurnCoordinator(
        bus=bus, sessions=SessionManager(tmp_path),
        schedule_background=lambda coro: coro.close(),
    )
    with coordinator.connected():
        msg = InboundMessage(
            channel="websocket", sender_id="user", chat_id="chat-retry", content="hello",
            metadata={"webui": True, "webui_turn_id": "turn-1"},
        )
        delivery = TurnDeliveryFactory(bus).create(msg, msg.session_key)
        for state in states:
            await delivery.events.emit(RetryStatusEvent(
                state=state, attempt=4, max_attempts=4, error_kind="connection",
            ))
        delivery.record_stop_reason("error", failure_error_kind=terminal_kind)
        await delivery.complete(None, publish_completion=True)

    outbounds = [bus.outbound.get_nowait() for _ in range(bus.outbound_size)]
    retry_events = [out.event for out in outbounds if isinstance(out.event, RetryStatusEvent)]
    assert [event.state for event in retry_events] == list(states)
    completed = next(out.event for out in outbounds if isinstance(out.event, TurnEndEvent))
    assert completed.failure_error_kind == expected_kind
    assert completed.failure_attempts == attempts


@pytest.mark.asyncio
@pytest.mark.parametrize("write_succeeds", [True, False])
async def test_session_input_is_projected_by_the_webui_coordinator(
    tmp_path,
    monkeypatch,
    write_succeeds,
) -> None:
    bus = MessageBus()
    bus.publish_outbound = AsyncMock()
    sessions = SessionManager(tmp_path)
    target_session = sessions.get_or_create("websocket:target")
    target_session.metadata["webui"] = True
    sessions.save(target_session)
    source = session_handle_for_name("websocket:source", "luma")
    envelope = {
        "message_id": "message-1",
        "created_at_ms": 123,
        "expect_reply": False,
        "source_handle": source.name,
        "source_session_key": "websocket:source",
        "target_session_key": "websocket:target",
    }
    append_input = AsyncMock(side_effect=None if write_succeeds else OSError("write failed"))
    monkeypatch.setattr(wth, "append_session_message_input", append_input)
    coordinator = wth.WebuiTurnCoordinator(
        bus=bus,
        sessions=sessions,
        schedule_background=lambda coro: coro.close(),
    )
    coordinator.subscribe()

    await bus.publish(UserInputAccepted(
        context=RuntimeEventContext(
            channel="system",
            chat_id="websocket:target",
            session_key="websocket:target",
            metadata={SESSION_MESSAGE_METADATA_KEY: envelope},
        ),
        content="Review this",
    ))

    append_input.assert_awaited_once()
    if not write_succeeds:
        bus.publish_outbound.assert_not_awaited()
        return
    outbound = bus.publish_outbound.await_args.args[0]
    assert outbound.channel == "websocket"
    assert outbound.chat_id == "target"
    assert isinstance(outbound.event, UserInputEvent)
    assert outbound.event.content == "Review this"
    assert outbound.event.provenance["session_message"]["session"] == {
        "id": source.id,
        "name": source.name,
    }


@pytest.mark.asyncio
async def test_fallback_model_ignores_non_websocket_requests() -> None:
    bus = MessageBus()
    bus.publish_outbound = AsyncMock()
    observer = wth.build_webui_fallback_model_observer(bus)

    with request_context(RequestContext(channel="telegram", chat_id="chat-model")):
        await observer(FallbackModelSelection("fallback", "openai_codex"))

    bus.publish_outbound.assert_not_awaited()
