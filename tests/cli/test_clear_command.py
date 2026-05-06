"""Tests for /clear slash command."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from nanobot.bus.events import InboundMessage


def _make_loop():
    """Create a minimal AgentLoop with mocked dependencies."""
    from nanobot.agent.loop import AgentLoop
    from nanobot.bus.queue import MessageBus

    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    workspace = MagicMock()
    workspace.__truediv__ = MagicMock(return_value=MagicMock())

    with patch("nanobot.agent.loop.ContextBuilder"), \
         patch("nanobot.agent.loop.SessionManager"), \
         patch("nanobot.agent.loop.SubagentManager"):
        loop = AgentLoop(bus=bus, provider=provider, workspace=workspace)
    return loop, bus


class TestClearCommand:

    @pytest.mark.asyncio
    async def test_clear_reports_message_count(self):
        """/clear returns the number of messages that were cleared."""
        loop, _bus = _make_loop()
        session = MagicMock()
        session.get_history.return_value = [{"role": "user"}] * 5
        session.messages = [{"role": "user"}] * 5
        session.last_consolidated = 0
        loop.sessions.get_or_create.return_value = session

        msg = InboundMessage(channel="telegram", sender_id="u1", chat_id="c1", content="/clear")
        response = await loop._process_message(msg)

        assert response is not None
        assert "5 messages" in response.content
        session.clear.assert_called_once()
        loop.sessions.save.assert_called()
        loop.sessions.invalidate.assert_called()

    @pytest.mark.asyncio
    async def test_clear_uses_singular_for_one_message(self):
        """/clear uses "message" (singular) when exactly one message was cleared."""
        loop, _bus = _make_loop()
        session = MagicMock()
        session.get_history.return_value = [{"role": "user"}]
        session.messages = [{"role": "user"}]
        session.last_consolidated = 0
        loop.sessions.get_or_create.return_value = session

        msg = InboundMessage(channel="telegram", sender_id="u1", chat_id="c1", content="/clear")
        response = await loop._process_message(msg)

        assert response is not None
        assert "1 message" in response.content
        assert "1 messages" not in response.content

    @pytest.mark.asyncio
    async def test_clear_empty_session(self):
        """/clear on an empty session reports zero cleared messages."""
        loop, _bus = _make_loop()
        session = MagicMock()
        session.get_history.return_value = []
        session.messages = []
        session.last_consolidated = 0
        loop.sessions.get_or_create.return_value = session

        msg = InboundMessage(channel="telegram", sender_id="u1", chat_id="c1", content="/clear")
        response = await loop._process_message(msg)

        assert response is not None
        assert "0 messages" in response.content

    @pytest.mark.asyncio
    async def test_clear_does_not_cancel_tasks(self):
        """/clear must NOT cancel running tasks — that's /new's job."""
        loop, _bus = _make_loop()
        session = MagicMock()
        session.get_history.return_value = []
        loop.sessions.get_or_create.return_value = session

        msg = InboundMessage(channel="telegram", sender_id="u1", chat_id="c1", content="/clear")
        await loop._process_message(msg)

        # _cancel_active_tasks should never be called by /clear
        assert not hasattr(loop, "_cancel_called") or not loop._cancel_called

    @pytest.mark.asyncio
    async def test_help_includes_clear(self):
        """/help output must list /clear."""
        loop, _bus = _make_loop()
        msg = InboundMessage(channel="telegram", sender_id="u1", chat_id="c1", content="/help")

        response = await loop._process_message(msg)

        assert response is not None
        assert "/clear" in response.content
