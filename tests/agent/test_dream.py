"""Tests for Dream memory consolidation — build_dream_prompt and cursor management."""

import pytest

from blackcat.agent.memory import MemoryStore
from blackcat.providers.base import LLMResponse
from blackcat.security.workspace_access import (
    bind_workspace_scope,
    default_workspace_scope,
    reset_workspace_scope,
)
from blackcat.utils.prompt_templates import render_template


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

    def test_batches_oldest_unprocessed_entries_first(self, store):
        for i in range(25):
            store.append_history(f"entry-{i + 1:02d}")

        result = store.build_dream_prompt(max_entries=20)
        assert result is not None
        prompt, cursor = result

        assert cursor == 20
        assert "entry-01" in prompt
        assert "entry-20" in prompt
        assert "entry-21" not in prompt

        store.set_last_dream_cursor(cursor)
        next_result = store.build_dream_prompt(max_entries=20)
        assert next_result is not None
        next_prompt, next_cursor = next_result
        assert next_cursor == 25
        assert "entry-21" in next_prompt
        assert "entry-25" in next_prompt

    def test_skips_malformed_history_entries(self, store):
        """Dream prompt building should tolerate externally corrupted JSONL rows."""
        store.history_file.write_text(
            '{"cursor": 1, "timestamp": "2026-04-01 10:00"}\n'
            '{"cursor": 2, "timestamp": "2026-04-01 10:01", "content": "usable memory"}\n',
            encoding="utf-8",
        )

        result = store.build_dream_prompt()

        assert result is not None
        prompt, cursor = result
        assert cursor == 2
        assert "usable memory" in prompt

    def test_dream_prompt_consumes_consolidator_attribute_tags(self):
        prompt = render_template(
            "agent/dream.md",
            strip=True,
            skill_creator_path="skills/skill-creator/SKILL.md",
        )

        assert "History attribute tags" in prompt
        assert "[skip]: audit-only" in prompt
        assert "[correction]: replace the older conflicting fact" in prompt
        assert "Always strip these bracketed tags from saved memory content" in prompt


class TestDreamTools:
    def test_dream_tools_are_restricted_to_file_edits(self, store):
        tools = store.build_dream_tools()

        assert set(tools.tool_names) == {
            "apply_patch",
            "edit_file",
            "read_file",
            "write_file",
        }

    @pytest.mark.asyncio
    async def test_dream_can_edit_canonical_memory_files(self, store):
        tools = store.build_dream_tools()

        memory_result = await tools.execute(
            "apply_patch",
            {
                "edits": [
                    {
                        "path": "memory/MEMORY.md",
                        "action": "replace",
                        "old_text": "Project X active",
                        "new_text": "Project Y active",
                    }
                ]
            },
        )
        soul_result = await tools.execute(
            "edit_file",
            {
                "path": "SOUL.md",
                "old_text": "Helpful",
                "new_text": "Precise",
            },
        )

        assert "Patch applied" in memory_result
        assert "Successfully edited" in soul_result
        assert "Project Y active" in store.memory_file.read_text(encoding="utf-8")
        assert "Precise" in store.soul_file.read_text(encoding="utf-8")

    @pytest.mark.asyncio
    async def test_dream_can_write_workspace_skills(self, store):
        tools = store.build_dream_tools()
        target = store.workspace / "skills" / "demo" / "SKILL.md"

        result = await tools.execute(
            "write_file",
            {
                "path": "skills/demo/SKILL.md",
                "content": "---\nname: demo\ndescription: Demo skill.\n---\n\nUse when needed.\n",
            },
        )

        assert "Successfully wrote" in result
        assert target.read_text(encoding="utf-8").startswith("---\nname: demo")

    @pytest.mark.asyncio
    async def test_dream_tools_keep_internal_write_scope_under_full_access(self, store):
        tools = store.build_dream_tools()
        scope = default_workspace_scope(store.workspace, restrict_to_workspace=False)
        outside = store.workspace.parent / f"{store.workspace.name}-outside"
        outside.mkdir()
        outside_target = outside / "escape.txt"
        skill_target = store.workspace / "skills" / "scoped" / "SKILL.md"

        token = bind_workspace_scope(scope)
        try:
            outside_result = await tools.execute(
                "write_file",
                {"path": str(outside_target), "content": "owned"},
            )
            skill_result = await tools.execute(
                "apply_patch",
                {
                    "edits": [
                        {
                            "path": "skills/scoped/SKILL.md",
                            "action": "add",
                            "new_text": "---\nname: scoped\n---\n",
                        }
                    ]
                },
            )
        finally:
            reset_workspace_scope(token)

        assert "outside allowed directory" in outside_result
        assert not outside_target.exists()
        assert "Patch applied" in skill_result
        assert skill_target.read_text(encoding="utf-8").startswith("---\nname: scoped")

    @pytest.mark.asyncio
    async def test_dream_cannot_modify_memory_internal_files(self, store):
        tools = store.build_dream_tools()
        store.history_file.write_text("before\n", encoding="utf-8")
        store._dream_cursor_file.write_text("1", encoding="utf-8")

        history_result = await tools.execute(
            "apply_patch",
            {
                "edits": [
                    {
                        "path": "memory/history.jsonl",
                        "action": "replace",
                        "old_text": "before",
                        "new_text": "after",
                    }
                ]
            },
        )
        cursor_result = await tools.execute(
            "edit_file",
            {
                "path": "memory/.dream_cursor",
                "old_text": "1",
                "new_text": "2",
            },
        )

        assert "outside allowed directory" in history_result
        assert "outside allowed directory" in cursor_result
        assert store.history_file.read_text(encoding="utf-8") == "before\n"
        assert store._dream_cursor_file.read_text(encoding="utf-8") == "1"

    @pytest.mark.asyncio
    async def test_dream_cannot_create_children_under_canonical_files(self, store):
        tools = store.build_dream_tools()

        memory_child = store.memory_file / "evil.txt"
        user_child = store.user_file / "evil.txt"
        memory_result = await tools.execute(
            "apply_patch",
            {
                "edits": [
                    {
                        "path": "memory/MEMORY.md/evil.txt",
                        "action": "add",
                        "new_text": "owned",
                    }
                ]
            },
        )
        user_result = await tools.execute(
            "edit_file",
            {
                "path": "USER.md/evil.txt",
                "old_text": "",
                "new_text": "owned",
            },
        )

        assert "outside allowed directory" in memory_result
        assert "outside allowed directory" in user_result
        assert not memory_child.exists()
        assert not user_child.exists()


