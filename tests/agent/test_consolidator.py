"""Tests for the lightweight Consolidator — append-only to HISTORY.md."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.memory import (
    _ARCHIVE_SUMMARY_MAX_CHARS,
    Consolidator,
    MemoryStore,
)
from nanobot.session.manager import Session


@pytest.fixture
def store(tmp_path):
    return MemoryStore(tmp_path)


@pytest.fixture
def mock_provider():
    p = MagicMock()
    p.chat_with_retry = AsyncMock()
    return p


@pytest.fixture
def consolidator(store, mock_provider):
    sessions = MagicMock()
    sessions.save = MagicMock()
    return Consolidator(
        store=store,
        provider=mock_provider,
        model="test-model",
        sessions=sessions,
        context_window_tokens=1000,
        build_messages=MagicMock(return_value=[]),
        get_tool_definitions=MagicMock(return_value=[]),
        max_completion_tokens=100,
    )


class TestConsolidatorSummarize:
    async def test_summarize_appends_to_history(self, consolidator, mock_provider, store):
        """Consolidator should call LLM to summarize, then append to HISTORY.md."""
        mock_provider.chat_with_retry.return_value = MagicMock(
            content="User fixed a bug in the auth module."
        )
        messages = [
            {"role": "user", "content": "fix the auth bug"},
            {"role": "assistant", "content": "Done, fixed the race condition."},
        ]
        result = await consolidator.archive(messages)
        assert result == "User fixed a bug in the auth module."
        entries = store.read_unprocessed_history(since_cursor=0)
        assert len(entries) == 1

    async def test_summarize_raw_dumps_on_llm_failure(self, consolidator, mock_provider, store):
        """On LLM failure, raw-dump messages to HISTORY.md."""
        mock_provider.chat_with_retry.side_effect = Exception("API error")
        messages = [{"role": "user", "content": "hello"}]
        result = await consolidator.archive(messages)
        assert result is None  # no summary on raw dump fallback
        entries = store.read_unprocessed_history(since_cursor=0)
        assert len(entries) == 1
        assert "[RAW]" in entries[0]["content"]

    async def test_summarize_skips_empty_messages(self, consolidator):
        result = await consolidator.archive([])
        assert result is None


class TestConsolidatorArchiveErrorHandling:
    """archive() must fall back to raw_archive when the LLM returns an error
    response (finish_reason == 'error'), e.g. overloaded / quota exceeded.
    See https://github.com/HKUDS/nanobot/issues/3244
    """

    async def test_archive_falls_back_on_error_finish_reason(self, consolidator, mock_provider, store):
        """LLM returning finish_reason='error' should trigger raw_archive, not write error text."""
        mock_provider.chat_with_retry.return_value = MagicMock(
            content="Error: {'type': 'error', 'error': {'type': 'overloaded_error', 'message': 'overloaded_error (529)'}}",
            finish_reason="error",
        )
        messages = [
            {"role": "user", "content": "fix the auth bug"},
            {"role": "assistant", "content": "Done, fixed the race condition."},
        ]
        result = await consolidator.archive(messages)
        assert result is None
        entries = store.read_unprocessed_history(since_cursor=0)
        assert len(entries) == 1
        assert "[RAW]" in entries[0]["content"]
        assert "Error:" not in entries[0]["content"]

    async def test_archive_preserves_summary_on_success(self, consolidator, mock_provider, store):
        """Normal LLM response should still produce a proper summary entry."""
        mock_provider.chat_with_retry.return_value = MagicMock(
            content="User fixed a bug in the auth module.",
            finish_reason="stop",
        )
        messages = [
            {"role": "user", "content": "fix the auth bug"},
            {"role": "assistant", "content": "Done."},
        ]
        result = await consolidator.archive(messages)
        assert result == "User fixed a bug in the auth module."
        entries = store.read_unprocessed_history(since_cursor=0)
        assert len(entries) == 1
        assert "[RAW]" not in entries[0]["content"]


class TestConsolidatorTokenBudget:
    async def test_prompt_below_threshold_does_not_consolidate(self, consolidator):
        """No consolidation when tokens are within budget."""
        session = MagicMock()
        session.last_consolidated = 0
        session.messages = [{"role": "user", "content": "hi"}]
        session.key = "test:key"
        consolidator.estimate_session_prompt_tokens = MagicMock(return_value=(100, "tiktoken"))
        consolidator.archive = AsyncMock(return_value=True)
        await consolidator.maybe_consolidate_by_tokens(session)
        consolidator.archive.assert_not_called()

    async def test_estimate_uses_full_unconsolidated_tail(self, consolidator):
        """Consolidation pressure must see messages hidden by the replay window."""
        session = Session(key="test:full-tail")
        for i in range(160):
            session.add_message("user", f"msg-{i}")

        captured: dict[str, list[dict]] = {}

        def build_messages(**kwargs):
            captured["history"] = kwargs["history"]
            return kwargs["history"]

        consolidator._build_messages = build_messages

        consolidator.estimate_session_prompt_tokens(session)

        assert len(captured["history"]) == 160
        assert captured["history"][0]["content"].endswith("msg-0")

    async def test_replay_window_overflow_is_archived_even_under_token_budget(
        self,
        consolidator,
    ):
        """Old messages that cannot be replayed should be materialized first."""
        consolidator._SAFETY_BUFFER = 0
        session = Session(key="test:replay-overflow")
        for i in range(10):
            session.add_message("user", f"u{i}")
            session.add_message("assistant", f"a{i}")

        consolidator.estimate_session_prompt_tokens = MagicMock(return_value=(100, "tiktoken"))
        consolidator.archive = AsyncMock(return_value="old conversation summary")

        await consolidator.maybe_consolidate_by_tokens(
            session,
            replay_max_messages=6,
        )

        archived_chunk = consolidator.archive.await_args.args[0]
        assert archived_chunk[0]["content"] == "u0"
        assert archived_chunk[-1]["content"] == "a6"
        assert session.last_consolidated == 14
        assert session.metadata["_last_summary"]["text"] == "old conversation summary"
        consolidator.sessions.save.assert_called()

    async def test_replay_window_overflow_matches_history_tool_boundary(
        self,
        consolidator,
    ):
        """Archive the exact prefix hidden by get_history's legal-start trimming."""
        session = Session(key="test:replay-tool-boundary")
        session.add_message("user", "run the tool")
        session.add_message(
            "assistant",
            "",
            tool_calls=[
                {"id": "call-1", "type": "function", "function": {"name": "x", "arguments": "{}"}}
            ],
        )
        session.add_message("tool", "tool result", tool_call_id="call-1", name="x")
        session.add_message("assistant", "final answer")

        consolidator.estimate_session_prompt_tokens = MagicMock(return_value=(100, "tiktoken"))
        consolidator.archive = AsyncMock(return_value="tool turn summary")

        await consolidator.maybe_consolidate_by_tokens(
            session,
            replay_max_messages=2,
        )

        archived_chunk = consolidator.archive.await_args.args[0]
        assert [m["role"] for m in archived_chunk] == ["user", "assistant", "tool"]
        assert session.last_consolidated == 3
        assert session.get_history(max_messages=2) == [{"role": "assistant", "content": "final answer"}]

    async def test_large_chunk_archived_without_cap(self, consolidator):
        """Without chunk cap, the full range from pick_consolidation_boundary is archived."""
        consolidator._SAFETY_BUFFER = 0
        session = MagicMock()
        session.last_consolidated = 0
        session.key = "test:key"
        session.messages = [
            {
                "role": "user" if i in {0, 50, 61} else "assistant",
                "content": f"m{i}",
            }
            for i in range(70)
        ]
        consolidator.estimate_session_prompt_tokens = MagicMock(
            side_effect=[(1200, "tiktoken"), (400, "tiktoken")]
        )
        # Use real pick_consolidation_boundary — it will find boundary at idx=50
        # (user message at 50, token budget met)
        consolidator.archive = AsyncMock(return_value=True)

        await consolidator.maybe_consolidate_by_tokens(session)

        archived_chunk = consolidator.archive.await_args.args[0]
        # pick_consolidation_boundary returns (50, tokens) — user turn at idx 50
        assert archived_chunk[0]["content"] == "m0"
        assert session.last_consolidated > 0

    async def test_raw_archive_fallback_advances_last_consolidated(self, consolidator):
        """When archive() falls back to raw-archive (LLM failed), the cursor
        must still advance. Otherwise the same chunk gets raw-archived again
        on every subsequent maybe_consolidate_by_tokens() call, spamming
        duplicate [RAW] entries into history.jsonl."""
        consolidator._SAFETY_BUFFER = 0
        session = MagicMock()
        session.last_consolidated = 0
        session.key = "test:key"
        session.messages = [
            {"role": "user" if i in {0, 50} else "assistant", "content": f"m{i}"}
            for i in range(70)
        ]
        session.metadata = {}
        consolidator.estimate_session_prompt_tokens = MagicMock(
            side_effect=[(1200, "tiktoken"), (400, "tiktoken")]
        )
        # LLM consolidation fails — archive() returns None (raw_archive fired).
        consolidator.archive = AsyncMock(return_value=None)

        await consolidator.maybe_consolidate_by_tokens(session)

        consolidator.archive.assert_awaited_once()
        # The chunk is considered "materialized" (as a raw-archive breadcrumb),
        # so last_consolidated must have moved past it.
        assert session.last_consolidated == 50

    async def test_raw_archive_fallback_breaks_round_loop(self, consolidator):
        """A degraded LLM should not trigger more archive() calls within the
        same maybe_consolidate_by_tokens invocation — bail after one fallback."""
        consolidator._SAFETY_BUFFER = 0
        session = MagicMock()
        session.last_consolidated = 0
        session.key = "test:key"
        session.messages = [
            {"role": "user" if i in {0, 20, 40, 60} else "assistant", "content": f"m{i}"}
            for i in range(70)
        ]
        session.metadata = {}
        # Keep estimates high so the loop would otherwise run multiple rounds.
        consolidator.estimate_session_prompt_tokens = MagicMock(
            return_value=(1200, "tiktoken")
        )
        consolidator.archive = AsyncMock(return_value=None)

        await consolidator.maybe_consolidate_by_tokens(session)

        # Exactly one fallback per call — not _MAX_CONSOLIDATION_ROUNDS.
        assert consolidator.archive.await_count == 1

    async def test_boundary_respected_when_no_intermediate_user_turn(self, consolidator):
        """When boundary points past a long tool chain, the full chunk is archived."""
        consolidator._SAFETY_BUFFER = 0
        session = MagicMock()
        session.last_consolidated = 0
        session.key = "test:key"
        session.messages = [
            {
                "role": "user" if i in {0, 61} else "assistant",
                "content": f"m{i}",
            }
            for i in range(70)
        ]
        consolidator.estimate_session_prompt_tokens = MagicMock(
            side_effect=[(1200, "tiktoken"), (400, "tiktoken")]
        )
        consolidator.archive = AsyncMock(return_value=True)

        await consolidator.maybe_consolidate_by_tokens(session)

        consolidator.archive.assert_awaited_once()
        # pick_consolidation_boundary finds the only boundary at idx=61
        assert session.last_consolidated == 61


