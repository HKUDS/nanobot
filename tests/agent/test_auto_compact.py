"""Tests for auto compact (idle TTL) feature."""

import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import AgentDefaults
from nanobot.command import CommandContext
from nanobot.providers.base import LLMResponse


def _make_loop(
    tmp_path: Path,
    session_ttl_minutes: int = 15,
) -> AgentLoop:
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


def _add_turns(session, turns: int, *, prefix: str = "msg") -> None:
    """Append simple user/assistant turns to a session."""
    for i in range(turns):
        session.add_message("user", f"{prefix} user {i}")
        session.add_message("assistant", f"{prefix} assistant {i}")


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

    def test_user_friendly_alias_is_supported(self):
        """Config should accept idleCompactAfterMinutes as the preferred JSON key."""
        defaults = AgentDefaults.model_validate({"idleCompactAfterMinutes": 30})
        assert defaults.session_ttl_minutes == 30

    def test_legacy_alias_is_still_supported(self):
        """Config should still accept the old sessionTtlMinutes key for compatibility."""
        defaults = AgentDefaults.model_validate({"sessionTtlMinutes": 30})
        assert defaults.session_ttl_minutes == 30

    def test_serializes_with_user_friendly_alias(self):
        """Config dumps should use idleCompactAfterMinutes for JSON output."""
        defaults = AgentDefaults(session_ttl_minutes=30)
        data = defaults.model_dump(mode="json", by_alias=True)
        assert data["idleCompactAfterMinutes"] == 30
        assert "sessionTtlMinutes" not in data

    def test_session_history_and_file_cap_are_internal_constants(self):
        """Session history/file cap should be internal constants, not config fields."""
        from nanobot.session.manager import HISTORY_MAX_MESSAGES, FILE_MAX_MESSAGES
        assert HISTORY_MAX_MESSAGES == 120
        assert FILE_MAX_MESSAGES == 2000


class TestAgentLoopTTLParam:
    """Test that AutoCompact receives and stores session_ttl_minutes."""

    def test_loop_stores_ttl(self, tmp_path):
        """AutoCompact should store the TTL value."""
        loop = _make_loop(tmp_path, session_ttl_minutes=25)
        assert loop.auto_compact._ttl == 25

    def test_loop_default_ttl_zero(self, tmp_path):
        """AutoCompact default TTL should be 0 (disabled)."""
        loop = _make_loop(tmp_path, session_ttl_minutes=0)
        assert loop.auto_compact._ttl == 0

    @pytest.mark.asyncio
    async def test_process_message_reads_history_with_token_budget(self, tmp_path):
        """_process_message should pass an auto-derived token budget to get_history."""
        loop = _make_loop(tmp_path)
        session = loop.sessions.get_or_create("cli:direct")
        session.get_history = MagicMock(return_value=[])
        loop.context.build_messages = MagicMock(return_value=[])
        loop._run_agent_loop = AsyncMock(return_value=("ok", [], [], "stop", False))
        loop._save_turn = MagicMock()

        msg = InboundMessage(
            channel="cli",
            sender_id="u1",
            chat_id="direct",
            content="hello",
        )
        await loop._process_message(msg)
        session.get_history.assert_called_once()
        kwargs = session.get_history.call_args.kwargs
        assert isinstance(kwargs.get("max_tokens"), int)
        assert kwargs["max_tokens"] > 0
        assert kwargs["include_timestamps"] is True

    @pytest.mark.asyncio
    async def test_session_file_cap_archives_and_trims_old_messages(self, tmp_path):
        loop = _make_loop(tmp_path)
        loop.context.memory.raw_archive = MagicMock()

        for i in range(4):
            msg = InboundMessage(
                channel="cli",
                sender_id="u1",
                chat_id="direct",
                content=f"hello {i}",
            )
            await loop._process_message(msg)

        session = loop.sessions.get_or_create("cli:direct")
        from nanobot.session.manager import FILE_MAX_MESSAGES
        assert len(session.messages) <= FILE_MAX_MESSAGES

    def test_session_enforce_file_cap_skips_archive_when_dropped_prefix_already_consolidated(self, tmp_path):
        from nanobot.session.manager import Session
        archive_fn = MagicMock()
        session = Session(key="cli:direct")
        for i in range(8):
            session.add_message("user", f"u{i}")
        session.last_consolidated = 6

        session.enforce_file_cap(on_archive=archive_fn, limit=4)

        assert len(session.messages) <= 4
        archive_fn.assert_not_called()

    def test_session_enforce_file_cap_archives_only_unconsolidated_dropped_prefix(self, tmp_path):
        from nanobot.session.manager import Session
        archive_fn = MagicMock()
        session = Session(key="cli:direct")
        for i in range(8):
            session.add_message("user", f"u{i}")
        session.last_consolidated = 2

        session.enforce_file_cap(on_archive=archive_fn, limit=4)

        assert len(session.messages) <= 4
        archive_fn.assert_called_once()
        archived = archive_fn.call_args.args[0]
        assert [m["content"] for m in archived] == ["u2", "u3"]


