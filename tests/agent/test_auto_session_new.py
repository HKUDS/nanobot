"""Tests for auto session new (idle TTL) feature."""

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock
from pathlib import Path

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import AgentDefaults
from nanobot.providers.base import LLMResponse


def _make_loop(tmp_path: Path, session_ttl_minutes: int = 15) -> AgentLoop:
    """Create a minimal AgentLoop for testing."""
    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    provider.estimate_prompt_tokens.return_value = (10_000, "test")
    provider.chat_with_retry = AsyncMock(return_value=LLMResponse(content="ok", tool_calls=[]))
    provider.generation.max_tokens = 4096
    loop = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=tmp_path,
        model="test-model",
        context_window_tokens=128_000,
        session_ttl_minutes=session_ttl_minutes,
    )
    loop.tools.get_definitions = MagicMock(return_value=[])
    return loop


class TestSessionTTLConfig:
    """Test session TTL configuration."""

    def test_default_ttl_is_zero(self):
        """Default TTL should be 0 (disabled)."""
        defaults = AgentDefaults()
        assert defaults.session_ttl_minutes == 0

    def test_custom_ttl(self):
        """Custom TTL should be stored correctly."""
        defaults = AgentDefaults(session_ttl_minutes=30)
        assert defaults.session_ttl_minutes == 30

    def test_ttl_zero_means_disabled(self):
        """TTL of 0 means auto-new is disabled."""
        defaults = AgentDefaults()
        assert defaults.session_ttl_minutes == 0


class TestAgentLoopTTLParam:
    """Test that AgentLoop receives and stores session_ttl_minutes."""

    def test_loop_stores_ttl(self, tmp_path):
        """AgentLoop should store the TTL value."""
        loop = _make_loop(tmp_path, session_ttl_minutes=25)
        assert loop._session_ttl_minutes == 25

    def test_loop_default_ttl_zero(self, tmp_path):
        """AgentLoop default TTL should be 0 (disabled)."""
        loop = _make_loop(tmp_path, session_ttl_minutes=0)
        assert loop._session_ttl_minutes == 0


class TestAutoNew:
    """Test the _auto_new method."""

    @pytest.mark.asyncio
    async def test_auto_new_archives_and_clears(self, tmp_path):
        """_auto_new should archive un-consolidated messages and clear session."""
        loop = _make_loop(tmp_path, session_ttl_minutes=15)
        session = loop.sessions.get_or_create("cli:test")
        for i in range(4):
            session.add_message("user", f"msg{i}")
            session.add_message("assistant", f"resp{i}")
        loop.sessions.save(session)

        archived_messages = []

        async def _fake_archive(messages):
            archived_messages.extend(messages)
            return True

        loop.consolidator.archive = _fake_archive

        await loop._auto_new("cli:test")

        assert len(archived_messages) == 8
        session_after = loop.sessions.get_or_create("cli:test")
        assert len(session_after.messages) == 0
        await loop.close_mcp()

    @pytest.mark.asyncio
    async def test_auto_new_injects_summary(self, tmp_path):
        """_auto_new should inject the archive result as a user message."""
        loop = _make_loop(tmp_path, session_ttl_minutes=15)
        session = loop.sessions.get_or_create("cli:test")
        session.add_message("user", "hello")
        session.add_message("assistant", "hi there")
        loop.sessions.save(session)

        async def _fake_archive(messages):
            return True

        loop.consolidator.archive = _fake_archive
        loop.consolidator.store.read_unprocessed_history = lambda since_cursor=0: [
            {"cursor": 1, "timestamp": "2026-01-01 00:00", "content": "User said hello, assistant said hi there."},
        ]

        await loop._auto_new("cli:test")

        session_after = loop.sessions.get_or_create("cli:test")
        assert len(session_after.messages) == 1
        assert session_after.messages[0]["role"] == "user"
        assert "[Session Resumed]" in session_after.messages[0]["content"]
        await loop.close_mcp()

    @pytest.mark.asyncio
    async def test_auto_new_empty_session(self, tmp_path):
        """_auto_new on empty session should not archive and not inject."""
        loop = _make_loop(tmp_path, session_ttl_minutes=15)
        session = loop.sessions.get_or_create("cli:test")

        archive_called = False

        async def _fake_archive(messages):
            nonlocal archive_called
            archive_called = True
            return True

        loop.consolidator.archive = _fake_archive

        await loop._auto_new("cli:test")

        assert not archive_called
        session_after = loop.sessions.get_or_create("cli:test")
        assert len(session_after.messages) == 0
        await loop.close_mcp()

    @pytest.mark.asyncio
    async def test_auto_new_respects_last_consolidated(self, tmp_path):
        """_auto_new should only archive un-consolidated messages."""
        loop = _make_loop(tmp_path, session_ttl_minutes=15)
        session = loop.sessions.get_or_create("cli:test")
        for i in range(10):
            session.add_message("user", f"msg{i}")
            session.add_message("assistant", f"resp{i}")
        session.last_consolidated = 18
        loop.sessions.save(session)

        archived_count = 0

        async def _fake_archive(messages):
            nonlocal archived_count
            archived_count = len(messages)
            return True

        loop.consolidator.archive = _fake_archive

        await loop._auto_new("cli:test")

        assert archived_count == 2
        await loop.close_mcp()


