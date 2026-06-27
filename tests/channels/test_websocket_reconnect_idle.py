"""Test websocket reconnect pushes idle status when no turn is active."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot.channels.websocket import WebSocketChannel


@pytest.mark.asyncio
async def test_hydrate_after_subscribe_pushes_idle_when_no_turn_active():
    """Reconnecting client should receive idle status when no turn is running."""
    channel = WebSocketChannel.__new__(WebSocketChannel)
    channel.gateway = MagicMock()
    channel.gateway.session_manager = MagicMock()
    channel.gateway.session_manager.read_session_file = MagicMock(return_value={})
    
    sent_events = []
    
    async def mock_send_goal_state(chat_id, blob):
        sent_events.append(("goal_state", chat_id, blob))
    
    async def mock_send_goal_status(chat_id, status, **kwargs):
        sent_events.append(("goal_status", chat_id, status, kwargs))
    
    channel.send_goal_state = mock_send_goal_state
    channel.send_goal_status = mock_send_goal_status
    
    with patch("nanobot.channels.websocket.websocket_turn_wall_started_at", return_value=None):
        await channel._hydrate_after_subscribe("test-chat")
    
    # Should have pushed idle status
    assert any(e[0] == "goal_status" and e[2] == "idle" for e in sent_events)


@pytest.mark.asyncio
async def test_hydrate_after_subscribe_pushes_running_when_turn_active():
    """Reconnecting client should receive running status when turn is active."""
    channel = WebSocketChannel.__new__(WebSocketChannel)
    channel.gateway = MagicMock()
    channel.gateway.session_manager = MagicMock()
    channel.gateway.session_manager.read_session_file = MagicMock(return_value={})
    
    sent_events = []
    
    async def mock_send_goal_state(chat_id, blob):
        sent_events.append(("goal_state", chat_id, blob))
    
    async def mock_send_goal_status(chat_id, status, **kwargs):
        sent_events.append(("goal_status", chat_id, status, kwargs))
    
    channel.send_goal_state = mock_send_goal_state
    channel.send_goal_status = mock_send_goal_status
    
    with patch("nanobot.channels.websocket.websocket_turn_wall_started_at", return_value=1234567890.0):
        await channel._hydrate_after_subscribe("test-chat")
    
    # Should have pushed running status with started_at
    running_events = [e for e in sent_events if e[0] == "goal_status" and e[2] == "running"]
    assert len(running_events) == 1
    assert running_events[0][3]["started_at"] == 1234567890.0
