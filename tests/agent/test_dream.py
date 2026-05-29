"""Tests for Dream memory consolidation — build_dream_prompt and cursor management."""

import pytest

from nanobot.agent.memory import MemoryStore


@pytest.fixture
def store(tmp_path):
    s = MemoryStore(tmp_path)
    s.write_soul("# Soul\n- Helpful")
    s.write_memory("# Memory\n- Project X active")
    return s


class TestBuildDreamPrompt:
    def test_returns_none_when_no_history(self, store):
        assert store.build_dream_prompt() is None

    def test_returns_prompt_with_history(self, store):
        store.append_history("hello")
        result = store.build_dream_prompt()
        assert result is not None
        prompt, cursor = result
        assert cursor > 0
        assert "## Conversation History" in prompt
        assert "hello" in prompt

    def test_cursor_advances_only_new_entries(self, store):
        store.append_history("first")
        r1 = store.build_dream_prompt()
        assert r1 is not None
        _, c1 = r1

        # Cursor not yet advanced — same entries are still available
        assert store.build_dream_prompt() is not None

        # Advance cursor
        store.set_last_dream_cursor(c1)
        # Now no new entries
        assert store.build_dream_prompt() is None

        # Add new entry
        store.append_history("second")
        r2 = store.build_dream_prompt()
        assert r2 is not None
        _, c2 = r2
        assert c2 > c1

    def test_prompt_includes_skill_creator_path(self, store):
        store.append_history("test")
        result = store.build_dream_prompt()
        assert result is not None
        prompt, _ = result
        assert "skill-creator" in prompt

    def test_truncates_long_entries(self, store):
        long_content = "x" * 2000
        store.append_history(long_content)
        result = store.build_dream_prompt()
        assert result is not None
        prompt, _ = result
        # The full 2000 chars should not appear — truncated to 500
        assert long_content not in prompt
        assert "x" * 500 in prompt


class TestEphemeralDirect:
    """Tests for the ephemeral flag that skips history.jsonl writes for Dream."""

    @pytest.fixture
    def _make_loop(self, tmp_path):
        """Factory fixture that builds a minimal AgentLoop with mocked deps."""
        from unittest.mock import AsyncMock, MagicMock, patch

        from nanobot.agent.loop import AgentLoop
        from nanobot.agent.memory import MemoryStore
        from nanobot.bus.queue import MessageBus

        store = MemoryStore(tmp_path)
        store.write_soul("# Soul")
        store.write_memory("# Memory")

        bus = MessageBus()
        provider = MagicMock()
        provider.get_default_model.return_value = "test-model"
        provider.supports_tools = True
        provider.generation = MagicMock(max_tokens=4096)
        provider.chat_with_retry = AsyncMock(
            return_value=MagicMock(
                content="done", finish_reason="stop", tool_calls=[], usage={},
            )
        )

        with (
            patch("nanobot.agent.loop.SessionManager"),
            patch("nanobot.agent.loop.SubagentManager") as mock_sub,
            patch("nanobot.agent.loop.Consolidator") as mock_consolidator_cls,
        ):
            mock_sub.return_value.cancel_by_session = AsyncMock(return_value=0)
            mock_consolidator_cls.return_value.maybe_consolidate_by_tokens = AsyncMock()
            loop = AgentLoop(
                bus=bus,
                provider=provider,
                workspace=tmp_path,
                context_window_tokens=8000,
            )

        return loop, store

    async def test_ephemeral_skips_raw_archive(self, tmp_path, _make_loop):
        """When ephemeral=True, raw_archive must not be called."""
        from unittest.mock import patch

        loop, store = _make_loop

        with patch.object(loop.context.memory, "raw_archive") as mock_archive:
            await loop.process_direct(
                "test", session_key="dream:test", ephemeral=True,
            )
            mock_archive.assert_not_called()

    async def test_non_ephemeral_runs_normally(self, tmp_path, _make_loop):
        """Without ephemeral, the normal path is untouched — no crash."""
        loop, store = _make_loop
        await loop.process_direct("test", session_key="cli:normal")

    async def test_ephemeral_sets_ctx_flag(self, tmp_path, _make_loop):
        """Verify that ephemeral=True is forwarded to TurnContext."""
        from unittest.mock import patch

        loop, store = _make_loop

        captured = {}

        original_save = loop._state_save

        async def patched_save(ctx):
            captured["ephemeral"] = ctx.ephemeral
            return await original_save(ctx)

        with patch.object(loop, "_state_save", side_effect=patched_save):
            await loop.process_direct(
                "test", session_key="dream:check", ephemeral=True,
            )

        assert captured.get("ephemeral") is True

    async def test_default_ephemeral_is_false(self, tmp_path, _make_loop):
        """By default ephemeral is False in TurnContext."""
        from unittest.mock import patch

        loop, store = _make_loop

        captured = {}

        original_save = loop._state_save

        async def patched_save(ctx):
            captured["ephemeral"] = ctx.ephemeral
            return await original_save(ctx)

        with patch.object(loop, "_state_save", side_effect=patched_save):
            await loop.process_direct("test", session_key="cli:normal")

        assert captured.get("ephemeral") is False

    async def test_ephemeral_skips_consolidator(self, tmp_path, _make_loop):
        """When ephemeral=True, consolidator.maybe_consolidate_by_tokens is not called."""
        from unittest.mock import patch

        loop, store = _make_loop

        with patch.object(
            loop.consolidator, "maybe_consolidate_by_tokens",
        ) as mock_consolidate:
            await loop.process_direct(
                "test", session_key="dream:consolidate-test", ephemeral=True,
            )
            mock_consolidate.assert_not_called()