class TestAutoCompact:
    """Test the _archive method."""

    @pytest.mark.asyncio
    async def test_is_expired_boundary(self, tmp_path):
        """Exactly at TTL boundary should be expired (>= not >)."""
        loop = _make_loop(tmp_path, session_ttl_minutes=15)
        ts = datetime.now() - timedelta(minutes=15)
        assert loop.auto_compact._is_expired(ts) is True
        ts2 = datetime.now() - timedelta(minutes=14, seconds=59)
        assert loop.auto_compact._is_expired(ts2) is False
        await loop.close_mcp()

    @pytest.mark.asyncio
    async def test_is_expired_string_timestamp(self, tmp_path):
        """_is_expired should parse ISO string timestamps."""
        loop = _make_loop(tmp_path, session_ttl_minutes=15)
        ts = (datetime.now() - timedelta(minutes=20)).isoformat()
        assert loop.auto_compact._is_expired(ts) is True
        assert loop.auto_compact._is_expired(None) is False
        assert loop.auto_compact._is_expired("") is False
        await loop.close_mcp()

    @pytest.mark.asyncio
    async def test_check_expired_only_archives_expired_sessions(self, tmp_path):
        """With multiple sessions, only the expired one should be archived."""
        loop = _make_loop(tmp_path, session_ttl_minutes=15)
        # Expired session
        s1 = loop.sessions.get_or_create("cli:expired")
        s1.add_message("user", "old")
        s1.updated_at = datetime.now() - timedelta(minutes=20)
        loop.sessions.save(s1)
        # Active session
        s2 = loop.sessions.get_or_create("cli:active")
        s2.add_message("user", "recent")
        loop.sessions.save(s2)

        async def _fake_archive(messages):
            return "Summary."

        loop.consolidator.archive = _fake_archive
        loop.auto_compact.check_expired(loop._schedule_background)
        await asyncio.sleep(0.1)

        active_after = loop.sessions.get_or_create("cli:active")
        assert len(active_after.messages) == 1
        assert active_after.messages[0]["content"] == "recent"
        await loop.close_mcp()

    @pytest.mark.asyncio
    async def test_auto_compact_archives_prefix_and_keeps_recent_suffix(self, tmp_path):
        """_archive should summarize the old prefix and keep a recent legal suffix."""
        loop = _make_loop(tmp_path, session_ttl_minutes=15)
        session = loop.sessions.get_or_create("cli:test")
        _add_turns(session, 6)
        loop.sessions.save(session)

        archived_messages = []

        async def _fake_archive(messages):
            archived_messages.extend(messages)
            return "Summary."

        loop.consolidator.archive = _fake_archive

        await loop.auto_compact._archive("cli:test")

        assert len(archived_messages) == 4
        session_after = loop.sessions.get_or_create("cli:test")
        assert len(session_after.messages) == loop.auto_compact._RECENT_SUFFIX_MESSAGES
        assert session_after.messages[0]["content"] == "msg user 2"
        assert session_after.messages[-1]["content"] == "msg assistant 5"
        await loop.close_mcp()

    @pytest.mark.asyncio
    async def test_auto_compact_stores_summary(self, tmp_path):
        """_archive should store the summary in _summaries."""
        loop = _make_loop(tmp_path, session_ttl_minutes=15)
        session = loop.sessions.get_or_create("cli:test")
        _add_turns(session, 6, prefix="hello")
        loop.sessions.save(session)

        async def _fake_archive(messages):
            return "User said hello."

        loop.consolidator.archive = _fake_archive

        await loop.auto_compact._archive("cli:test")

        entry = loop.auto_compact._summaries.get("cli:test")
        assert entry is not None
        assert entry[0] == "User said hello."
        session_after = loop.sessions.get_or_create("cli:test")
        assert len(session_after.messages) == loop.auto_compact._RECENT_SUFFIX_MESSAGES
        await loop.close_mcp()

    @pytest.mark.asyncio
    async def test_auto_compact_empty_session(self, tmp_path):
        """_archive on empty session should not archive."""
        loop = _make_loop(tmp_path, session_ttl_minutes=15)
        session = loop.sessions.get_or_create("cli:test")

        archive_called = False

        async def _fake_archive(messages):
            nonlocal archive_called
            archive_called = True
            return "Summary."

        loop.consolidator.archive = _fake_archive

        await loop.auto_compact._archive("cli:test")

        assert not archive_called
        session_after = loop.sessions.get_or_create("cli:test")
        assert len(session_after.messages) == 0
        await loop.close_mcp()

    @pytest.mark.asyncio
    async def test_auto_compact_respects_last_consolidated(self, tmp_path):
        """_archive should only archive un-consolidated messages."""
        loop = _make_loop(tmp_path, session_ttl_minutes=15)
        session = loop.sessions.get_or_create("cli:test")
        _add_turns(session, 14)
        session.last_consolidated = 18
        loop.sessions.save(session)

        archived_count = 0

        async def _fake_archive(messages):
            nonlocal archived_count
            archived_count = len(messages)
            return "Summary."

        loop.consolidator.archive = _fake_archive

        await loop.auto_compact._archive("cli:test")

        assert archived_count == 2
        await loop.close_mcp()


