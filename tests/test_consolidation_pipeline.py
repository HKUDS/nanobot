"""Tests for nanobot.memory.consolidation_pipeline.ConsolidationPipeline."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot.memory.consolidation_pipeline import ConsolidationPipeline


def _make_pipeline(tmp_path: Path | None = None, **overrides: object) -> ConsolidationPipeline:
    """Build a ``ConsolidationPipeline`` with all dependencies mocked."""
    defaults: dict[str, object] = {
        "extractor": MagicMock(),
        "ingester": MagicMock(),
        "profile_mgr": MagicMock(),
        "conflict_mgr": MagicMock(),
        "snapshot": MagicMock(),
        "db": MagicMock(),
        "rollout": {"consolidation_single_tool": True},
    }
    defaults.update(overrides)
    return ConsolidationPipeline(**defaults)  # type: ignore[arg-type]


def _make_session(
    messages: list[dict[str, object]] | None = None,
    last_consolidated: int = 0,
) -> MagicMock:
    session = MagicMock()
    session.messages = messages or []
    session.last_consolidated = last_consolidated
    session.key = "test-session"
    return session


# ---------------------------------------------------------------------------
# _select_messages_for_consolidation
# ---------------------------------------------------------------------------


class TestSelectMessages:
    def test_archive_all(self) -> None:
        pipeline = _make_pipeline()
        msgs = [{"role": "user", "content": f"msg-{i}"} for i in range(10)]
        session = _make_session(messages=msgs)

        result = pipeline._select_messages_for_consolidation(
            session, archive_all=True, memory_window=50
        )
        assert result is not None
        old_messages, keep_count, source_start = result
        assert old_messages is msgs
        assert keep_count == 0
        assert source_start == 0

    def test_normal_selection(self) -> None:
        pipeline = _make_pipeline()
        msgs = [{"role": "user", "content": f"msg-{i}"} for i in range(20)]
        session = _make_session(messages=msgs, last_consolidated=0)

        result = pipeline._select_messages_for_consolidation(
            session, archive_all=False, memory_window=10
        )
        assert result is not None
        old_messages, keep_count, source_start = result
        # keep_count = memory_window // 2 = 5
        assert keep_count == 5
        assert source_start == 0
        # old_messages = messages[0:-5] = first 15 messages
        assert len(old_messages) == 15

    def test_too_few_messages(self) -> None:
        pipeline = _make_pipeline()
        msgs = [{"role": "user", "content": f"msg-{i}"} for i in range(3)]
        session = _make_session(messages=msgs)

        result = pipeline._select_messages_for_consolidation(
            session, archive_all=False, memory_window=10
        )
        # 3 messages <= keep_count (5) -> returns None
        assert result is None

    def test_nothing_new_to_consolidate(self) -> None:
        pipeline = _make_pipeline()
        msgs = [{"role": "user", "content": f"msg-{i}"} for i in range(20)]
        session = _make_session(messages=msgs, last_consolidated=20)

        result = pipeline._select_messages_for_consolidation(
            session, archive_all=False, memory_window=10
        )
        assert result is None


# ---------------------------------------------------------------------------
# _format_conversation_lines
# ---------------------------------------------------------------------------


class TestFormatConversationLines:
    def test_basic_formatting(self) -> None:
        messages = [
            {"role": "user", "content": "Hello", "timestamp": "2026-01-01T12:00:00"},
            {
                "role": "assistant",
                "content": "Hi!",
                "timestamp": "2026-01-01T12:01:00",
                "tools_used": ["web_search"],
            },
        ]
        lines = ConsolidationPipeline._format_conversation_lines(messages)
        assert len(lines) == 2
        assert "[2026-01-01T12:00" in lines[0]
        assert "USER" in lines[0]
        assert "Hello" in lines[0]
        assert "[tools: web_search]" in lines[1]
        assert "ASSISTANT" in lines[1]

    def test_skips_empty_content(self) -> None:
        messages = [
            {"role": "user", "content": ""},
            {"role": "user", "content": None},
            {"role": "user", "content": "actual"},
        ]
        lines = ConsolidationPipeline._format_conversation_lines(messages)
        assert len(lines) == 1
        assert "actual" in lines[0]


# ---------------------------------------------------------------------------
# _build_consolidation_prompt
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# _finalize_consolidation
# ---------------------------------------------------------------------------


class TestFinalizeConsolidation:
    def test_updates_session_pointer(self) -> None:
        pipeline = _make_pipeline()
        msgs = [{"role": "user", "content": f"m{i}"} for i in range(20)]
        session = _make_session(messages=msgs)

        pipeline._finalize_consolidation(session, archive_all=False, keep_count=5)
        assert session.last_consolidated == 15

    def test_archive_all_resets_pointer(self) -> None:
        pipeline = _make_pipeline()
        msgs = [{"role": "user", "content": f"m{i}"} for i in range(10)]
        session = _make_session(messages=msgs)

        pipeline._finalize_consolidation(session, archive_all=True, keep_count=0)
        assert session.last_consolidated == 0


# ---------------------------------------------------------------------------
# consolidate -- integration-level tests
# ---------------------------------------------------------------------------


class TestConsolidate:
    @pytest.mark.asyncio
    async def test_no_op_returns_true(self) -> None:
        """When there are too few messages, consolidate returns True (no-op)."""
        pipeline = _make_pipeline()
        session = _make_session(messages=[{"role": "user", "content": "hi"}])
        provider = MagicMock()

        result = await pipeline.consolidate(session, provider, "gpt-4")
        assert result is True

    @pytest.mark.asyncio
    async def test_no_tool_call_returns_false(self, tmp_path: Path) -> None:
        """When LLM does not call save_memory, consolidate returns False."""
        pipeline = _make_pipeline(tmp_path)
        msgs = [{"role": "user", "content": f"msg-{i}"} for i in range(30)]
        session = _make_session(messages=msgs)

        response = MagicMock()
        response.has_tool_calls = False
        provider = MagicMock()
        provider.chat = AsyncMock(return_value=response)

        with patch("nanobot.memory.consolidation_pipeline.prompts") as mock_prompts:
            mock_prompts.get.return_value = "system prompt"
            result = await pipeline.consolidate(session, provider, "gpt-4")

        assert result is False

    @pytest.mark.asyncio
    async def test_success_happy_path(self, tmp_path: Path) -> None:
        """Full happy-path: LLM calls consolidate_memory, extraction runs, returns True."""
        pipeline = _make_pipeline(tmp_path)
        msgs = [
            {"role": "user", "content": f"msg-{i}", "timestamp": "2026-01-01T00:00:00"}
            for i in range(30)
        ]
        session = _make_session(messages=msgs)

        tool_call = MagicMock()
        tool_call.arguments = '{"history_entry": "summary", "events": [], "profile_updates": {}}'
        response = MagicMock()
        response.has_tool_calls = True
        response.tool_calls = [tool_call]

        provider = MagicMock()
        provider.chat = AsyncMock(return_value=response)

        pipeline._extractor.parse_tool_args.return_value = {
            "history_entry": "summary",
            "events": [
                {"type": "fact", "summary": "test event", "timestamp": "2026-01-01T00:00:00"},
            ],
            "profile_updates": {},
        }
        pipeline._extractor.default_profile_updates.return_value = {}
        pipeline._extractor.coerce_event.return_value = {
            "id": "e1",
            "type": "fact",
            "summary": "test event",
            "timestamp": "2026-01-01T00:00:00",
        }
        pipeline._extractor.extract_structured_memory = AsyncMock(return_value=([], {}))
        pipeline._ingester.append_events.return_value = 0
        pipeline._ingester._ingest_graph_triples = AsyncMock()
        pipeline._profile_mgr.read_profile.return_value = {}
        pipeline._profile_mgr._apply_profile_updates.return_value = (0, 0, 0)

        with patch("nanobot.memory.consolidation_pipeline.prompts") as mock_prompts:
            mock_prompts.get.return_value = "system prompt"
            result = await pipeline.consolidate(session, provider, "gpt-4")

        assert result is True
        # History entry should have been written to the database
        pipeline._db.append_history.assert_called_once()
        pipeline._snapshot.rebuild_memory_snapshot.assert_called_once_with(write=True)

    @pytest.mark.asyncio
    async def test_exception_returns_false(self, tmp_path: Path) -> None:
        """Crash-barrier: exceptions inside try block are caught, returns False."""
        pipeline = _make_pipeline(tmp_path)
        msgs = [{"role": "user", "content": f"msg-{i}"} for i in range(30)]
        session = _make_session(messages=msgs)

        provider = MagicMock()
        provider.chat = AsyncMock(side_effect=RuntimeError("provider crash"))

        with patch("nanobot.memory.consolidation_pipeline.prompts") as mock_prompts:
            mock_prompts.get.return_value = "system prompt"
            result = await pipeline.consolidate(session, provider, "gpt-4")

        assert result is False
