"""Tests for the lightweight Consolidator — append-only to HISTORY.md."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.memory import (
    _ARCHIVE_SUMMARY_MAX_CHARS,
    Consolidator,
    MemoryStore,
)
from nanobot.providers.base import LLMResponse
from nanobot.session.manager import Session
from nanobot.utils.prompt_templates import render_template


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
    # When maybe_consolidate_by_tokens refreshes the session reference via
    # get_or_create(session.key), it should get back the same object the test
    # passed in.  Store sessions by key so the lookup is transparent.
    _session_cache: dict[str, MagicMock] = {}
    sessions.get_or_create = MagicMock(side_effect=lambda key: _session_cache.get(key, MagicMock()))
    sessions._session_cache = _session_cache
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


def _tool_round(call_id: str) -> list[dict]:
    return [
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {"id": call_id, "type": "function", "function": {"name": "x", "arguments": "{}"}}
            ],
        },
        {"role": "tool", "tool_call_id": call_id, "name": "x", "content": "ok"},
    ]


def _message_text_chars(messages: list[dict]) -> int:
    total = 0
    for message in messages:
        content = message.get("content")
        if isinstance(content, str):
            total += len(content)
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    total += len(part.get("text", ""))
    return total


def _counting_provider():
    provider = MagicMock()
    provider.estimate_prompt_tokens.side_effect = (
        lambda messages, _tools, _model: (_message_text_chars(messages), "chars")
    )
    return provider


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

    async def test_summarize_appends_session_key_to_history(
        self,
        consolidator,
        mock_provider,
        store,
    ):
        mock_provider.chat_with_retry.return_value = MagicMock(
            content="User fixed a bug in the auth module.",
            finish_reason="stop",
        )
        messages = [{"role": "user", "content": "fix the auth bug"}]

        await consolidator.archive(messages, session_key="telegram:chat-1")

        entries = store.read_unprocessed_history(since_cursor=0)
        assert entries[0]["session_key"] == "telegram:chat-1"

    async def test_summarize_raw_dumps_on_llm_failure(self, consolidator, mock_provider, store):
        """On LLM failure, raw-dump messages to HISTORY.md."""
        mock_provider.chat_with_retry.side_effect = Exception("API error")
        messages = [{"role": "user", "content": "hello"}]
        result = await consolidator.archive(messages)
        assert result is None  # no summary on raw dump fallback
        entries = store.read_unprocessed_history(since_cursor=0)
        assert len(entries) == 1
        assert "[RAW]" in entries[0]["content"]

    async def test_raw_dump_fallback_appends_session_key(
        self,
        consolidator,
        mock_provider,
        store,
    ):
        mock_provider.chat_with_retry.side_effect = Exception("API error")
        messages = [{"role": "user", "content": "hello"}]

        await consolidator.archive(messages, session_key="slack:chat-2")

        entries = store.read_unprocessed_history(since_cursor=0)
        assert entries[0]["session_key"] == "slack:chat-2"

    async def test_summarize_skips_empty_messages(self, consolidator):
        result = await consolidator.archive([])
        assert result is None


class TestConsolidatorPromptContract:
    def test_archive_prompt_outputs_attribute_tags_without_missing_context_claims(self):
        prompt = render_template("agent/consolidator_archive.md", strip=True)

        assert "SNIP" in prompt
        for mark in ("[permanent]", "[durable]", "[ephemeral]", "[correction]", "[skip]"):
            assert mark in prompt
        assert "check context below" not in prompt.lower()
        assert "Do not mark something [skip] merely because it might already exist" in prompt


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
        consolidator.sessions._session_cache[session.key] = session
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

        consolidator.sessions._session_cache[session.key] = session
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

    async def test_replay_window_overflow_extends_to_long_recent_user_turn(
        self,
        consolidator,
    ):
        """Replay-window consolidation must not cut into the latest user turn."""
        session = Session(key="test:replay-tool-boundary")
        session.add_message("user", "old")
        session.add_message("assistant", "old answer")
        session.add_message("user", "record this")
        for i in range(4):
            session.messages.extend(_tool_round(f"call-{i}"))
        session.add_message("assistant", "final answer")

        consolidator.sessions._session_cache[session.key] = session
        consolidator.estimate_session_prompt_tokens = MagicMock(return_value=(100, "tiktoken"))
        consolidator.archive = AsyncMock(return_value="tool turn summary")

        await consolidator.maybe_consolidate_by_tokens(
            session,
            replay_max_messages=4,
        )

        archived_chunk = consolidator.archive.await_args.args[0]
        assert [m["content"] for m in archived_chunk] == ["old", "old answer"]
        assert session.last_consolidated == 2

        history = session.get_history(max_messages=4, extend_to_user=True)
        assert len(history) > 4
        assert history[0]["content"] == "record this"
        assert history[-1]["content"] == "final answer"

    async def test_replay_window_overflow_uses_newer_user_inside_window(
        self,
        consolidator,
    ):
        """Do not extend to an older long turn when the hard window has a newer user."""
        session = Session(key="test:replay-newer-user")
        session.add_message("user", "old")
        session.add_message("assistant", "old answer")
        session.add_message("user", "long older turn")
        for i in range(8):
            session.messages.extend(_tool_round(f"older-{i}"))
        session.add_message("assistant", "older final")
        session.add_message("user", "new question")
        session.add_message("assistant", "new answer")

        consolidator.sessions._session_cache[session.key] = session
        consolidator.estimate_session_prompt_tokens = MagicMock(return_value=(100, "tiktoken"))
        consolidator.archive = AsyncMock(return_value="older turn summary")

        await consolidator.maybe_consolidate_by_tokens(
            session,
            replay_max_messages=6,
        )

        archived_chunk = consolidator.archive.await_args.args[0]
        assert archived_chunk[2]["content"] == "long older turn"
        assert archived_chunk[-1]["content"] == "older final"
        assert session.last_consolidated == len(session.messages) - 2

        history = session.get_history(max_messages=6, extend_to_user=True)
        assert [m["content"] for m in history] == ["new question", "new answer"]

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
        consolidator.sessions._session_cache[session.key] = session
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
        consolidator.sessions._session_cache[session.key] = session
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
        consolidator.sessions._session_cache[session.key] = session
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
        consolidator.sessions._session_cache[session.key] = session
        consolidator.estimate_session_prompt_tokens = MagicMock(
            side_effect=[(1200, "tiktoken"), (400, "tiktoken")]
        )
        consolidator.archive = AsyncMock(return_value=True)

        await consolidator.maybe_consolidate_by_tokens(session)

        consolidator.archive.assert_awaited_once()
        # pick_consolidation_boundary finds the only boundary at idx=61
        assert session.last_consolidated == 61


class TestCompactIdleSession:
    """Tests for Consolidator.compact_idle_session — lock-protected idle truncation."""

    @pytest.fixture
    def real_consolidator(self, store, mock_provider):
        """Create a Consolidator with a real SessionManager (not a mock)."""
        from nanobot.session.manager import SessionManager

        sessions = SessionManager(store.workspace)
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

    @pytest.mark.asyncio
    async def test_archives_prefix_keeps_suffix(self, real_consolidator, mock_provider):
        """20 user/assistant turns → compact with max_suffix=8 → messages ≤ 8,
        last_consolidated=0, _last_summary stored."""
        mock_provider.chat_with_retry.return_value = MagicMock(
            content="Summary of old conversation.", finish_reason="stop"
        )
        sessions = real_consolidator.sessions
        session = sessions.get_or_create("cli:test")
        for i in range(20):
            session.add_message("user", f"user msg {i}")
            session.add_message("assistant", f"assistant msg {i}")
        sessions.save(session)

        result = await real_consolidator.compact_idle_session("cli:test", max_suffix=8)
        assert result == "Summary of old conversation."

        reloaded = sessions.get_or_create("cli:test")
        assert len(reloaded.messages) <= 8
        assert reloaded.last_consolidated == 0
        meta = reloaded.metadata.get("_last_summary")
        assert meta is not None
        assert meta["text"] == "Summary of old conversation."
        assert "last_active" in meta

    @pytest.mark.asyncio
    async def test_summarizes_retained_suffix_not_just_dropped_prefix(
        self, real_consolidator, mock_provider
    ):
        """idleCompact must summarize over the full unconsolidated tail, including
        the recent suffix it retains. Otherwise a late user correction / final
        result that lands in the kept suffix is excluded from the persisted
        summary, leaving a stale wrong conclusion in history. Regression for #4264."""
        mock_provider.chat_with_retry.return_value = MagicMock(
            content="Summary.", finish_reason="stop"
        )
        sessions = real_consolidator.sessions
        session = sessions.get_or_create("cli:correction")
        for i in range(18):
            session.add_message("user", f"user msg {i}")
            session.add_message("assistant", f"assistant msg {i}")
        # Final correction exchange lands inside the retained max_suffix window.
        session.add_message("user", "no, that's wrong, use approach B")
        session.add_message("assistant", "CORRECTED_FINAL_RESULT_alpha")
        sessions.save(session)

        await real_consolidator.compact_idle_session("cli:correction", max_suffix=8)

        summarized = mock_provider.chat_with_retry.call_args.kwargs["messages"][1]["content"]
        assert "CORRECTED_FINAL_RESULT_alpha" in summarized

    @pytest.mark.asyncio
    async def test_raw_dumps_only_dropped_messages_on_llm_failure(
        self, real_consolidator, mock_provider, store
    ):
        """Summarizing over the full tail must not widen what gets raw-dumped on
        LLM failure: the breadcrumb should contain only the removed prefix, not
        the retained suffix that stays live in the session. Regression for #4264."""
        mock_provider.chat_with_retry.side_effect = RuntimeError("LLM unavailable")
        sessions = real_consolidator.sessions
        session = sessions.get_or_create("cli:rawdrop")
        for i in range(18):
            session.add_message("user", f"user msg {i}")
            session.add_message("assistant", f"assistant msg {i}")
        session.add_message("user", "final user follow-up")
        session.add_message("assistant", "RETAINED_SUFFIX_marker")
        sessions.save(session)

        await real_consolidator.compact_idle_session("cli:rawdrop", max_suffix=8)

        raw = "\n".join(e["content"] for e in store.read_unprocessed_history(since_cursor=0))
        assert "[RAW]" in raw
        assert "user msg 0" in raw  # removed prefix is the breadcrumb
        assert "RETAINED_SUFFIX_marker" not in raw  # retained suffix not dumped

    @pytest.mark.asyncio
    async def test_idle_compact_writes_session_key_to_history(
        self,
        real_consolidator,
        mock_provider,
        store,
    ):
        mock_provider.chat_with_retry.return_value = MagicMock(
            content="Summary of old conversation.", finish_reason="stop"
        )
        session = real_consolidator.sessions.get_or_create("cli:test")
        for i in range(10):
            session.add_message("user", f"user msg {i}")
            session.add_message("assistant", f"assistant msg {i}")
        real_consolidator.sessions.save(session)

        await real_consolidator.compact_idle_session("cli:test", max_suffix=4)

        entries = store.read_unprocessed_history(since_cursor=0)
        assert entries[0]["session_key"] == "cli:test"

    @pytest.mark.asyncio
    async def test_empty_session_refreshes_timestamp(self, real_consolidator):
        """Empty session with old updated_at → refreshed after call, returns ''."""
        from datetime import datetime, timedelta

        sessions = real_consolidator.sessions
        session = sessions.get_or_create("cli:empty")
        old_ts = datetime.now() - timedelta(hours=2)
        session.updated_at = old_ts
        sessions.save(session)

        result = await real_consolidator.compact_idle_session("cli:empty")
        assert result == ""

        reloaded = sessions.get_or_create("cli:empty")
        assert reloaded.updated_at > old_ts

    @pytest.mark.asyncio
    async def test_nothing_summary_not_stored(self, real_consolidator, mock_provider):
        """LLM returns '(nothing)' → _last_summary NOT in metadata."""
        mock_provider.chat_with_retry.return_value = MagicMock(
            content="(nothing)", finish_reason="stop"
        )
        sessions = real_consolidator.sessions
        session = sessions.get_or_create("cli:nothing")
        for i in range(10):
            session.add_message("user", f"u{i}")
            session.add_message("assistant", f"a{i}")
        sessions.save(session)

        result = await real_consolidator.compact_idle_session("cli:nothing", max_suffix=4)
        assert result == "(nothing)"

        reloaded = sessions.get_or_create("cli:nothing")
        assert "_last_summary" not in reloaded.metadata

    @pytest.mark.asyncio
    async def test_llm_failure_still_truncates(self, real_consolidator, mock_provider, store):
        """LLM raises RuntimeError → raw_archive fires, session still truncated, returns None."""
        mock_provider.chat_with_retry.side_effect = RuntimeError("LLM unavailable")
        sessions = real_consolidator.sessions
        session = sessions.get_or_create("cli:fail")
        for i in range(10):
            session.add_message("user", f"u{i}")
            session.add_message("assistant", f"a{i}")
        sessions.save(session)

        result = await real_consolidator.compact_idle_session("cli:fail", max_suffix=4)
        assert result is None

        # raw_archive should have been called (history.jsonl gets an entry)
        entries = store.read_unprocessed_history(since_cursor=0)
        assert any("[RAW]" in e["content"] for e in entries)

        # Session should still be truncated
        reloaded = sessions.get_or_create("cli:fail")
        assert len(reloaded.messages) <= 4

    @pytest.mark.asyncio
    async def test_respects_last_consolidated(self, real_consolidator, mock_provider):
        """30 turns with last_consolidated=50 → only unconsolidated tail considered."""
        mock_provider.chat_with_retry.return_value = MagicMock(
            content="Tail summary.", finish_reason="stop"
        )
        sessions = real_consolidator.sessions
        session = sessions.get_or_create("cli:offset")
        for i in range(30):
            session.add_message("user", f"u{i}")
            session.add_message("assistant", f"a{i}")
        session.last_consolidated = 50  # Only 10 messages unconsolidated
        sessions.save(session)

        result = await real_consolidator.compact_idle_session("cli:offset", max_suffix=4)
        assert result == "Tail summary."

        # Verify only the unconsolidated tail was processed:
        # 10 unconsolidated messages (50-59), keep suffix of 4 → archive 6
        archived_call = mock_provider.chat_with_retry.call_args
        user_content = archived_call.kwargs["messages"][1]["content"]
        # Should contain only tail messages, not early ones
        assert "u0" not in user_content
        assert "u25" in user_content or "a25" in user_content

    @pytest.mark.asyncio
    async def test_non_contiguous_suffix_archives_actual_dropped_messages(
        self,
        real_consolidator,
        mock_provider,
    ):
        """Assistant-only tails extend back to the latest user turn, so archive
        the actual dropped messages rather than a computed prefix."""
        mock_provider.chat_with_retry.return_value = MagicMock(
            content="Tail summary.", finish_reason="stop"
        )
        sessions = real_consolidator.sessions
        session = sessions.get_or_create("cli:noncontiguous")
        for i in range(15):
            session.add_message("user", f"user-{i:02d}")
        for i in range(10):
            session.add_message("assistant", f"assistant-{i:02d}")
        sessions.save(session)

        result = await real_consolidator.compact_idle_session("cli:noncontiguous", max_suffix=6)
        assert result == "Tail summary."

        reloaded = sessions.get_or_create("cli:noncontiguous")
        assert [m["content"] for m in reloaded.messages] == [
            "user-14",
            "assistant-00",
            "assistant-01",
            "assistant-02",
            "assistant-03",
            "assistant-04",
            "assistant-05",
            "assistant-06",
            "assistant-07",
            "assistant-08",
            "assistant-09",
        ]

        # #4264: idle compaction now summarizes the full unconsolidated tail, so
        # the dropped head (user-00) and retained suffix (user-14 through
        # assistant-09) are all summarized.
        archived_call = mock_provider.chat_with_retry.call_args
        user_content = archived_call.kwargs["messages"][1]["content"]
        assert "user-00" in user_content
        assert "assistant-09" in user_content
        assert "user-14" in user_content

    @pytest.mark.asyncio
    async def test_acquires_consolidation_lock(self, real_consolidator, mock_provider):
        """Verify lock is held during execution."""
        import asyncio

        # Use a slow LLM response to ensure the lock is held while we check
        started = asyncio.Event()
        release_chat = asyncio.Event()

        async def slow_chat(**kwargs):
            started.set()
            await release_chat.wait()
            return LLMResponse(content="Summary.", finish_reason="stop")

        mock_provider.chat_with_retry = slow_chat

        sessions = real_consolidator.sessions
        session = sessions.get_or_create("cli:lock")
        for i in range(10):
            session.add_message("user", f"u{i}")
            session.add_message("assistant", f"a{i}")
        sessions.save(session)

        lock = real_consolidator.get_lock("cli:lock")
        assert not lock.locked()

        task = asyncio.ensure_future(
            real_consolidator.compact_idle_session("cli:lock", max_suffix=4)
        )
        await started.wait()
        assert lock.locked()
        release_chat.set()
        await task
        assert not lock.locked()