class TestAutoCompactIdleDetection:
    """Test idle detection triggers auto-new in _process_message."""

    @pytest.mark.asyncio
    async def test_no_auto_compact_when_ttl_disabled(self, tmp_path):
        """No auto-new should happen when TTL is 0 (disabled)."""
        loop = _make_loop(tmp_path, session_ttl_minutes=0)
        session = loop.sessions.get_or_create("cli:test")
        session.add_message("user", "old message")
        session.updated_at = datetime.now() - timedelta(minutes=30)
        loop.sessions.save(session)

        msg = InboundMessage(channel="cli", sender_id="user", chat_id="test", content="new msg")
        await loop._process_message(msg)

        session_after = loop.sessions.get_or_create("cli:test")
        assert any(m["content"] == "old message" for m in session_after.messages)
        await loop.close_mcp()

    @pytest.mark.asyncio
    async def test_auto_compact_triggers_on_idle(self, tmp_path):
        """Proactive auto-new archives expired session; _process_message reloads it."""
        loop = _make_loop(tmp_path, session_ttl_minutes=15)
        session = loop.sessions.get_or_create("cli:test")
        _add_turns(session, 6, prefix="old")
        session.updated_at = datetime.now() - timedelta(minutes=20)
        loop.sessions.save(session)

        archived_messages = []

        async def _fake_archive(messages):
            archived_messages.extend(messages)
            return "Summary."

        loop.consolidator.archive = _fake_archive

        # Simulate proactive archive completing before message arrives
        await loop.auto_compact._archive("cli:test")

        msg = InboundMessage(channel="cli", sender_id="user", chat_id="test", content="new msg")
        await loop._process_message(msg)

        session_after = loop.sessions.get_or_create("cli:test")
        assert len(archived_messages) == 4
        assert not any(m["content"] == "old user 0" for m in session_after.messages)
        assert any(m["content"] == "new msg" for m in session_after.messages)
        await loop.close_mcp()

    @pytest.mark.asyncio
    async def test_no_auto_compact_when_active(self, tmp_path):
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
    async def test_auto_compact_does_not_affect_priority_commands(self, tmp_path):
        """Priority commands (/stop, /restart) bypass _process_message entirely via run()."""
        loop = _make_loop(tmp_path, session_ttl_minutes=15)
        session = loop.sessions.get_or_create("cli:test")
        session.add_message("user", "old message")
        session.updated_at = datetime.now() - timedelta(minutes=20)
        loop.sessions.save(session)

        # Priority commands are dispatched in run() before _process_message is called.
        # Simulate that path directly via dispatch_priority.
        raw = "/stop"
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
    async def test_auto_compact_with_slash_new(self, tmp_path):
        """Auto-new fires before /new dispatches; session is cleared twice but idempotent."""
        loop = _make_loop(tmp_path, session_ttl_minutes=15)
        session = loop.sessions.get_or_create("cli:test")
        for i in range(4):
            session.add_message("user", f"msg{i}")
            session.add_message("assistant", f"resp{i}")
        session.updated_at = datetime.now() - timedelta(minutes=20)
        loop.sessions.save(session)

        async def _fake_archive(messages):
            return "Summary."

        loop.consolidator.archive = _fake_archive

        msg = InboundMessage(channel="cli", sender_id="user", chat_id="test", content="/new")
        response = await loop._process_message(msg)

        assert response is not None
        assert "new session started" in response.content.lower()

        session_after = loop.sessions.get_or_create("cli:test")
        # Session is empty (auto-new archived and cleared, /new cleared again)
        assert len(session_after.messages) == 0
        await loop.close_mcp()


