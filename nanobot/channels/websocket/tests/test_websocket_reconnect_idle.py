"""Test websocket subscribe hydration only replays known active turns."""

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from websockets.asyncio.server import ServerConnection

from nanobot.bus.queue import MessageBus
from nanobot.channels.websocket.runtime import WebSocketConfig
from nanobot.webui.gateway_services import build_gateway_services
from nanobot.webui.outbound_delivery import WebUIOutboundDelivery


class _RecordingTransport:
    def __init__(self) -> None:
        self.connection = MagicMock(spec=ServerConnection)
        self.frames: list[dict[str, Any]] = []

    def webui_recipients(self, audience: object) -> tuple[ServerConnection, ...]:
        return (self.connection,)

    async def webui_send_raw(
        self, connection: ServerConnection, raw: str, *, label: str = "",
    ) -> None:
        self.frames.append(json.loads(raw))


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
    """Subscribe hydration must not inject an idle event into normal message order."""
    outbound, transport = _delivery(history, tmp_path)

    with patch("nanobot.webui.session_projection.websocket_turn_wall_started_at", return_value=None):
        await outbound.hydrate("test-chat")

    assert transport.frames == []


@pytest.mark.asyncio
async def test_subscribe_hydration_pushes_running_when_turn_active(history, tmp_path):
    """Reconnecting client should receive running status when turn is active."""
    outbound, transport = _delivery(history, tmp_path)

    with (
        patch(
            "nanobot.webui.session_projection.websocket_turn_wall_started_at",
            return_value=1234567890.0,
        ),
        patch(
            "nanobot.webui.session_projection.websocket_turn_id",
            return_value="turn-active",
        ),
    ):
        await outbound.hydrate("test-chat")

    assert transport.frames == [{
        "event": "goal_status",
        "chat_id": "test-chat",
        "status": "running",
        "started_at": 1234567890.0,
        "turn_id": "turn-active",
    }]