class TestConsolidatorSessionRefresh:
    """Background consolidation must detect stale session references."""

    @pytest.mark.asyncio
    async def test_reloads_before_empty_session_guard(self, tmp_path):
        """A stale empty reference must not skip a non-empty cached session."""
        from nanobot.agent.memory import Consolidator, MemoryStore
        from nanobot.session.manager import Session, SessionManager

        store = MemoryStore(tmp_path)
        provider = MagicMock()
        provider.chat_with_retry = AsyncMock(
            return_value=MagicMock(content="summary", finish_reason="stop")
        )
        provider.generation.max_tokens = 4096
        provider.estimate_prompt_tokens = MagicMock(return_value=(10, "test"))
        sessions = SessionManager(tmp_path)
        consolidator = Consolidator(
            store=store,
            provider=provider,
            model="test-model",
            sessions=sessions,
            context_window_tokens=128_000,
            build_messages=MagicMock(return_value=[]),
            get_tool_definitions=MagicMock(return_value=[]),
        )

        fresh = sessions.get_or_create("cli:test")
        fresh.add_message("user", "fresh message")
        sessions.save(fresh)
        stale_empty = Session(key="cli:test")

        seen: dict[str, Session] = {}

        def estimate(session: Session):
            seen["session"] = session
            return 10, "test"

        consolidator.estimate_session_prompt_tokens = MagicMock(side_effect=estimate)

        await consolidator.maybe_consolidate_by_tokens(stale_empty)

        assert seen["session"] is fresh

    @pytest.mark.asyncio
    async def test_reloads_stale_session_after_compact(self, tmp_path):
        """After compact_idle_session replaces the session, a concurrent
        maybe_consolidate_by_tokens with the old reference should use the
        fresh session from cache instead of overwriting."""
        from nanobot.agent.memory import Consolidator, MemoryStore
        from nanobot.session.manager import SessionManager

        store = MemoryStore(tmp_path)
        provider = MagicMock()
        provider.chat_with_retry = AsyncMock(
            return_value=MagicMock(content="summary", finish_reason="stop")
        )
        provider.generation.max_tokens = 4096
        provider.estimate_prompt_tokens = MagicMock(return_value=(10, "test"))
        sessions = SessionManager(tmp_path)
        consolidator = Consolidator(
            store=store,
            provider=provider,
            model="test-model",
            sessions=sessions,
            context_window_tokens=128_000,
            build_messages=MagicMock(return_value=[]),
            get_tool_definitions=MagicMock(return_value=[]),
        )

        # Populate session with many messages
        session = sessions.get_or_create("cli:test")
        for i in range(20):
            session.add_message("user", f"u{i}")
            session.add_message("assistant", f"a{i}")
        sessions.save(session)

        # Simulate: background consolidation captures old reference
        old_ref = session

        # AutoCompact runs first and truncates to 8
        await consolidator.compact_idle_session("cli:test", max_suffix=8)

        # Background consolidation runs with stale reference —
        # should detect the session was replaced and not undo the compact.
        await consolidator.maybe_consolidate_by_tokens(old_ref)

        session_after = sessions.get_or_create("cli:test")
        # Messages should still be truncated (not restored to 40)
        assert len(session_after.messages) <= 8


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

    def test_raw_archive_preserves_session_key(self, store):
        messages = [{"role": "user", "content": "hello"}]
        store.raw_archive(messages, session_key="websocket:chat-1")
        entries = store.read_unprocessed_history(since_cursor=0)
        assert entries[0]["session_key"] == "websocket:chat-1"

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
        assert token_count <= 9_900


