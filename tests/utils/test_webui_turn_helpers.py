"""Tests for WebSocket turn timing strip bookkeeping."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.tools.context import RequestContext, request_context
from nanobot.agent.turn_delivery import TurnRoute
from nanobot.bus.events import InboundMessage
from nanobot.bus.outbound_events import (
    GoalStatusEvent,
    TurnModelUpdatedEvent,
)
from nanobot.bus.runtime_events import (
    RuntimeEventBus,
    RuntimeEventContext,
    SessionTurnStarted,
    TurnRuntimeAdmitted,
)
from nanobot.providers.base import GenerationSettings
from nanobot.session import webui_turns as wth
from nanobot.session.manager import SessionManager
from nanobot.session.session_messages import SESSION_MESSAGE_METADATA_KEY
from nanobot.utils.llm_runtime import LLMRuntime
from nanobot.webui.metadata import WEBSOCKET_TURN_OWNER_METADATA_KEY
from nanobot.webui.transcript import read_transcript_lines


@pytest.fixture(autouse=True)
def _clear_turn_wall_clock(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    wth._WEBSOCKET_ACTIVE_TURNS.clear()
    wth._WEBSOCKET_TURN_WALL_STARTED_AT.clear()
    wth._WEBSOCKET_TURN_IDS.clear()
    wth._WEBSOCKET_TURN_OWNERS.clear()
    yield
    wth._WEBSOCKET_ACTIVE_TURNS.clear()
    wth._WEBSOCKET_TURN_WALL_STARTED_AT.clear()
    wth._WEBSOCKET_TURN_IDS.clear()
    wth._WEBSOCKET_TURN_OWNERS.clear()


@pytest.mark.asyncio
async def test_publish_turn_run_status_running_records_wall_clock() -> None:
    bus = MagicMock()
    bus.publish_outbound = AsyncMock()
    msg = InboundMessage(
        channel="websocket",
        sender_id="u",
        chat_id="chat-a",
        content="hi",
        metadata={"webui_turn_id": "turn-a"},
    )

    await wth.publish_turn_run_status(bus, msg, "running")

    assert "chat-a" in wth._WEBSOCKET_TURN_WALL_STARTED_AT
    t0 = wth.websocket_turn_wall_started_at("chat-a")
    assert isinstance(t0, float)
    assert wth.websocket_turn_id("chat-a") == "turn-a"
    call = bus.publish_outbound.await_args[0][0]
    assert call.chat_id == "chat-a"
    assert isinstance(call.event, GoalStatusEvent)
    assert call.event.started_at == t0


@pytest.mark.asyncio
async def test_publish_turn_run_status_reuses_explicit_wall_clock() -> None:
    bus = MagicMock()
    bus.publish_outbound = AsyncMock()
    msg = InboundMessage(channel="websocket", sender_id="u", chat_id="chat-a", content="hi")

    await wth.publish_turn_run_status(bus, msg, "running", started_at=1234.5)

    assert wth.websocket_turn_wall_started_at("chat-a") == 1234.5
    call = bus.publish_outbound.await_args[0][0]
    assert isinstance(call.event, GoalStatusEvent)
    assert call.event.started_at == 1234.5


@pytest.mark.asyncio
async def test_publish_turn_run_status_idle_retains_registry_until_delivery() -> None:
    bus = MagicMock()
    bus.publish_outbound = AsyncMock()
    msg = InboundMessage(
        channel="websocket",
        sender_id="u",
        chat_id="chat-b",
        content="hi",
        metadata={"webui_turn_id": "turn-b"},
    )

    await wth.publish_turn_run_status(bus, msg, "running")
    assert wth.websocket_turn_wall_started_at("chat-b") is not None
    assert wth.websocket_turn_id("chat-b") == "turn-b"

    await wth.publish_turn_run_status(bus, msg, "idle")
    assert wth.websocket_turn_wall_started_at("chat-b") is not None
    assert wth.websocket_turn_id("chat-b") == "turn-b"


def test_clear_websocket_turn_only_clears_matching_owner() -> None:
    wth._WEBSOCKET_TURN_WALL_STARTED_AT["chat-b"] = 1234.5
    wth._WEBSOCKET_TURN_IDS["chat-b"] = "turn-new"
    wth._WEBSOCKET_TURN_OWNERS["chat-b"] = "owner-new"

    assert wth.clear_websocket_turn_if_current("chat-b", "owner-old") is False
    assert wth.websocket_turn_wall_started_at("chat-b") == 1234.5
    assert wth.websocket_turn_id("chat-b") == "turn-new"

    assert wth.clear_websocket_turn_if_current("chat-b", "owner-new") is True
    assert wth.websocket_turn_wall_started_at("chat-b") is None
    assert wth.websocket_turn_id("chat-b") is None


@pytest.mark.asyncio
async def test_ownerless_turns_receive_distinct_internal_owners() -> None:
    bus = MagicMock()
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
    assert wth._WEBSOCKET_TURN_OWNERS["chat-ownerless"] == second_owner
    assert wth.websocket_turn_wall_started_at("chat-ownerless") is not None
    assert wth.clear_websocket_turn_if_current("chat-ownerless", second_owner) is True


@pytest.mark.asyncio
async def test_publish_turn_run_status_non_websocket_noop_registry() -> None:
    bus = MagicMock()
    bus.publish_outbound = AsyncMock()
    msg = InboundMessage(channel="telegram", sender_id="u", chat_id="1", content="hi")

    await wth.publish_turn_run_status(bus, msg, "running")

    assert wth._WEBSOCKET_TURN_WALL_STARTED_AT == {}
    assert wth._WEBSOCKET_TURN_IDS == {}


@pytest.mark.asyncio
async def test_fallback_model_is_scoped_to_its_websocket_chat() -> None:
    bus = MagicMock()
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
        await observer("deepseek/deepseek-chat")

    outbound = bus.publish_outbound.await_args.args[0]
    assert outbound.channel == "websocket"
    assert outbound.chat_id == "chat-model"
    assert outbound.metadata == {"webui": True}
    assert isinstance(outbound.event, TurnModelUpdatedEvent)
    assert outbound.event.model == "deepseek/deepseek-chat"
    assert outbound.event.model_preset == "Deep Research"


@pytest.mark.asyncio
async def test_admitted_runtime_publishes_chat_scoped_model_and_preset(tmp_path) -> None:
    bus = MagicMock()
    bus.publish_outbound = AsyncMock()
    runtime_events = RuntimeEventBus()
    coordinator = wth.WebuiTurnCoordinator(
        bus=bus,
        sessions=SessionManager(tmp_path),
        schedule_background=lambda coro: coro.close(),
    )
    coordinator.subscribe(runtime_events)
    runtime = LLMRuntime(
        provider=MagicMock(),
        model="openai-codex/gpt-5.6",
        generation=GenerationSettings(),
        context_window_tokens=262_144,
        model_preset="Codex",
    )

    await runtime_events.publish(
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
async def test_fallback_model_ignores_non_websocket_requests() -> None:
    bus = MagicMock()
    bus.publish_outbound = AsyncMock()
    observer = wth.build_webui_fallback_model_observer(bus)

    with request_context(RequestContext(channel="telegram", chat_id="chat-model")):
        await observer("fallback")

    bus.publish_outbound.assert_not_awaited()


@pytest.mark.asyncio
async def test_session_route_does_not_duplicate_already_projected_input(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)
    sessions = SessionManager(tmp_path / "sessions")
    target = sessions.get_or_create("websocket:target")
    target.metadata["webui"] = True
    sessions.save(target)
    metadata = {
        SESSION_MESSAGE_METADATA_KEY: {
            "message_id": "message-1",
            "created_at_ms": 1234,
            "expect_reply": True,
            "source": {
                "name": "reviewer",
                "session_key": "websocket:source",
                "handle_id": "handle_11111111111111111111111111111111",
                "color_slot": 3,
            },
            "target": {
                "name": "implementer",
                "session_key": "websocket:target",
            },
        }
    }
    msg = InboundMessage(
        channel="system",
        sender_id="session",
        chat_id="websocket:target",
        content="Please review this.",
        metadata=metadata,
        session_key_override="websocket:target",
        require_existing_session=True,
    )

    routed = wth.WebuiTurnRoutePolicy(sessions)(
        msg,
        "websocket:target",
        TurnRoute(channel="websocket", chat_id="target"),
    )

    assert routed.publish_lifecycle is True
    assert read_transcript_lines("websocket:target") == []

    bus = MagicMock()
    bus.publish_outbound = AsyncMock()
    coordinator = wth.WebuiTurnCoordinator(
        bus=bus,
        sessions=sessions,
        schedule_background=lambda _task: None,
    )
    await coordinator._handle_session_turn_started(SessionTurnStarted(
        context=RuntimeEventContext(
            channel=routed.channel,
            chat_id=routed.chat_id,
            session_key="websocket:target",
            metadata=routed.metadata,
        ),
        content=msg.content,
    ))

    assert read_transcript_lines("websocket:target") == []
    bus.publish_outbound.assert_not_awaited()


def _session_message_metadata() -> dict[str, Any]:
    return {
        SESSION_MESSAGE_METADATA_KEY: {
            "message_id": "message-1",
            "created_at_ms": 1,
            "expect_reply": True,
            "source": {
                "name": "reviewer",
                "session_key": "websocket:source",
                "handle_id": "handle_11111111111111111111111111111111",
                "color_slot": 1,
            },
            "target": {
                "name": "implementer",
                "session_key": "websocket:target",
            },
        }
    }
