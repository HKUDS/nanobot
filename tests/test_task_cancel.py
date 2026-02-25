"""Tests for the command system and task cancellation."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot.agent.commands import (
    COMMANDS,
    get_help_text,
    is_immediate_command,
    parse_command,
)


# ---------------------------------------------------------------------------
# commands.py unit tests
# ---------------------------------------------------------------------------

class TestParseCommand:
    def test_slash_command(self):
        assert parse_command("/stop") == "/stop"

    def test_slash_command_with_args(self):
        assert parse_command("/new some args") == "/new"

    def test_not_a_command(self):
        assert parse_command("hello world") is None

    def test_empty_string(self):
        assert parse_command("") is None

    def test_leading_whitespace(self):
        assert parse_command("  /help") == "/help"

    def test_uppercase_normalized(self):
        assert parse_command("/STOP") == "/stop"


class TestIsImmediateCommand:
    def test_stop_is_immediate(self):
        assert is_immediate_command("/stop") is True

    def test_new_is_not_immediate(self):
        assert is_immediate_command("/new") is False

    def test_help_is_not_immediate(self):
        assert is_immediate_command("/help") is False

    def test_unknown_command(self):
        assert is_immediate_command("/unknown") is False


class TestGetHelpText:
    def test_contains_all_commands(self):
        text = get_help_text()
        for cmd in COMMANDS:
            assert cmd in text

    def test_contains_descriptions(self):
        text = get_help_text()
        for defn in COMMANDS.values():
            assert defn.description in text

    def test_starts_with_header(self):
        assert get_help_text().startswith("🐈")


# ---------------------------------------------------------------------------
# Task cancellation integration tests
# ---------------------------------------------------------------------------

class TestTaskCancellation:
    """Tests for /stop cancelling an active task in AgentLoop."""

    def _make_loop(self):
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
            loop = AgentLoop(
                bus=bus,
                provider=provider,
                workspace=workspace,
            )
        return loop, bus

    @pytest.mark.asyncio
    async def test_stop_no_active_task(self):
        """'/stop' when nothing is running returns 'No active task'."""
        from nanobot.bus.events import InboundMessage

        loop, bus = self._make_loop()
        msg = InboundMessage(
            channel="test", sender_id="u1", chat_id="c1", content="/stop"
        )
        await loop._handle_immediate_command("/stop", msg)
        out = await asyncio.wait_for(bus.consume_outbound(), timeout=1.0)
        assert "No active task" in out.content

    @pytest.mark.asyncio
    async def test_stop_cancels_active_task(self):
        """'/stop' cancels a running task."""
        from nanobot.bus.events import InboundMessage

        loop, bus = self._make_loop()
        session_key = "test:c1"

        cancelled = asyncio.Event()

        async def slow_task():
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                cancelled.set()
                raise

        task = asyncio.create_task(slow_task())
        await asyncio.sleep(0)  # Let task enter its await
        loop._active_tasks[session_key] = task

        msg = InboundMessage(
            channel="test", sender_id="u1", chat_id="c1", content="/stop"
        )
        await loop._handle_immediate_command("/stop", msg)

        assert cancelled.is_set()
        assert task.cancelled()
        out = await asyncio.wait_for(bus.consume_outbound(), timeout=1.0)
        assert "stopped" in out.content.lower()

    @pytest.mark.asyncio
    async def test_dispatch_registers_and_clears_task(self):
        """_dispatch registers the task in _active_tasks and clears it after."""
        from nanobot.bus.events import InboundMessage, OutboundMessage

        loop, bus = self._make_loop()
        msg = InboundMessage(
            channel="test", sender_id="u1", chat_id="c1", content="hello"
        )

        # Mock _process_message to return a simple response
        loop._process_message = AsyncMock(
            return_value=OutboundMessage(channel="test", chat_id="c1", content="hi")
        )

        task = asyncio.create_task(loop._dispatch(msg))
        await task

        # Task should be cleaned up
        assert msg.session_key not in loop._active_tasks

    @pytest.mark.asyncio
    async def test_dispatch_handles_cancelled_error(self):
        """_dispatch catches CancelledError gracefully."""
        from nanobot.bus.events import InboundMessage

        loop, bus = self._make_loop()
        msg = InboundMessage(
            channel="test", sender_id="u1", chat_id="c1", content="hello"
        )

        async def mock_process(m, **kwargs):
            await asyncio.sleep(60)

        loop._process_message = mock_process

        task = asyncio.create_task(loop._dispatch(msg))
        await asyncio.sleep(0.05)  # Let task start

        assert msg.session_key in loop._active_tasks
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        # Task should be cleaned up even after cancel
        assert msg.session_key not in loop._active_tasks

    @pytest.mark.asyncio
    async def test_processing_lock_serializes(self):
        """Only one message processes at a time due to _processing_lock."""
        from nanobot.bus.events import InboundMessage, OutboundMessage

        loop, bus = self._make_loop()
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

        # Should be serialized: start-a, end-a, start-b, end-b
        assert order == ["start-a", "end-a", "start-b", "end-b"]


# ---------------------------------------------------------------------------


class TestSubagentCancellation:
    """Tests for /stop cancelling subagents spawned under a session."""

    @pytest.mark.asyncio
    async def test_cancel_by_session(self):
        """cancel_by_session cancels all tasks for that session."""
        from nanobot.agent.subagent import SubagentManager
        from nanobot.bus.queue import MessageBus

        bus = MessageBus()
        provider = MagicMock()
        provider.get_default_model.return_value = "test-model"
        mgr = SubagentManager(provider=provider, workspace=MagicMock(), bus=bus)

        cancelled = asyncio.Event()

        async def slow_subagent():
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                cancelled.set()
                raise

        task = asyncio.create_task(slow_subagent())
        await asyncio.sleep(0)
        tid = "sub-1"
        session_key = "test:c1"
        mgr._running_tasks[tid] = task
        mgr._session_tasks[session_key] = {tid}

        count = await mgr.cancel_by_session(session_key)
        assert count == 1
        assert cancelled.is_set()
        assert task.cancelled()

    @pytest.mark.asyncio
    async def test_cancel_by_session_no_tasks(self):
        """cancel_by_session returns 0 when no subagents for session."""
        from nanobot.agent.subagent import SubagentManager
        from nanobot.bus.queue import MessageBus

        bus = MessageBus()
        provider = MagicMock()
        provider.get_default_model.return_value = "test-model"
        mgr = SubagentManager(provider=provider, workspace=MagicMock(), bus=bus)

        count = await mgr.cancel_by_session("nonexistent:session")
        assert count == 0

    @pytest.mark.asyncio
    async def test_stop_cancels_subagents_via_loop(self):
        """/stop on AgentLoop also cancels subagents for that session."""
        from nanobot.agent.loop import AgentLoop
        from nanobot.bus.events import InboundMessage
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

        # Replace subagents with a real SubagentManager
        from nanobot.agent.subagent import SubagentManager
        loop.subagents = SubagentManager(
            provider=provider, workspace=MagicMock(), bus=bus
        )

        cancelled = asyncio.Event()
        session_key = "test:c1"

        async def slow_sub():
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                cancelled.set()
                raise

        task = asyncio.create_task(slow_sub())
        await asyncio.sleep(0)
        loop.subagents._running_tasks["sub-1"] = task
        loop.subagents._session_tasks[session_key] = {"sub-1"}

        msg = InboundMessage(
            channel="test", sender_id="u1", chat_id="c1", content="/stop"
        )
        await loop._handle_immediate_command("/stop", msg)

        assert cancelled.is_set()
        out = await asyncio.wait_for(bus.consume_outbound(), timeout=1.0)
        assert "stopped" in out.content.lower() or "background" in out.content.lower()
