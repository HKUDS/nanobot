from pathlib import Path

import pytest

from nanobot.agent.turn_delivery import TurnDeliveryFactory
from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.bus.runtime_events import RuntimeEventBus
from nanobot.session.manager import SessionManager
from nanobot.session.webui_turns import WebuiTurnRoutePolicy
from nanobot.webui.metadata import (
    WEBSOCKET_TURN_OWNER_METADATA_KEY,
    WEBUI_TURN_METADATA_KEY,
)


def test_websocket_lifecycles_get_distinct_internal_owners(tmp_path: Path) -> None:
    factory = TurnDeliveryFactory(
        MessageBus(),
        RuntimeEventBus(),
        route_policy=WebuiTurnRoutePolicy(SessionManager(tmp_path / "sessions")),
    )
    first_msg = InboundMessage(
        channel="websocket",
        sender_id="user",
        chat_id="chat-a",
        content="first",
        metadata={WEBSOCKET_TURN_OWNER_METADATA_KEY: "attacker-reused-owner"},
    )
    second_msg = InboundMessage(
        channel="websocket",
        sender_id="user",
        chat_id="chat-a",
        content="second",
        metadata={WEBSOCKET_TURN_OWNER_METADATA_KEY: "attacker-reused-owner"},
    )

    first = factory.create(first_msg, first_msg.session_key)
    second = factory.create(second_msg, second_msg.session_key)
    first_owner = first.lifecycle_message.metadata[WEBSOCKET_TURN_OWNER_METADATA_KEY]
    second_owner = second.lifecycle_message.metadata[WEBSOCKET_TURN_OWNER_METADATA_KEY]

    assert first_owner == first.delivery_message.metadata[WEBSOCKET_TURN_OWNER_METADATA_KEY]
    assert first_owner != second_owner
    assert first_owner != "attacker-reused-owner"
    assert second_owner != "attacker-reused-owner"
    assert WEBUI_TURN_METADATA_KEY not in first.lifecycle_message.metadata
    assert first_msg.metadata[WEBSOCKET_TURN_OWNER_METADATA_KEY] == first_owner
    assert second_msg.metadata[WEBSOCKET_TURN_OWNER_METADATA_KEY] == second_owner


def test_websocket_lifecycle_reuses_registered_ingress_owner(tmp_path: Path) -> None:
    from nanobot.session import webui_turns as wth

    owner = wth.register_queued_websocket_turn_if_idle("chat-queued", "turn-queued")
    assert owner is not None
    msg = InboundMessage(
        channel="websocket",
        sender_id="user",
        chat_id="chat-queued",
        content="queued",
        metadata={
            WEBSOCKET_TURN_OWNER_METADATA_KEY: owner,
            WEBUI_TURN_METADATA_KEY: "turn-queued",
        },
    )
    factory = TurnDeliveryFactory(
        MessageBus(),
        RuntimeEventBus(),
        route_policy=WebuiTurnRoutePolicy(SessionManager(tmp_path / "sessions")),
    )

    try:
        delivery = factory.create(msg, msg.session_key)

        assert delivery.lifecycle_message.metadata[WEBSOCKET_TURN_OWNER_METADATA_KEY] == owner
        assert msg.metadata[WEBSOCKET_TURN_OWNER_METADATA_KEY] == owner
    finally:
        wth.clear_websocket_turn_if_current("chat-queued", owner)