class TestAutoCompactSystemMessages:
    """Test that auto-new also works for system messages."""

    @pytest.mark.asyncio
    async def test_auto_compact_triggers_for_system_messages(self, tmp_path):
        """Proactive auto-new archives expired session; system messages reload it."""
        loop = _make_loop(tmp_path, session_ttl_minutes=15)
        session = loop.sessions.get_or_create("cli:test")
        _add_turns(session, 6, prefix="old")
        session.updated_at = datetime.now() - timedelta(minutes=20)
        loop.sessions.save(session)

        async def _fake_archive(messages):
            return "Summary."

        loop.consolidator.archive = _fake_archive

        # Simulate proactive archive completing before system message arrives
        await loop.auto_compact._archive("cli:test")

        msg = InboundMessage(
            channel="system", sender_id="subagent", chat_id="cli:test",
            content="subagent result",
        )
        await loop._process_message(msg)

        session_after = loop.sessions.get_or_create("cli:test")
        assert not any(
            m["content"] == "old user 0"
            for m in session_after.messages
        )
        await loop.close_mcp()


class TestAutoCompactEdgeCases:
    """Edge cases for auto session new."""

    @pytest.mark.asyncio
    async def test_auto_compact_with_nothing_summary(self, tmp_path):
        """Auto-new should not inject when archive produces '(nothing)'."""
        loop = _make_loop(tmp_path, session_ttl_minutes=15)
        session = loop.sessions.get_or_create("cli:test")
        _add_turns(session, 6, prefix="thanks")
        session.updated_at = datetime.now() - timedelta(minutes=20)
        loop.sessions.save(session)

        loop.provider.chat_with_retry = AsyncMock(
            return_value=LLMResponse(content="(nothing)", tool_calls=[])
        )

        await loop.auto_compact._archive("cli:test")

        session_after = loop.sessions.get_or_create("cli:test")
        assert len(session_after.messages) == loop.auto_compact._RECENT_SUFFIX_MESSAGES
        # "(nothing)" summary should not be stored
        assert "cli:test" not in loop.auto_compact._summaries

        await loop.close_mcp()

    @pytest.mark.asyncio
    async def test_auto_compact_archive_failure_still_keeps_recent_suffix(self, tmp_path):
        """Auto-new should keep the recent suffix even if LLM archive falls back to raw dump."""
        loop = _make_loop(tmp_path, session_ttl_minutes=15)
        session = loop.sessions.get_or_create("cli:test")
        _add_turns(session, 6, prefix="important")
        session.updated_at = datetime.now() - timedelta(minutes=20)
        loop.sessions.save(session)

        loop.provider.chat_with_retry = AsyncMock(side_effect=Exception("API down"))

        # Should not raise
        await loop.auto_compact._archive("cli:test")

        session_after = loop.sessions.get_or_create("cli:test")
        assert len(session_after.messages) == loop.auto_compact._RECENT_SUFFIX_MESSAGES

        await loop.close_mcp()

    @pytest.mark.asyncio
    async def test_auto_compact_preserves_runtime_checkpoint_before_check(self, tmp_path):
        """Short expired sessions keep recent messages; checkpoint restore still works on resume."""
        loop = _make_loop(tmp_path, session_ttl_minutes=15)
        session = loop.sessions.get_or_create("cli:test")
        session.metadata[AgentLoop._RUNTIME_CHECKPOINT_KEY] = {
            "assistant_message": {"role": "assistant", "content": "interrupted response"},
            "completed_tool_results": [],
            "pending_tool_calls": [],
        }
        session.add_message("user", "previous message")
        session.updated_at = datetime.now() - timedelta(minutes=20)
        loop.sessions.save(session)

        archived_messages = []

        async def _fake_archive(messages):
            archived_messages.extend(messages)
            return "Summary."

        loop.consolidator.archive = _fake_archive

        # Simulate proactive archive completing before message arrives
        await loop.auto_compact._archive("cli:test")

        msg = InboundMessage(channel="cli", sender_id="user", chat_id="test", content="continue")
        await loop._process_message(msg)

        session_after = loop.sessions.get_or_create("cli:test")
        assert archived_messages == []
        assert any(m["content"] == "previous message" for m in session_after.messages)
        assert any(m["content"] == "interrupted response" for m in session_after.messages)

        await loop.close_mcp()