def test_estimate_session_prompt_tokens_mirrors_microcompact_when_enabled(tmp_path):
    """#4222: status/consolidation estimates should match runner compaction."""
    from nanobot.agent.context import ContextBuilder
    from nanobot.agent.runner import _MICROCOMPACT_KEEP_RECENT, _MICROCOMPACT_MIN_CHARS

    ctx = ContextBuilder(workspace=tmp_path)
    store = MemoryStore(tmp_path)
    sessions = MagicMock()
    session = Session(key="websocket:cache")
    session.add_message("user", "inspect files")
    long_content = "z" * (_MICROCOMPACT_MIN_CHARS + 80)
    for i in range(_MICROCOMPACT_KEEP_RECENT + 3):
        session.messages.append(
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": f"c{i}",
                        "type": "function",
                        "function": {"name": "read_file", "arguments": "{}"},
                    }
                ],
            }
        )
        session.messages.append(
            {"role": "tool", "tool_call_id": f"c{i}", "name": "read_file", "content": long_content}
        )

    enabled = Consolidator(
        store=store,
        provider=_counting_provider(),
        model="test-model",
        sessions=sessions,
        context_window_tokens=100_000,
        build_messages=ctx.build_messages,
        get_tool_definitions=MagicMock(return_value=[]),
        microcompact_tool_results=True,
    )
    disabled = Consolidator(
        store=store,
        provider=_counting_provider(),
        model="test-model",
        sessions=sessions,
        context_window_tokens=100_000,
        build_messages=ctx.build_messages,
        get_tool_definitions=MagicMock(return_value=[]),
        microcompact_tool_results=False,
    )

    enabled_tokens, _ = enabled.estimate_session_prompt_tokens(session)
    disabled_tokens, _ = disabled.estimate_session_prompt_tokens(session)

    assert enabled_tokens < disabled_tokens