class TestAutoNewIdleDetection:
    """Test idle detection triggers auto-new in _process_message."""

    @pytest.mark.asyncio
    async def test_no_auto_new_when_ttl_disabled(self, tmp_path):
        """No auto-new should happen when TTL is 0 (disabled)."""
        loop = _make_loop(tmp_path, session_ttl_minutes=0)
        session = loop.sessions.get_or_create("cli:test")
        session.add_message("user", "old message")
        session.updated_at = datetime.now() - timedelta(minutes=30)
        loop.sessions.save(session)

        msg = InboundMessage(channel="cli", sender_id="user", chat_id="test", content="new msg")
        await loop._process_message(msg)

        session_after = loop.sessions.get_or_create("cli:test")
        assert len(session_after.messages) >= 1
        await loop.close_mcp()

    @pytest.mark.asyncio
    async def test_auto_new_triggers_on_idle(self, tmp_path):
        """Auto-new should trigger when idle exceeds TTL."""
        loop = _make_loop(tmp_path, session_ttl_minutes=15)
        session = loop.sessions.get_or_create("cli:test")
        session.add_message("user", "old message")
        session.updated_at = datetime.now() - timedelta(minutes=20)
        loop.sessions.save(session)

        async def _fake_archive(messages):
            return True

        loop.consolidator.archive = _fake_archive

        msg = InboundMessage(channel="cli", sender_id="user", chat_id="test", content="new msg")
        await loop._process_message(msg)

        session_after = loop.sessions.get_or_create("cli:test")
        assert not any(m["content"] == "old message" for m in session_after.messages)
        await loop.close_mcp()

    @pytest.mark.asyncio
    async def test_no_auto_new_when_active(self, tmp_path):
        """No auto-new should happen when session is recently active."""
        loop = _make_loop(tmp_path, session_ttl_minutes=15)
        session = loop.sessions.get_or_create("cli:test")
        session.add_message("user", "recent message")
        loop.sessions.save(session)

        msg = InboundMessage(channel="cli", sender_id="user", chat_id="test", content="new msg")
        await loop._process_message(msg)

        session_after = loop.sessions.get_or_create("cli:test")
        assert any(m["content"] == "recent message" for m in session_after.messages)
        await loop.close_mcp()

    @pytest.mark.asyncio
    async def test_auto_new_does_not_affect_priority_commands(self, tmp_path):
        """Priority commands (/stop, /restart) bypass _process_message entirely via run()."""
        loop = _make_loop(tmp_path, session_ttl_minutes=15)
        session = loop.sessions.get_or_create("cli:test")
        session.add_message("user", "old message")
        session.updated_at = datetime.now() - timedelta(minutes=20)
        loop.sessions.save(session)

        # Priority commands are dispatched in run() before _process_message is called.
        # Simulate that path directly via dispatch_priority.
        raw = "/stop"
        from nanobot.command import CommandContext
        msg = InboundMessage(channel="cli", sender_id="user", chat_id="test", content=raw)
        ctx = CommandContext(msg=msg, session=session, key="cli:test", raw=raw, loop=loop)
        result = await loop.commands.dispatch_priority(ctx)
        assert result is not None
        assert "stopped" in result.content.lower() or "no active task" in result.content.lower()

        # Session should be untouched since priority commands skip _process_message
        session_after = loop.sessions.get_or_create("cli:test")
        assert any(m["content"] == "old message" for m in session_after.messages)
        await loop.close_mcp()

    @pytest.mark.asyncio
    async def test_auto_new_does_not_fire_on_exact_slash_new(self, tmp_path):
        """Manual /new should still work as before (no double auto-new)."""
        loop = _make_loop(tmp_path, session_ttl_minutes=15)
        session = loop.sessions.get_or_create("cli:test")
        for i in range(4):
            session.add_message("user", f"msg{i}")
            session.add_message("assistant", f"resp{i}")
        session.updated_at = datetime.now() - timedelta(minutes=20)
        loop.sessions.save(session)

        async def _fake_archive(messages):
            return True

        loop.consolidator.archive = _fake_archive

        msg = InboundMessage(channel="cli", sender_id="user", chat_id="test", content="/new")
        response = await loop._process_message(msg)

        assert response is not None
        assert "new session started" in response.content.lower()

        session_after = loop.sessions.get_or_create("cli:test")
        # /new clears without injecting summary (manual /new behavior preserved)
        assert len(session_after.messages) == 0
        await loop.close_mcp()


class TestAutoNewSystemMessages:
    """Test that auto-new also works for system messages."""

    @pytest.mark.asyncio
    async def test_auto_new_triggers_for_system_messages(self, tmp_path):
        """Auto-new should also apply to system-originated messages."""
        loop = _make_loop(tmp_path, session_ttl_minutes=15)
        session = loop.sessions.get_or_create("cli:test")
        session.add_message("user", "old message from subagent context")
        session.updated_at = datetime.now() - timedelta(minutes=20)
        loop.sessions.save(session)

        async def _fake_archive(messages):
            return True

        loop.consolidator.archive = _fake_archive

        msg = InboundMessage(
            channel="system", sender_id="subagent", chat_id="cli:test",
            content="subagent result",
        )
        await loop._process_message(msg)

        session_after = loop.sessions.get_or_create("cli:test")
        assert not any(
            m["content"] == "old message from subagent context"
            for m in session_after.messages
        )
        await loop.close_mcp()