class TestAutoCompactIntegration:
    """End-to-end test of auto session new feature."""

    @pytest.mark.asyncio
    async def test_full_lifecycle(self, tmp_path):
        """
        Full lifecycle: messages -> idle -> auto-new -> archive -> clear -> summary injected as runtime context.
        """
        loop = _make_loop(tmp_path, session_ttl_minutes=15)
        session = loop.sessions.get_or_create("cli:test")

        # Phase 1: User has a conversation longer than the retained recent suffix
        session.add_message("user", "I'm learning English, teach me past tense")
        session.add_message("assistant", "Past tense is used for actions completed in the past...")
        session.add_message("user", "Give me an example")
        session.add_message("assistant", '"I walked to the store yesterday."')
        session.add_message("user", "Give me another example")
        session.add_message("assistant", '"She visited Paris last year."')
        session.add_message("user", "Quiz me")
        session.add_message("assistant", "What is the past tense of go?")
        session.add_message("user", "I think it is went")
        session.add_message("assistant", "Correct.")
        loop.sessions.save(session)

        # Phase 2: Time passes (simulate idle)
        session.updated_at = datetime.now() - timedelta(minutes=20)
        loop.sessions.save(session)

        # Phase 3: User returns with a new message
        loop.provider.chat_with_retry = AsyncMock(
            return_value=LLMResponse(
                content="User is learning English past tense. Example: 'I walked to the store yesterday.'",
                tool_calls=[],
            )
        )

        msg = InboundMessage(
            channel="cli", sender_id="user", chat_id="test",
            content="Let's continue, teach me present perfect",
        )
        response = await loop._process_message(msg)

        # Phase 4: Verify
        session_after = loop.sessions.get_or_create("cli:test")

        # The oldest messages should be trimmed from live session history
        assert not any(
            "past tense is used" in str(m.get("content", "")) for m in session_after.messages
        )

        # Summary should NOT be persisted in session (ephemeral, one-shot)
        assert not any(
            "[Resumed Session]" in str(m.get("content", "")) for m in session_after.messages
        )
        # Runtime context end marker should NOT be persisted
        assert not any(
            "[/Runtime Context]" in str(m.get("content", "")) for m in session_after.messages
        )

        # Pending summary should be consumed (one-shot)
        assert "cli:test" not in loop.auto_compact._summaries

        # The new message should be processed (response exists)
        assert response is not None

        await loop.close_mcp()

    @pytest.mark.asyncio
    async def test_runtime_context_markers_not_persisted_for_multi_paragraph_turn(self, tmp_path):
        """Auto-compact resume context must not leak runtime markers into persisted session history."""
        loop = _make_loop(tmp_path, session_ttl_minutes=15)
        session = loop.sessions.get_or_create("cli:test")
        session.add_message("user", "old message")
        session.updated_at = datetime.now() - timedelta(minutes=20)
        loop.sessions.save(session)

        async def _fake_archive(messages):
            return "Summary."

        loop.consolidator.archive = _fake_archive

        # Simulate proactive archive completing before message arrives
        await loop.auto_compact._archive("cli:test")

        msg = InboundMessage(
            channel="cli", sender_id="user", chat_id="test",
            content="Paragraph one\n\nParagraph two\n\nParagraph three",
        )
        await loop._process_message(msg)

        session_after = loop.sessions.get_or_create("cli:test")
        assert any(m.get("content") == "old message" for m in session_after.messages)
        for persisted in session_after.messages:
            content = str(persisted.get("content", ""))
            assert "[Runtime Context" not in content
            assert "[/Runtime Context]" not in content
        await loop.close_mcp()


