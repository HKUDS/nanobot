"""Tests for WebSocket turn timing strip bookkeeping."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.tools.context import RequestContext, request_context
from nanobot.bus.events import InboundMessage
from nanobot.bus.outbound_events import GoalStatusEvent, TurnModelUpdatedEvent
from nanobot.session import webui_turns as wth
from nanobot.webui.metadata import WEBSOCKET_TURN_OWNER_METADATA_KEY


@pytest.fixture(autouse=True)
def _clear_turn_wall_clock() -> None:
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