@pytest.mark.asyncio
async def test_same_chat_different_sessions_restore_previous_active_projection(
    tmp_path: Path,
) -> None:
    from unittest.mock import AsyncMock, MagicMock

    from nanobot.session import webui_turns as wth

    factory = TurnDeliveryFactory(
        MessageBus(),
        RuntimeEventBus(),
        route_policy=WebuiTurnRoutePolicy(SessionManager(tmp_path / "sessions")),
    )
    first_msg = InboundMessage(
        channel="websocket",
        sender_id="user",
        chat_id="shared-chat",
        content="first",
        metadata={WEBUI_TURN_METADATA_KEY: "turn-first"},
        session_key_override="websocket:session-first",
    )
    second_msg = InboundMessage(
        channel="websocket",
        sender_id="user",
        chat_id="shared-chat",
        content="second",
        metadata={WEBUI_TURN_METADATA_KEY: "turn-second"},
        session_key_override="websocket:session-second",
    )
    first = factory.create(first_msg, first_msg.session_key)
    second = factory.create(second_msg, second_msg.session_key)
    first_owner = first.lifecycle_message.metadata[WEBSOCKET_TURN_OWNER_METADATA_KEY]
    second_owner = second.lifecycle_message.metadata[WEBSOCKET_TURN_OWNER_METADATA_KEY]
    bus = MagicMock()
    bus.publish_outbound = AsyncMock()

    try:
        await wth.publish_turn_run_status(
            bus,
            first.lifecycle_message,
            "running",
            started_at=100.0,
        )
        await wth.publish_turn_run_status(
            bus,
            second.lifecycle_message,
            "running",
            started_at=200.0,
        )

        assert wth.websocket_turn_wall_started_at("shared-chat") == 200.0
        assert wth.websocket_turn_id("shared-chat") == "turn-second"
        assert wth.clear_websocket_turn_if_current("shared-chat", second_owner) is True
        assert wth.websocket_turn_wall_started_at("shared-chat") == 100.0
        assert wth.websocket_turn_id("shared-chat") == "turn-first"
        assert wth._WEBSOCKET_TURN_OWNERS["shared-chat"] == first_owner
        assert wth.clear_websocket_turn_if_current("shared-chat", first_owner) is True
        assert wth.websocket_turn_wall_started_at("shared-chat") is None
    finally:
        wth._WEBSOCKET_ACTIVE_TURNS.pop("shared-chat", None)
        wth._WEBSOCKET_TURN_WALL_STARTED_AT.pop("shared-chat", None)
        wth._WEBSOCKET_TURN_IDS.pop("shared-chat", None)
        wth._WEBSOCKET_TURN_OWNERS.pop("shared-chat", None)


def test_late_subagent_route_requires_webui_owned_session(tmp_path: Path) -> None:
    sessions = SessionManager(tmp_path)
    factory = TurnDeliveryFactory(
        MessageBus(),
        RuntimeEventBus(),
        route_policy=WebuiTurnRoutePolicy(sessions),
    )
    session_key = "websocket:chat-a"
    msg = InboundMessage(
        channel="system",
        sender_id="subagent",
        chat_id=session_key,
        content="Background research completed",
        session_key_override=session_key,
        metadata={
            "injected_event": "subagent_result",
            "subagent_task_id": "sub-1",
        },
    )

    hidden_route = factory.create(msg, session_key).route

    assert hidden_route.channel == "websocket"
    assert hidden_route.chat_id == "chat-a"
    assert hidden_route.metadata == {}
    assert hidden_route.publish_lifecycle is False

    session = sessions.get_or_create(session_key)
    session.metadata["webui"] = True
    first_visible_route = factory.create(msg, session_key).route
    second_visible_route = factory.create(msg, session_key).route

    assert first_visible_route.publish_lifecycle is True
    assert set(first_visible_route.metadata) == {
        "webui",
        "_wants_stream",
        WEBSOCKET_TURN_OWNER_METADATA_KEY,
        WEBUI_TURN_METADATA_KEY,
    }
    assert first_visible_route.metadata["webui"] is True
    assert first_visible_route.metadata["_wants_stream"] is True
    first_turn_id = first_visible_route.metadata[WEBUI_TURN_METADATA_KEY]
    second_turn_id = second_visible_route.metadata[WEBUI_TURN_METADATA_KEY]
    assert first_turn_id.startswith("subagent:")
    assert second_turn_id.startswith("subagent:")
    assert first_turn_id != second_turn_id
    assert (
        first_visible_route.metadata[WEBSOCKET_TURN_OWNER_METADATA_KEY]
        != second_visible_route.metadata[WEBSOCKET_TURN_OWNER_METADATA_KEY]
    )
    assert msg.metadata == {
        "injected_event": "subagent_result",
        "subagent_task_id": "sub-1",
    }
