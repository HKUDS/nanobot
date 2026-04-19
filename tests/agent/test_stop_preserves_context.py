"""Tests for /stop preserving partial context from interrupted turns.

When /stop cancels an active task, the runtime checkpoint (tool results,
assistant messages accumulated so far) should be materialized into session
history rather than silently discarded.

See: https://github.com/HKUDS/nanobot/issues/2966
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import MagicMock, patch, AsyncMock

import pytest

from nanobot.agent.loop import AgentLoop


@pytest.fixture
def mock_loop():
    """Create a minimal AgentLoop with mocked dependencies."""
    with patch.object(AgentLoop, "__init__", lambda self: None):
        loop = AgentLoop()
        loop.sessions = MagicMock()
        loop._pending_queues = {}
        loop._session_locks = {}
        loop._active_tasks = {}
        loop._concurrency_gate = None
        loop._RUNTIME_CHECKPOINT_KEY = "runtime_checkpoint"
        loop._PENDING_USER_TURN_KEY = "pending_user_turn"
        loop.bus = MagicMock()
        loop.bus.publish_outbound = AsyncMock()
        loop.bus.publish_inbound = AsyncMock()
        loop.commands = MagicMock()
        loop.commands.dispatch_priority = AsyncMock(return_value=None)
        return loop


class TestStopPreservesContext:
    """Verify that /stop restores partial context via checkpoint."""

    def test_restore_checkpoint_method_exists(self, mock_loop):
        """AgentLoop should have _restore_runtime_checkpoint."""
        assert hasattr(mock_loop, "_restore_runtime_checkpoint")

    def test_checkpoint_key_constant(self, mock_loop):
        """The runtime checkpoint key should be defined."""
        assert mock_loop._RUNTIME_CHECKPOINT_KEY == "runtime_checkpoint"

    def test_cancel_dispatch_restores_checkpoint(self, mock_loop):
        """When a task is cancelled, the checkpoint should be restored."""
        # Create a mock session with a checkpoint
        session = MagicMock()
        session.metadata = {
            "runtime_checkpoint": {
                "phase": "awaiting_tools",
                "iteration": 0,
                "assistant_message": {
                    "role": "assistant",
                    "content": "Let me search for that.",
                    "tool_calls": [{"id": "tc_1", "type": "function",
                                    "function": {"name": "web_search", "arguments": "{}"}}],
                },
                "completed_tool_results": [
                    {"role": "tool", "tool_call_id": "tc_1",
                     "content": "Search results: ..."},
                ],
                "pending_tool_calls": [],
            }
        }
        session.messages = [
            {"role": "user", "content": "Search for something"},
        ]
        mock_loop.sessions.get_or_create.return_value = session

        # The restore method should add checkpoint messages to session history
        restored = mock_loop._restore_runtime_checkpoint(session)
        assert restored is True
        # After restore, session should have more messages
        assert len(session.messages) > 1
        # The checkpoint should be cleared
        assert "runtime_checkpoint" not in session.metadata
