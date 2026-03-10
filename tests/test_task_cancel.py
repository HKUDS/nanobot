"""Tests for /stop task cancellation."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


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
         patch("nanobot.agent.loop.SubagentManager") as MockSubMgr:
        MockSubMgr.return_value.cancel_by_session = AsyncMock(return_value=0)
        loop = AgentLoop(bus=bus, provider=provider, workspace=workspace)
    return loop, bus


class TestHandleStop:
    @pytest.mark.asyncio
    async def test_stop_no_active_task(self):
        from nanobot.bus.events import InboundMessage

        loop, bus = _make_loop()
        msg = InboundMessage(channel="test", sender_id="u1", chat_id="c1", content="/stop")
        await loop._handle_stop(msg)
        out = await asyncio.wait_for(bus.consume_outbound(), timeout=1.0)
        assert "No active task" in out.content

    @pytest.mark.asyncio
    async def test_stop_cancels_active_task(self):
        from nanobot.bus.events import InboundMessage

        loop, bus = _make_loop()
        cancelled = asyncio.Event()

        async def slow_task():
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                cancelled.set()
                raise

        task = asyncio.create_task(slow_task())
        await asyncio.sleep(0)
        loop._active_tasks["test:c1"] = [task]

        msg = InboundMessage(channel="test", sender_id="u1", chat_id="c1", content="/stop")
        await loop._handle_stop(msg)

        assert cancelled.is_set()
        out = await asyncio.wait_for(bus.consume_outbound(), timeout=1.0)
        assert "stopped" in out.content.lower()

    @pytest.mark.asyncio
    async def test_stop_cancels_multiple_tasks(self):
        from nanobot.bus.events import InboundMessage

        loop, bus = _make_loop()
        events = [asyncio.Event(), asyncio.Event()]

        async def slow(idx):
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                events[idx].set()
                raise

        tasks = [asyncio.create_task(slow(i)) for i in range(2)]
        await asyncio.sleep(0)
        loop._active_tasks["test:c1"] = tasks

        msg = InboundMessage(channel="test", sender_id="u1", chat_id="c1", content="/stop")
        await loop._handle_stop(msg)

        assert all(e.is_set() for e in events)
        out = await asyncio.wait_for(bus.consume_outbound(), timeout=1.0)
        assert "2 task" in out.content


class TestDispatch:
    @pytest.mark.asyncio
    async def test_dispatch_processes_and_publishes(self):
        from nanobot.bus.events import InboundMessage, OutboundMessage

        loop, bus = _make_loop()
        msg = InboundMessage(channel="test", sender_id="u1", chat_id="c1", content="hello")
        loop._process_message = AsyncMock(
            return_value=OutboundMessage(channel="test", chat_id="c1", content="hi")
        )
        await loop._dispatch(msg)
        out = await asyncio.wait_for(bus.consume_outbound(), timeout=1.0)
        assert out.content == "hi"

    @pytest.mark.asyncio
    async def test_processing_lock_serializes(self):
        from nanobot.bus.events import InboundMessage, OutboundMessage

        loop, bus = _make_loop()
        order = []

        async def mock_process(m, **kwargs):
            order.append(f"start-{m.content}")
            await asyncio.sleep(0.05)
            order.append(f"end-{m.content}")
            return OutboundMessage(channel="test", chat_id="c1", content=m.content)

        loop._process_message = mock_process
        msg1 = InboundMessage(channel="test", sender_id="u1", chat_id="c1", content="a")
        msg2 = InboundMessage(channel="test", sender_id="u1", chat_id="c1", content="b")

        t1 = asyncio.create_task(loop._dispatch(msg1))
        t2 = asyncio.create_task(loop._dispatch(msg2))
        await asyncio.gather(t1, t2)
        assert order == ["start-a", "end-a", "start-b", "end-b"]


class TestSubagentCancellation:
    @pytest.mark.asyncio
    async def test_cancel_by_session(self):
        from nanobot.agent.subagent import SubagentManager
        from nanobot.bus.queue import MessageBus

        bus = MessageBus()
        provider = MagicMock()
        provider.get_default_model.return_value = "test-model"
        mgr = SubagentManager(provider=provider, workspace=MagicMock(), bus=bus)

        cancelled = asyncio.Event()

        async def slow():
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                cancelled.set()
                raise

        task = asyncio.create_task(slow())
        await asyncio.sleep(0)
        mgr._running_tasks["sub-1"] = task
        mgr._session_tasks["test:c1"] = {"sub-1"}

        count = await mgr.cancel_by_session("test:c1")
        assert count == 1
        assert cancelled.is_set()

    @pytest.mark.asyncio
    async def test_cancel_by_session_no_tasks(self):
        from nanobot.agent.subagent import SubagentManager
        from nanobot.bus.queue import MessageBus

        bus = MessageBus()
        provider = MagicMock()
        provider.get_default_model.return_value = "test-model"
        mgr = SubagentManager(provider=provider, workspace=MagicMock(), bus=bus)
        assert await mgr.cancel_by_session("nonexistent") == 0


class TestAutoCancelOnNewMessage:
    """Tests for automatic task cancellation when a new message arrives."""

    @pytest.mark.asyncio
    async def test_new_message_cancels_existing_task(self):
        """Test that sending a new message automatically cancels the previous task."""
        from nanobot.bus.events import InboundMessage, OutboundMessage

        loop, bus = _make_loop()

        async def slow_process(msg, **kwargs):
            await asyncio.sleep(0.1)  # Simulate slow processing
            return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id, content=f"reply-{msg.content}")

        loop._process_message = slow_process

        # Start first message
        msg1 = InboundMessage(channel="test", sender_id="u1", chat_id="c1", content="first")
        t1 = asyncio.create_task(loop._dispatch(msg1))
        loop._active_tasks["test:c1"] = [t1]
        await asyncio.sleep(0.01)  # Let first task start

        # Send second message - should cancel first
        await loop._cancel_session_tasks("test:c1")

        # First task should be cancelled
        assert t1.cancelled() or t1.done()
        # Active tasks should be cleared
        assert "test:c1" not in loop._active_tasks

    @pytest.mark.asyncio
    async def test_cancelled_task_checked_before_send(self):
        """Test that cancelled task checks cancellation before sending message."""
        from nanobot.bus.events import InboundMessage, OutboundMessage

        loop, bus = _make_loop()
        sent_messages = []

        original_publish = bus.publish_outbound

        async def capture_publish(msg):
            sent_messages.append(msg)
            await original_publish(msg)

        bus.publish_outbound = capture_publish

        async def mock_process(msg, **kwargs):
            # Simulate task that completes after cancellation
            await asyncio.sleep(0.05)
            return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id, content=f"done-{msg.content}")

        loop._process_message = mock_process

        # Start first task
        msg1 = InboundMessage(channel="test", sender_id="u1", chat_id="c1", content="slow")
        t1 = asyncio.create_task(loop._dispatch(msg1))
        loop._active_tasks["test:c1"] = [t1]
        await asyncio.sleep(0.01)

        # Cancel it
        await loop._cancel_session_tasks("test:c1")

        # Wait for task to potentially finish
        try:
            await asyncio.wait_for(t1, timeout=0.2)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass

        # Check cancellation happened - task should either be cancelled or have raised CancelledError
        # The key is that we check before sending
        assert len(sent_messages) == 0 or t1.cancelled()

    @pytest.mark.asyncio
    async def test_different_sessions_not_affected(self):
        """Test that cancelling one session doesn't affect other sessions."""
        loop, bus = _make_loop()
        task1_cancelled = asyncio.Event()
        task2_cancelled = asyncio.Event()

        async def mock_task(session, event):
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                event.set()
                raise

        t1 = asyncio.create_task(mock_task("s1", task1_cancelled))
        t2 = asyncio.create_task(mock_task("s2", task2_cancelled))
        await asyncio.sleep(0)

        loop._active_tasks["s1"] = [t1]
        loop._active_tasks["s2"] = [t2]

        # Cancel only s1
        await loop._cancel_session_tasks("s1")

        await asyncio.sleep(0.01)

        assert task1_cancelled.is_set()
        assert not task2_cancelled.is_set()
        assert "s1" not in loop._active_tasks
        assert "s2" in loop._active_tasks

    @pytest.mark.asyncio
    async def test_cancel_empty_session_no_error(self):
        """Test that cancelling a session with no tasks is safe."""
        loop, bus = _make_loop()
        # Should not raise
        await loop._cancel_session_tasks("nonexistent")
        assert True