def test_estimate_session_prompt_tokens_can_disable_microcompact(tmp_path):
    """#4222: disabling microcompact leaves old tool results in the token probe."""
    from nanobot.agent.context import ContextBuilder
    from nanobot.agent.runner import _MICROCOMPACT_KEEP_RECENT, _MICROCOMPACT_MIN_CHARS

    captured: list[dict] = []
    provider = MagicMock()

    def estimate_prompt_tokens(messages, _tools, _model):
        captured[:] = messages
        return _message_text_chars(messages), "chars"

    provider.estimate_prompt_tokens.side_effect = estimate_prompt_tokens
    ctx = ContextBuilder(workspace=tmp_path)
    store = MemoryStore(tmp_path)
    session = Session(key="websocket:cache")
    session.add_message("user", "inspect files")
    long_content = "q" * (_MICROCOMPACT_MIN_CHARS + 80)
    for i in range(_MICROCOMPACT_KEEP_RECENT + 3):
        session.messages.append(
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": f"c{i}",
                        "type": "function",
                        "function": {"name": "read_file", "arguments": "{}"},
                    }
                ],
            }
        )
        session.messages.append(
            {"role": "tool", "tool_call_id": f"c{i}", "name": "read_file", "content": long_content}
        )

    consolidator = Consolidator(
        store=store,
        provider=provider,
        model="test-model",
        sessions=MagicMock(),
        context_window_tokens=100_000,
        build_messages=ctx.build_messages,
        get_tool_definitions=MagicMock(return_value=[]),
        microcompact_tool_results=False,
    )

    consolidator.estimate_session_prompt_tokens(session)

    tool_messages = [m for m in captured if m.get("role") == "tool"]
    assert len(tool_messages) == _MICROCOMPACT_KEEP_RECENT + 3
    assert all(m.get("content") == long_content for m in tool_messages)
    assert "omitted from context" not in "\n".join(str(m.get("content")) for m in captured)