class TestProactiveAutoCompact:
    """Test proactive auto-new on idle ticks (TimeoutError path in run loop)."""

    @staticmethod
    async def _run_check_expired(loop, active_session_keys=()):
        """Helper: run check_expired via callback and wait for background tasks."""
        loop.auto_compact.check_expired(
            loop._schedule_background,
            active_session_keys=active_session_keys,
        )
        await asyncio.sleep(0.1)

    @pytest.mark.asyncio
    async def test_no_check_when_ttl_disabled(self, tmp_path):
        """check_expired should be a no-op when TTL is 0."""
        loop = _make_loop(tmp_path, session_ttl_minutes=0)
        session = loop.sessions.get_or_create("cli:test")
        session.add_message("user", "old message")
        session.updated_at = datetime.now() - timedelta(minutes=30)
        loop.sessions.save(session)

        await self._run_check_expired(loop)

        session_after = loop.sessions.get_or_create("cli:test")
        assert len(session_after.messages) == 1
        await loop.close_mcp()

    @pytest.mark.asyncio
    async def test_proactive_archive_on_idle_tick(self, tmp_path):
        """Expired session should be archived during idle tick."""
        loop = _make_loop(tmp_path, session_ttl_minutes=15)
        session = loop.sessions.get_or_create("cli:test")
        _add_turns(session, 5, prefix="old")
        session.updated_at = datetime.now() - timedelta(minutes=20)
        loop.sessions.save(session)

        archived_messages = []

        async def _fake_archive(messages):
            archived_messages.extend(messages)
            return "User chatted about old things."

        loop.consolidator.archive = _fake_archive

        await self._run_check_expired(loop)

        session_after = loop.sessions.get_or_create("cli:test")
        assert len(session_after.messages) == loop.auto_compact._RECENT_SUFFIX_MESSAGES
        assert len(archived_messages) == 2
        entry = loop.auto_compact._summaries.get("cli:test")
        assert entry is not None
        assert entry[0] == "User chatted about old things."
        await loop.close_mcp()

    @pytest.mark.asyncio
    async def test_no_proactive_archive_when_active(self, tmp_path):
        """Recently active session should NOT be archived on idle tick."""
        loop = _make_loop(tmp_path, session_ttl_minutes=15)
        session = loop.sessions.get_or_create("cli:test")
        session.add_message("user", "recent message")
        loop.sessions.save(session)

        await self._run_check_expired(loop)

        session_after = loop.sessions.get_or_create("cli:test")
        assert len(session_after.messages) == 1
        await loop.close_mcp()

    @pytest.mark.asyncio
    async def test_no_duplicate_archive(self, tmp_path):
        """Should not archive the same session twice if already in progress."""
        loop = _make_loop(tmp_path, session_ttl_minutes=15)
        session = loop.sessions.get_or_create("cli:test")
        _add_turns(session, 6, prefix="old")
        session.updated_at = datetime.now() - timedelta(minutes=20)
        loop.sessions.save(session)

        archive_count = 0
        started = asyncio.Event()
        block_forever = asyncio.Event()

        async def _slow_archive(messages):
            nonlocal archive_count
            archive_count += 1
            started.set()
            await block_forever.wait()
            return "Summary."

        loop.consolidator.archive = _slow_archive

        # First call starts archiving via callback
        loop.auto_compact.check_expired(loop._schedule_background)
        await started.wait()
        assert archive_count == 1

        # Second call should skip (key is in _archiving)
        loop.auto_compact.check_expired(loop._schedule_background)
        await asyncio.sleep(0.05)
        assert archive_count == 1

        # Clean up
        block_forever.set()
        await asyncio.sleep(0.1)
        await loop.close_mcp()

    @pytest.mark.asyncio
    async def test_proactive_archive_error_does_not_block(self, tmp_path):
        """Proactive archive failure should be caught and not block future ticks."""
        loop = _make_loop(tmp_path, session_ttl_minutes=15)
        session = loop.sessions.get_or_create("cli:test")
        _add_turns(session, 6, prefix="old")
        session.updated_at = datetime.now() - timedelta(minutes=20)
        loop.sessions.save(session)

        async def _failing_archive(messages):
            raise RuntimeError("LLM down")

        loop.consolidator.archive = _failing_archive

        # Should not raise
        await self._run_check_expired(loop)

        # Key should be removed from _archiving (finally block)
        assert "cli:test" not in loop.auto_compact._archiving
        await loop.close_mcp()

    @pytest.mark.asyncio
    async def test_proactive_archive_skips_empty_sessions(self, tmp_path):
        """Proactive archive should not call LLM for sessions with no un-consolidated messages."""
        loop = _make_loop(tmp_path, session_ttl_minutes=15)
        session = loop.sessions.get_or_create("cli:test")
        session.updated_at = datetime.now() - timedelta(minutes=20)
        loop.sessions.save(session)

        archive_called = False

        async def _fake_archive(messages):
            nonlocal archive_called
            archive_called = True
            return "Summary."

        loop.consolidator.archive = _fake_archive

        await self._run_check_expired(loop)

        assert not archive_called
        await loop.close_mcp()

    @pytest.mark.asyncio
    async def test_skip_expired_session_with_active_agent_task(self, tmp_path):
        """Expired session with an active agent task should NOT be archived."""
        loop = _make_loop(tmp_path, session_ttl_minutes=15)
        session = loop.sessions.get_or_create("cli:test")
        _add_turns(session, 6, prefix="old")
        session.updated_at = datetime.now() - timedelta(minutes=20)
        loop.sessions.save(session)

        archive_count = 0

        async def _fake_archive(messages):
            nonlocal archive_count
            archive_count += 1
            return "Summary."

        loop.consolidator.archive = _fake_archive

        # Simulate an active agent task for this session
        await self._run_check_expired(loop, active_session_keys={"cli:test"})
        assert archive_count == 0

        session_after = loop.sessions.get_or_create("cli:test")
        assert len(session_after.messages) == 12  # All messages preserved

        await loop.close_mcp()

    @pytest.mark.asyncio
    async def test_archive_after_active_task_completes(self, tmp_path):
        """Session should be archived on next tick after active task completes."""
        loop = _make_loop(tmp_path, session_ttl_minutes=15)
        session = loop.sessions.get_or_create("cli:test")
        _add_turns(session, 6, prefix="old")
        session.updated_at = datetime.now() - timedelta(minutes=20)
        loop.sessions.save(session)

        archive_count = 0

        async def _fake_archive(messages):
            nonlocal archive_count
            archive_count += 1
            return "Summary."

        loop.consolidator.archive = _fake_archive

        # First tick: active task, skip
        await self._run_check_expired(loop, active_session_keys={"cli:test"})
        assert archive_count == 0

        # Second tick: task completed, should archive
        await self._run_check_expired(loop)
        assert archive_count == 1
        await loop.close_mcp()

    @pytest.mark.asyncio
    async def test_partial_active_set_only_archives_inactive_expired(self, tmp_path):
        """With multiple sessions, only the expired+inactive one should be archived."""
        loop = _make_loop(tmp_path, session_ttl_minutes=15)
        # Session A: expired, no active task -> should be archived
        s1 = loop.sessions.get_or_create("cli:expired_idle")
        _add_turns(s1, 6, prefix="old_a")
        s1.updated_at = datetime.now() - timedelta(minutes=20)
        loop.sessions.save(s1)
        # Session B: expired, has active task -> should be skipped
        s2 = loop.sessions.get_or_create("cli:expired_active")
        _add_turns(s2, 6, prefix="old_b")
        s2.updated_at = datetime.now() - timedelta(minutes=20)
        loop.sessions.save(s2)
        # Session C: recent, no active task -> should be skipped
        s3 = loop.sessions.get_or_create("cli:recent")
        s3.add_message("user", "recent")
        loop.sessions.save(s3)

        archive_count = 0

        async def _fake_archive(messages):
            nonlocal archive_count
            archive_count += 1
            return "Summary."

        loop.consolidator.archive = _fake_archive

        await self._run_check_expired(loop, active_session_keys={"cli:expired_active"})

        assert archive_count == 1
        s1_after = loop.sessions.get_or_create("cli:expired_idle")
        assert len(s1_after.messages) == loop.auto_compact._RECENT_SUFFIX_MESSAGES
        s2_after = loop.sessions.get_or_create("cli:expired_active")
        assert len(s2_after.messages) == 12  # Preserved
        s3_after = loop.sessions.get_or_create("cli:recent")
        assert len(s3_after.messages) == 1  # Preserved
        await loop.close_mcp()

    @pytest.mark.asyncio
    async def test_no_reschedule_after_successful_archive(self, tmp_path):
        """Already-archived session should NOT be re-scheduled on subsequent ticks."""
        loop = _make_loop(tmp_path, session_ttl_minutes=15)
        session = loop.sessions.get_or_create("cli:test")
        _add_turns(session, 5, prefix="old")
        session.updated_at = datetime.now() - timedelta(minutes=20)
        loop.sessions.save(session)

        archive_count = 0

        async def _fake_archive(messages):
            nonlocal archive_count
            archive_count += 1
            return "Summary."

        loop.consolidator.archive = _fake_archive

        # First tick: archives the session
        await self._run_check_expired(loop)
        assert archive_count == 1

        # Second tick: should NOT re-schedule (updated_at is fresh after clear)
        await self._run_check_expired(loop)
        assert archive_count == 1  # Still 1, not re-scheduled
        await loop.close_mcp()

    @pytest.mark.asyncio
    async def test_empty_skip_refreshes_updated_at_prevents_reschedule(self, tmp_path):
        """Empty session skip refreshes updated_at, preventing immediate re-scheduling."""
        loop = _make_loop(tmp_path, session_ttl_minutes=15)
        session = loop.sessions.get_or_create("cli:test")
        session.updated_at = datetime.now() - timedelta(minutes=20)
        loop.sessions.save(session)

        archive_count = 0

        async def _fake_archive(messages):
            nonlocal archive_count
            archive_count += 1
            return "Summary."

        loop.consolidator.archive = _fake_archive

        # First tick: skips (no messages), refreshes updated_at
        await self._run_check_expired(loop)
        assert archive_count == 0

        # Second tick: should NOT re-schedule because updated_at is fresh
        await self._run_check_expired(loop)
        assert archive_count == 0
        await loop.close_mcp()

    @pytest.mark.asyncio
    async def test_session_can_be_compacted_again_after_new_messages(self, tmp_path):
        """After successful compact + user sends new messages + idle again, should compact again."""
        loop = _make_loop(tmp_path, session_ttl_minutes=15)
        session = loop.sessions.get_or_create("cli:test")
        _add_turns(session, 5, prefix="first")
        session.updated_at = datetime.now() - timedelta(minutes=20)
        loop.sessions.save(session)

        archive_count = 0

        async def _fake_archive(messages):
            nonlocal archive_count
            archive_count += 1
            return "Summary."

        loop.consolidator.archive = _fake_archive

        # First compact cycle
        await loop.auto_compact._archive("cli:test")
        assert archive_count == 1

        # User returns, sends new messages
        msg = InboundMessage(channel="cli", sender_id="user", chat_id="test", content="second topic")
        await loop._process_message(msg)

        # Simulate idle again
        loop.sessions.invalidate("cli:test")
        session2 = loop.sessions.get_or_create("cli:test")
        session2.updated_at = datetime.now() - timedelta(minutes=20)
        loop.sessions.save(session2)

        # Second compact cycle should succeed
        await loop.auto_compact._archive("cli:test")
        assert archive_count == 2
        await loop.close_mcp()