class TestEphemeralDirect:
    """Tests for the ephemeral flag that skips history.jsonl writes for Dream."""

    @pytest.fixture
    def _make_loop(self, tmp_path):
        """Factory fixture that builds a minimal AgentLoop with mocked deps."""
        from unittest.mock import AsyncMock, MagicMock, patch

        from blackcat.agent.loop import AgentLoop
        from blackcat.agent.memory import MemoryStore
        from blackcat.bus.queue import MessageBus

        store = MemoryStore(tmp_path)
        store.write_soul("# Soul")
        store.write_memory("# Memory")

        bus = MessageBus()
        provider = MagicMock()
        provider.get_default_model.return_value = "test-model"
        provider.supports_tools = True
        provider.generation = MagicMock(max_tokens=4096)
        provider.chat_with_retry = AsyncMock(
            return_value=LLMResponse(content="done", tool_calls=[], finish_reason="stop", usage={})
        )

        with (
            patch("blackcat.agent.loop.SessionManager"),
            patch("blackcat.agent.loop.SubagentManager") as mock_sub,
            patch("blackcat.agent.loop.Consolidator") as mock_consolidator_cls,
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
        """Without ephemeral, the normal path returns the model response."""
        loop, store = _make_loop
        response = await loop.process_direct("test", session_key="cli:normal")

        assert response is not None
        assert response.content == "done"
        loop.provider.chat_with_retry.assert_awaited()

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

    async def test_ephemeral_response_reports_stop_reason(self, tmp_path, _make_loop):
        loop, store = _make_loop
        loop.provider.chat_with_retry.return_value = LLMResponse(
            content="provider error",
            finish_reason="error",
        )

        resp = await loop.process_direct(
            "test", session_key="dream:error", ephemeral=True,
        )

        assert resp is not None
        assert resp.metadata["_stop_reason"] == "error"
        assert MemoryStore.dream_run_completed(resp) is False

    async def test_dream_turn_can_skip_unbatched_recent_history(self, tmp_path):
        """Dream must only see the batch selected by build_dream_prompt."""
        from unittest.mock import MagicMock

        from blackcat.agent.loop import AgentLoop
        from blackcat.bus.queue import MessageBus

        store = MemoryStore(tmp_path)
        for i in range(60):
            store.append_history(f"entry-{i + 1:02d}")

        result = store.build_dream_prompt(max_entries=20)
        assert result is not None
        prompt, cursor = result
        assert cursor == 20

        captured: dict[str, list[dict]] = {}
        provider = MagicMock()
        provider.get_default_model.return_value = "test-model"
        provider.supports_tools = True
        provider.generation = MagicMock(max_tokens=4096)

        async def chat_with_retry(**kwargs):
            captured["messages"] = kwargs["messages"]
            return LLMResponse(content="done", finish_reason="stop")

        provider.chat_with_retry = chat_with_retry
        loop = AgentLoop(
            bus=MessageBus(),
            provider=provider,
            workspace=tmp_path,
            context_window_tokens=8000,
        )

        await loop.process_direct(
            prompt,
            session_key="dream:test",
            ephemeral=True,
            tools=store.build_dream_tools(),
        )

        messages = captured["messages"]
        system_prompt = messages[0]["content"]
        request_text = "\n".join(str(message.get("content", "")) for message in messages)
        assert "# Recent History" not in system_prompt
        assert "entry-01" in request_text
        assert "entry-20" in request_text
        assert "entry-21" not in request_text
        assert "entry-60" not in request_text


class TestEphemeralHooks:
    """When ephemeral=True, extra hooks must not fire."""

    @pytest.fixture
    def _make_loop_with_spy(self, tmp_path):
        """Build an AgentLoop with a spy hook to verify hook firing behavior."""
        from unittest.mock import AsyncMock, MagicMock, patch

        from blackcat.agent.hook import AgentHook
        from blackcat.agent.loop import AgentLoop
        from blackcat.bus.queue import MessageBus

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
            patch("blackcat.agent.loop.SessionManager"),
            patch("blackcat.agent.loop.SubagentManager") as mock_sub,
            patch("blackcat.agent.loop.Consolidator") as mock_consolidator_cls,
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

        from blackcat.agent.memory import MemoryStore

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