class TestRawArchiveTruncation:
    """raw_archive() must cap entry size to avoid bloating history.jsonl."""

    def test_raw_archive_truncates_large_content(self, store):
        """Large messages should be truncated to _RAW_ARCHIVE_MAX_CHARS."""
        big = "x" * 50_000
        messages = [{"role": "user", "content": big}]
        store.raw_archive(messages)
        entries = store.read_unprocessed_history(since_cursor=0)
        assert len(entries) == 1
        assert len(entries[0]["content"]) < 50_000
        assert "[RAW]" in entries[0]["content"]

    def test_raw_archive_preserves_small_content(self, store):
        """Small messages should not be truncated."""
        messages = [{"role": "user", "content": "hello"}]
        store.raw_archive(messages)
        entries = store.read_unprocessed_history(since_cursor=0)
        assert len(entries) == 1
        assert "hello" in entries[0]["content"]

    def test_raw_archive_custom_max_chars(self, store):
        """max_chars parameter should override default limit."""
        messages = [{"role": "user", "content": "a" * 200}]
        store.raw_archive(messages, max_chars=100)
        entries = store.read_unprocessed_history(since_cursor=0)
        assert len(entries[0]["content"]) < 200


class TestArchiveTruncation:
    """archive() must truncate formatted text before sending to consolidation LLM."""

    async def test_archive_truncates_large_formatted_text(self, consolidator, mock_provider, store):
        """Large formatted text should be truncated to token budget before LLM call."""
        # context_window_tokens=1000, max_completion_tokens=100, _SAFETY_BUFFER=1024
        # budget = 1000 - 100 - 1024 = -124 → fallback via truncate_text(budget*4)
        big_messages = [{"role": "user", "content": "x" * 100_000}]
        mock_provider.chat_with_retry.return_value = MagicMock(
            content="Summary of large input.", finish_reason="stop"
        )
        await consolidator.archive(big_messages)

        call_args = mock_provider.chat_with_retry.call_args
        user_content = call_args.kwargs["messages"][1]["content"]
        # Should be significantly shorter than 100K
        assert len(user_content) < 50_000

    async def test_archive_truncates_with_small_token_budget(self, consolidator, mock_provider, store):
        """Small context window: truncation uses actual tokenizer count."""
        consolidator.context_window_tokens = 500
        big_messages = [{"role": "user", "content": "word " * 50_000}]
        mock_provider.chat_with_retry.return_value = MagicMock(
            content="Summary.", finish_reason="stop"
        )
        await consolidator.archive(big_messages)

        sent_messages = mock_provider.chat_with_retry.call_args.kwargs["messages"]
        user_content = sent_messages[1]["content"]
        # budget = 500 - 100 - 1024 = negative, fallback char-based
        # Should be truncated
        assert len(user_content) < 250_000

    async def test_oversized_summary_is_capped_before_append(self, consolidator, mock_provider, store):
        """A pathologically large LLM summary must not land full-length in
        history.jsonl — that would re-open the #3412 bloat vector from the
        *success* path instead of the fallback path."""
        mock_provider.chat_with_retry.return_value = MagicMock(
            content="S" * (_ARCHIVE_SUMMARY_MAX_CHARS * 10),
            finish_reason="stop",
        )
        await consolidator.archive([{"role": "user", "content": "hi"}])

        entry = store.read_unprocessed_history(since_cursor=0)[0]
        assert len(entry["content"]) <= _ARCHIVE_SUMMARY_MAX_CHARS + 50

    async def test_archive_truncates_via_tiktoken_with_positive_budget(self, consolidator, mock_provider, store):
        """Positive token budget should use tiktoken for precise truncation."""
        consolidator.context_window_tokens = 10_000
        consolidator._SAFETY_BUFFER = 0
        # budget = 10000 - 100 - 0 = 9900 tokens
        big_messages = [{"role": "user", "content": "word " * 50_000}]
        mock_provider.chat_with_retry.return_value = MagicMock(
            content="Summary.", finish_reason="stop"
        )
        await consolidator.archive(big_messages)

        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        sent_content = mock_provider.chat_with_retry.call_args.kwargs["messages"][1]["content"]
        token_count = len(enc.encode(sent_content))
        assert token_count <= 9_900 + 10  # small margin for truncation suffix