class TestEphemeralHooks:
    """When ephemeral=True, extra hooks must not fire."""

    @pytest.fixture
    def _make_loop_with_spy(self, tmp_path):
        """Build an AgentLoop with a spy hook to verify hook firing behavior."""
        from unittest.mock import AsyncMock, MagicMock, patch

        from nanobot.agent.hook import AgentHook
        from nanobot.agent.loop import AgentLoop
        from nanobot.bus.queue import MessageBus

        bus = MessageBus()
        provider = MagicMock()
        provider.get_default_model.return_value = "test-model"
        provider.supports_tools = True
        provider.generation = MagicMock(max_tokens=4096)
        provider.chat_with_retry = AsyncMock(
            return_value=MagicMock(
                content="done", finish_reason="stop", tool_calls=[], usage={},
            )
        )

        spy = MagicMock(spec=AgentHook)
        spy.wants_streaming.return_value = False
        spy.before_iteration = AsyncMock()
        spy.after_iteration = AsyncMock()

        with (
            patch("nanobot.agent.loop.SessionManager"),
            patch("nanobot.agent.loop.SubagentManager") as mock_sub,
            patch("nanobot.agent.loop.Consolidator") as mock_consolidator_cls,
        ):
            mock_sub.return_value.cancel_by_session = AsyncMock(return_value=0)
            mock_consolidator_cls.return_value.maybe_consolidate_by_tokens = AsyncMock()
            loop = AgentLoop(
                bus=bus,
                provider=provider,
                workspace=tmp_path,
                context_window_tokens=8000,
                hooks=[spy],
            )

        return loop, spy

    async def test_extra_hooks_skipped_when_ephemeral(self, tmp_path, _make_loop_with_spy):
        """When ephemeral=True, extra hooks must not fire."""
        loop, spy = _make_loop_with_spy

        await loop.process_direct(
            "test", session_key="dream:hook-test", ephemeral=True,
        )
        spy.before_iteration.assert_not_called()
        spy.after_iteration.assert_not_called()

    async def test_extra_hooks_fire_for_normal_sessions(self, tmp_path, _make_loop_with_spy):
        """Without ephemeral, extra hooks should fire normally."""
        loop, spy = _make_loop_with_spy

        await loop.process_direct("test", session_key="cli:normal")
        spy.before_iteration.assert_called()


class TestDreamCommitMessage:
    async def test_commit_includes_response_summary(self, tmp_path):
        """Git auto-commit after Dream should include the LLM response in the body."""
        import subprocess
        from unittest.mock import AsyncMock, MagicMock

        from nanobot.agent.memory import MemoryStore

        store = MemoryStore(tmp_path)
        store.write_soul("# Soul")
        store.write_memory("# Memory")
        store.append_history("user discussed project goals")

        provider = MagicMock()
        provider.get_default_model.return_value = "test-model"
        provider.supports_tools = True
        provider.generation = MagicMock(max_tokens=4096)
        provider.chat_with_retry = AsyncMock(return_value=MagicMock(
            content="Identified 2 new facts about project goals",
            finish_reason="stop",
            tool_calls=[],
            usage={},
        ))

        store.git.init()
        store.git.auto_commit("initial state")

        # Simulate what the cron handler does: produce a resp with content,
        # build the commit message via the actual function, then commit.
        resp_content = "Identified 2 new facts about project goals"
        resp = MagicMock(content=resp_content)
        msg = MemoryStore.build_dream_commit_message(
            "dream: periodic memory consolidation", resp,
        )

        # Write a change so auto_commit has something to commit
        store.write_memory("# Memory\n- Updated by Dream")
        sha = store.git.auto_commit(msg)
        assert sha is not None

        log = subprocess.check_output(
            ["git", "log", "-1", "--format=%B"],
            cwd=str(tmp_path), text=True,
        ).strip()
        assert "dream: periodic memory consolidation" in log
        assert "Identified 2 new facts" in log
