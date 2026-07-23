"""Tests for WebSocket turn timing strip bookkeeping."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.tools.context import RequestContext, request_context
from nanobot.bus.events import InboundMessage
from nanobot.bus.outbound_events import GoalStatusEvent, TurnModelUpdatedEvent
from nanobot.session import webui_turns as wth


@pytest.fixture(autouse=True)
def _clear_turn_wall_clock() -> None:
    wth._WEBSOCKET_TURN_WALL_STARTED_AT.clear()
    yield
    wth._WEBSOCKET_TURN_WALL_STARTED_AT.clear()


@pytest.mark.asyncio
async def test_publish_turn_run_status_running_records_wall_clock() -> None:
    bus = MagicMock()
    bus.publish_outbound = AsyncMock()
    msg = InboundMessage(channel="websocket", sender_id="u", chat_id="chat-a", content="hi")

    await wth.publish_turn_run_status(bus, msg, "running")

    assert "chat-a" in wth._WEBSOCKET_TURN_WALL_STARTED_AT
    t0 = wth.websocket_turn_wall_started_at("chat-a")
    assert isinstance(t0, float)
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
async def test_publish_turn_run_status_idle_clears_wall_clock() -> None:
    bus = MagicMock()
    bus.publish_outbound = AsyncMock()
    msg = InboundMessage(channel="websocket", sender_id="u", chat_id="chat-b", content="hi")

    await wth.publish_turn_run_status(bus, msg, "running")
    assert wth.websocket_turn_wall_started_at("chat-b") is not None

    await wth.publish_turn_run_status(bus, msg, "idle")
    assert wth.websocket_turn_wall_started_at("chat-b") is None


@pytest.mark.asyncio
async def test_publish_turn_run_status_non_websocket_noop_registry() -> None:
    bus = MagicMock()
    bus.publish_outbound = AsyncMock()
    msg = InboundMessage(channel="telegram", sender_id="u", chat_id="1", content="hi")

    await wth.publish_turn_run_status(bus, msg, "running")

    assert wth._WEBSOCKET_TURN_WALL_STARTED_AT == {}


@pytest.mark.asyncio
async def test_fallback_model_is_scoped_to_its_websocket_chat() -> None:
    bus = MagicMock()
    bus.publish_outbound = AsyncMock()
    observer = wth.build_webui_fallback_model_observer(bus)

    with request_context(
        RequestContext(
            channel="websocket",
            chat_id="chat-model",
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


@pytest.mark.asyncio
async def test_fallback_model_ignores_non_websocket_requests() -> None:
    bus = MagicMock()
    bus.publish_outbound = AsyncMock()
    observer = wth.build_webui_fallback_model_observer(bus)

    with request_context(RequestContext(channel="telegram", chat_id="chat-model")):
        await observer("fallback")

    bus.publish_outbound.assert_not_awaited()
