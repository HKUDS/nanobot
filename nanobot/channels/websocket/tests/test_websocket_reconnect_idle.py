import json
from collections.abc import Callable
from typing import Any
from unittest.mock import MagicMock

import pytest
from websockets.asyncio.server import ServerConnection

from nanobot.bus.queue import MessageBus
from nanobot.channels.websocket.runtime import WebSocketConfig
from nanobot.session.webui_turns import (
    clear_websocket_turns,
    register_queued_websocket_turn_if_idle,
    websocket_turn_wall_started_at,
)
from nanobot.webui.gateway_services import build_gateway_services
from nanobot.webui.outbound_delivery import WebUIOutboundDelivery


class _RecordingTransport:
    def __init__(self) -> None:
        self.connection = MagicMock(spec=ServerConnection)
        self.frames: list[dict[str, Any]] = []

    def webui_recipients(self, audience: object) -> tuple[ServerConnection, ...]:
        return (self.connection,)

    async def webui_send_raw(
        self, connection: ServerConnection, raw: str, *, label: str = "", on_sent: Callable[[], None] | None = None,
    ) -> None:
        self.frames.append(json.loads(raw))
        if on_sent:
            on_sent()


def _delivery(history, tmp_path) -> tuple[WebUIOutboundDelivery, _RecordingTransport]:
    gateway = build_gateway_services(
        config=WebSocketConfig(allow_from=["*"], websocket_requires_token=False),
        bus=MessageBus(),
        session_manager=history.sessions,
        static_dist_path=None,
        workspace_path=tmp_path,
        default_restrict_to_workspace=False,
        runtime_model_name=None,
        runtime_surface="browser",
        runtime_capabilities_overrides=None,
    )
    transport = _RecordingTransport()
    outbound = WebUIOutboundDelivery(
        transport,
        media=gateway.media,
        transcripts=gateway.transcripts,
        temporary_chats=gateway.temporary_chats,
        session_projection=gateway.session_projection,
    )
    return outbound, transport


@pytest.mark.asyncio
async def test_subscribe_hydration_is_quiet_when_no_turn_active(history, tmp_path):
    outbound, transport = _delivery(history, tmp_path)

    await outbound.hydrate("hydrate-idle-chat")

    assert transport.frames == []


@pytest.mark.asyncio
async def test_subscribe_hydration_pushes_running_when_turn_active(history, tmp_path):
    outbound, transport = _delivery(history, tmp_path)

    chat_id = "hydrate-running-chat"
    assert register_queued_websocket_turn_if_idle(chat_id, "turn-active") is not None
    try:
        started_at = websocket_turn_wall_started_at(chat_id)
        assert started_at is not None
        await outbound.hydrate(chat_id)
    finally:
        clear_websocket_turns(chat_id)

    assert transport.frames == [{
        "event": "goal_status",
        "chat_id": chat_id,
        "status": "running",
        "started_at": started_at,
        "turn_id": "turn-active",
    }]
