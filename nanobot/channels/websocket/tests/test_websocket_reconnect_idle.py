"""Test websocket subscribe hydration only replays known active turns."""

from unittest.mock import MagicMock, patch

import pytest

from nanobot.channels.websocket.runtime import WebSocketChannel


@pytest.mark.asyncio
async def test_hydrate_after_subscribe_is_quiet_when_no_turn_active():
    """Subscribe hydration must not inject an idle event into normal message order."""
    channel = WebSocketChannel.__new__(WebSocketChannel)
    channel.gateway = MagicMock()
    channel.gateway.session_manager = MagicMock()
    channel.gateway.session_manager.read_session_file = MagicMock(return_value={})
    channel.gateway.subagent_statuses_for_chat = None
    channel.gateway.subagent_detail_snapshot = None
    channel._turn_models = {}

    sent_events = []

    async def mock_send_goal_state(chat_id, blob):
        sent_events.append(("goal_state", chat_id, blob))

    async def mock_send_goal_status(chat_id, status, **kwargs):
        sent_events.append(("goal_status", chat_id, status, kwargs))

    channel.send_goal_state = mock_send_goal_state
    channel.send_goal_status = mock_send_goal_status

    with patch("nanobot.channels.websocket.runtime.websocket_turn_wall_started_at", return_value=None):
        await channel._hydrate_after_subscribe("test-chat")

    assert sent_events == []


@pytest.mark.asyncio
async def test_hydrate_after_subscribe_pushes_running_when_turn_active():
    """Reconnecting client should receive running status when turn is active."""
    channel = WebSocketChannel.__new__(WebSocketChannel)
    channel.gateway = MagicMock()
    channel.gateway.session_manager = MagicMock()
    channel.gateway.session_manager.read_session_file = MagicMock(return_value={})
    channel.gateway.subagent_statuses_for_chat = None
    channel.gateway.subagent_detail_snapshot = None
    channel._turn_models = {}

    sent_events = []

    async def mock_send_goal_state(chat_id, blob):
        sent_events.append(("goal_state", chat_id, blob))

    async def mock_send_goal_status(chat_id, status, **kwargs):
        sent_events.append(("goal_status", chat_id, status, kwargs))

    channel.send_goal_state = mock_send_goal_state
    channel.send_goal_status = mock_send_goal_status

    with (
        patch(
            "nanobot.channels.websocket.runtime.websocket_turn_wall_started_at",
            return_value=1234567890.0,
        ),
        patch(
            "nanobot.channels.websocket.runtime.websocket_turn_id",
            return_value="turn-active",
        ),
    ):
        await channel._hydrate_after_subscribe("test-chat")

    running_events = [e for e in sent_events if e[0] == "goal_status" and e[2] == "running"]
    assert len(running_events) == 1
    assert running_events[0][3]["started_at"] == 1234567890.0
    assert running_events[0][3]["turn_id"] == "turn-active"


@pytest.mark.asyncio
async def test_hydrate_after_subscribe_replays_details_from_websocket_session_key():
    """Persisted detail records use the full session key, not the wire chat UUID."""
    channel = WebSocketChannel.__new__(WebSocketChannel)
    channel.gateway = MagicMock()
    channel.gateway.session_manager = MagicMock()
    channel.gateway.session_manager.read_session_file = MagicMock(return_value={})
    channel.gateway.subagent_statuses_for_chat = None
    channel.gateway.subagent_detail_snapshot = MagicMock(
        return_value=[{"task_id": "task-1", "label": "第一轮任务", "status": "completed"}],
    )
    channel._turn_models = {}

    sent_events = []

    async def mock_send_detail_snapshot(chat_id, *, items):
        sent_events.append((chat_id, items))

    channel.send_subagent_detail_snapshot = mock_send_detail_snapshot

    await channel._hydrate_after_subscribe("test-chat")

    channel.gateway.subagent_detail_snapshot.assert_called_once_with("websocket:test-chat")
    assert sent_events == [
        ("test-chat", [{"task_id": "task-1", "label": "第一轮任务", "status": "completed"}]),
    ]
