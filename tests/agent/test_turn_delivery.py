from pathlib import Path

from nanobot.agent.turn_delivery import TurnDeliveryFactory
from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.bus.runtime_events import RuntimeEventBus
from nanobot.session.manager import SessionManager
from nanobot.session.webui_turns import WebuiTurnRoutePolicy
from nanobot.webui.metadata import WEBUI_TURN_METADATA_KEY


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
        WEBUI_TURN_METADATA_KEY,
    }
    assert first_visible_route.metadata["webui"] is True
    assert first_visible_route.metadata["_wants_stream"] is True
    first_turn_id = first_visible_route.metadata[WEBUI_TURN_METADATA_KEY]
    second_turn_id = second_visible_route.metadata[WEBUI_TURN_METADATA_KEY]
    assert first_turn_id.startswith("subagent:")
    assert second_turn_id.startswith("subagent:")
    assert first_turn_id != second_turn_id
    assert msg.metadata == {
        "injected_event": "subagent_result",
        "subagent_task_id": "sub-1",
    }