class TestSummaryPersistence:
    """Test that summary survives restart via session metadata."""

    @pytest.mark.asyncio
    async def test_summary_persisted_in_session_metadata(self, tmp_path):
        """After archive, _last_summary should be in session metadata."""
        loop = _make_loop(tmp_path, session_ttl_minutes=15)
        session = loop.sessions.get_or_create("cli:test")
        _add_turns(session, 6, prefix="hello")
        session.updated_at = datetime.now() - timedelta(minutes=20)
        loop.sessions.save(session)

        async def _fake_archive(messages):
            return "User said hello."

        loop.consolidator.archive = _fake_archive

        await loop.auto_compact._archive("cli:test")

        # Summary should be persisted in session metadata
        session_after = loop.sessions.get_or_create("cli:test")
        meta = session_after.metadata.get("_last_summary")
        assert meta is not None
        assert meta["text"] == "User said hello."
        assert "last_active" in meta
        await loop.close_mcp()

    @pytest.mark.asyncio
    async def test_summary_recovered_after_restart(self, tmp_path):
        """Summary should be recovered from metadata when _summaries is empty (simulates restart)."""
        loop = _make_loop(tmp_path, session_ttl_minutes=15)
        session = loop.sessions.get_or_create("cli:test")
        _add_turns(session, 6, prefix="hello")
        last_active = datetime.now() - timedelta(minutes=20)
        session.updated_at = last_active
        loop.sessions.save(session)

        async def _fake_archive(messages):
            return "User said hello."

        loop.consolidator.archive = _fake_archive

        # Archive
        await loop.auto_compact._archive("cli:test")

        # Simulate restart: clear in-memory state
        loop.auto_compact._summaries.clear()
        loop.sessions.invalidate("cli:test")

        # prepare_session should recover summary from metadata
        reloaded = loop.sessions.get_or_create("cli:test")
        assert len(reloaded.messages) == loop.auto_compact._RECENT_SUFFIX_MESSAGES
        _, summary = loop.auto_compact.prepare_session(reloaded, "cli:test")

        assert summary is not None
        assert "User said hello." in summary
        assert "Inactive for" in summary
        # Metadata should be cleaned up after consumption
        assert "_last_summary" not in reloaded.metadata
        await loop.close_mcp()

    @pytest.mark.asyncio
    async def test_metadata_cleanup_no_leak(self, tmp_path):
        """_last_summary should be removed from metadata after being consumed."""
        loop = _make_loop(tmp_path, session_ttl_minutes=15)
        session = loop.sessions.get_or_create("cli:test")
        _add_turns(session, 6, prefix="hello")
        session.updated_at = datetime.now() - timedelta(minutes=20)
        loop.sessions.save(session)

        async def _fake_archive(messages):
            return "Summary."

        loop.consolidator.archive = _fake_archive

        await loop.auto_compact._archive("cli:test")

        # Clear in-memory to force metadata path
        loop.auto_compact._summaries.clear()
        loop.sessions.invalidate("cli:test")
        reloaded = loop.sessions.get_or_create("cli:test")

        # First call: consumes from metadata
        _, summary = loop.auto_compact.prepare_session(reloaded, "cli:test")
        assert summary is not None

        # Second call: no summary (already consumed)
        _, summary2 = loop.auto_compact.prepare_session(reloaded, "cli:test")
        assert summary2 is None
        assert "_last_summary" not in reloaded.metadata
        await loop.close_mcp()

    @pytest.mark.asyncio
    async def test_metadata_cleanup_on_inmemory_path(self, tmp_path):
        """In-memory _summaries path should also clean up _last_summary from metadata."""
        loop = _make_loop(tmp_path, session_ttl_minutes=15)
        session = loop.sessions.get_or_create("cli:test")
        _add_turns(session, 6, prefix="hello")
        session.updated_at = datetime.now() - timedelta(minutes=20)
        loop.sessions.save(session)

        async def _fake_archive(messages):
            return "Summary."

        loop.consolidator.archive = _fake_archive

        await loop.auto_compact._archive("cli:test")

        # Both _summaries and metadata have the summary
        assert "cli:test" in loop.auto_compact._summaries
        loop.sessions.invalidate("cli:test")
        reloaded = loop.sessions.get_or_create("cli:test")
        assert "_last_summary" in reloaded.metadata

        # In-memory path is taken (no restart)
        _, summary = loop.auto_compact.prepare_session(reloaded, "cli:test")
        assert summary is not None
        # Metadata should also be cleaned up
        assert "_last_summary" not in reloaded.metadata
        await loop.close_mcp()
