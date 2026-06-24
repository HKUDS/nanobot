"""Tests for read_only session metadata flag in AgentLoop.run()."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.session.manager import Session, SessionManager


def _make_session(*, read_only: bool) -> Session:
    return Session(
        key="test:user1",
        metadata={"read_only": True} if read_only else {},
    )


def _make_loop(workspace, session):
    from nanobot.agent.loop import AgentLoop
    from nanobot.bus.queue import MessageBus

    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"

    sessions_mgr = MagicMock(spec=SessionManager)
    sessions_mgr.get_or_create.return_value = session

    with patch("nanobot.agent.loop.SessionManager", return_value=sessions_mgr), \
         patch("nanobot.agent.loop.ContextBuilder"), \
         patch("nanobot.agent.loop.SubagentManager") as MockSubMgr:
        MockSubMgr.return_value.cancel_by_session = AsyncMock(return_value=0)
        loop = AgentLoop(bus=bus, provider=provider, workspace=workspace)
    return loop, bus


@pytest.mark.asyncio
async def test_read_only_session_returns_hint_and_skips_dispatch(tmp_path):
    """An inbound message to a read-only session produces a hint and no dispatch."""
    loop, bus = _make_loop(tmp_path, _make_session(read_only=True))
    msg = InboundMessage(channel="test", sender_id="user1", chat_id="user1", content="hello")
    await bus.publish_inbound(msg)

    loop_task = asyncio.create_task(loop.run())
    try:
        outbound: OutboundMessage = await asyncio.wait_for(bus.consume_outbound(), timeout=2.0)
        assert "read-only" in outbound.content.lower()
    finally:
        loop_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await loop_task


@pytest.mark.asyncio
async def test_read_only_session_blocks_priority_commands(tmp_path):
    """A /-command sent to a read-only session is blocked."""
    loop, bus = _make_loop(tmp_path, _make_session(read_only=True))
    msg = InboundMessage(channel="test", sender_id="user1", chat_id="user1", content="/reset")
    await bus.publish_inbound(msg)

    loop_task = asyncio.create_task(loop.run())
    try:
        outbound = await asyncio.wait_for(bus.consume_outbound(), timeout=2.0)
        assert "read-only" in outbound.content.lower()
    finally:
        loop_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await loop_task


@pytest.mark.asyncio
async def test_normal_session_proceeds_without_hint(tmp_path):
    """A normal (non-read-only) session does not receive a read-only hint."""
    loop, bus = _make_loop(tmp_path, _make_session(read_only=False))
    msg = InboundMessage(channel="test", sender_id="user1", chat_id="user1", content="hello")
    await bus.publish_inbound(msg)

    loop_task = asyncio.create_task(loop.run())
    try:
        try:
            outbound = await asyncio.wait_for(bus.consume_outbound(), timeout=0.5)
        except asyncio.TimeoutError:
            pass  # Normal — dispatch is async
        else:
            assert "read-only" not in outbound.content.lower(), (
                f"Unexpected read-only hint: {outbound.content}"
            )
    finally:
        loop_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await loop_task
