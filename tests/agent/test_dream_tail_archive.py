"""Tests for the Dream-tail archive path (#3973).

Short sessions (<= AutoCompact._RECENT_SUFFIX_MESSAGES total messages) can never
produce a compactable tail under the existing idle-archive path, because
retain_recent_legal_suffix always keeps everything when the session is that
short. That means history.jsonl stays empty for them forever, starving Dream of
input for what is the most common conversation shape. These tests cover the
lightweight, independent tail-archive path added to close that gap, and the
corresponding boundary adjustments in Consolidator so it never re-archives a
range that tail-archive already covered.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.agent.memory import DREAM_TAIL_SESSION_KEY_PREFIX, Consolidator
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import LLMResponse
from nanobot.runtime_context import RUNTIME_CONTEXT_HISTORY_META


def _make_loop(tmp_path: Path, session_ttl_minutes: int = 15) -> AgentLoop:
    """Minimal AgentLoop with a deterministic fake LLM provider (mirrors test_auto_compact.py)."""
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
    for i in range(turns):
        session.add_message("user", f"{prefix} user {i}")
        session.add_message("assistant", f"{prefix} assistant {i}")


async def _drain_background_tasks(loop: AgentLoop) -> None:
    tasks = list(loop._background_tasks)
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    await asyncio.sleep(0)


async def _run_check_expired(loop: AgentLoop, active_session_keys=()) -> None:
    loop.auto_compact.check_expired(
        loop.schedule_background,
        loop.runtime_for_session,
        active_session_keys=active_session_keys,
    )
    await _drain_background_tasks(loop)


def _history_entries_for(loop: AgentLoop, session_key: str) -> list[dict]:
    """Entries produced by/for this session, whether written under its own
    real key (real consolidation) or dream-tail-archive prefixed."""
    entries = loop.context.memory.read_unprocessed_history(since_cursor=0)
    tail_key = f"{DREAM_TAIL_SESSION_KEY_PREFIX}{session_key}"
    return [e for e in entries if e.get("session_key") in (session_key, tail_key)]


class TestDreamTailArchiveBasics:
    """A short idle session should get a history.jsonl entry, exactly once."""

    @pytest.mark.asyncio
    async def test_short_idle_session_produces_a_history_entry(self, tmp_path):
        loop = _make_loop(tmp_path, session_ttl_minutes=15)  # shipped default
        session = loop.sessions.get_or_create("cli:short")
        _add_turns(session, 2, prefix="short")  # 4 messages, well under the 8-floor
        session.updated_at = datetime.now() - timedelta(minutes=20)
        loop.sessions.save(session)

        await _run_check_expired(loop)

        entries = _history_entries_for(loop, "cli:short")
        assert len(entries) > 0, (
            "Short idle sessions must produce a history.jsonl entry even under the "
            "default TTL — otherwise Dream never has input for short conversations."
        )
        await loop.close_mcp()

    @pytest.mark.asyncio
    async def test_second_scan_does_not_duplicate(self, tmp_path):
        loop = _make_loop(tmp_path, session_ttl_minutes=15)
        session = loop.sessions.get_or_create("cli:short")
        _add_turns(session, 2, prefix="short")
        session.updated_at = datetime.now() - timedelta(minutes=20)
        loop.sessions.save(session)

        await _run_check_expired(loop)
        first_count = len(_history_entries_for(loop, "cli:short"))
        assert first_count > 0

        # Second scan: nothing changed, session still "idle" (updated_at untouched).
        await _run_check_expired(loop)
        second_count = len(_history_entries_for(loop, "cli:short"))
        assert second_count == first_count, (
            f"Idempotency violated: first scan wrote {first_count} entries, "
            f"second scan produced {second_count}."
        )
        await loop.close_mcp()

    @pytest.mark.asyncio
    async def test_long_session_does_not_take_the_tail_branch(self, tmp_path):
        """Sessions with > 8 messages must still take the existing
        compact_idle_session path unchanged — the new branch must not fire."""
        loop = _make_loop(tmp_path, session_ttl_minutes=15)
        session = loop.sessions.get_or_create("cli:long")
        _add_turns(session, 6, prefix="old")  # 12 messages, > 8-message floor
        session.updated_at = datetime.now() - timedelta(minutes=20)
        loop.sessions.save(session)

        tail_archive_called = False
        original = loop.auto_compact._dream_tail_archive

        async def _spy(key):
            nonlocal tail_archive_called
            tail_archive_called = True
            await original(key)

        loop.auto_compact._dream_tail_archive = _spy

        await _run_check_expired(loop)

        assert not tail_archive_called, (
            "Regression: the new Dream-tail branch fired for a >8-message session "
            "that should have taken the existing compact_idle_session path instead."
        )
        session_after = loop.sessions.get_or_create("cli:long")
        # Existing retain-8 behavior must be completely unaffected.
        assert len(session_after.get_history(max_messages=20)) == (
            loop.auto_compact._RECENT_SUFFIX_MESSAGES
        )
        await loop.close_mcp()


class TestDreamTailArchiveIncrementalMessages:
    """New messages added after a session was already tail-archived must
    eventually surface, and must be routed to the correct branch."""

    @pytest.mark.asyncio
    async def test_new_messages_after_tail_archive_are_not_permanently_skipped(self, tmp_path):
        loop = _make_loop(tmp_path, session_ttl_minutes=15)
        session = loop.sessions.get_or_create("cli:short")
        _add_turns(session, 2, prefix="short")  # 4 messages
        session.updated_at = datetime.now() - timedelta(minutes=20)
        loop.sessions.save(session)

        await _run_check_expired(loop)
        assert len(_history_entries_for(loop, "cli:short")) == 1

        # Session "resumes": 2 more messages, then idle again.
        session = loop.sessions.get_or_create("cli:short")
        _add_turns(session, 1, prefix="resumed")  # +2 messages = 6 total
        session.updated_at = datetime.now() - timedelta(minutes=20)
        loop.sessions.save(session)

        await _run_check_expired(loop)
        entries = _history_entries_for(loop, "cli:short")
        all_content = "\n".join(e.get("content", "") for e in entries)
        assert "resumed" in all_content, (
            "The 2 new messages added after the first tail-archive were never "
            "written to history.jsonl by a second idle scan — permanently invisible "
            "to Dream. Entries seen: " + repr(entries)
        )
        await loop.close_mcp()

    @pytest.mark.asyncio
    async def test_resume_past_the_retain_floor_is_not_dropped_by_the_wrong_branch(self, tmp_path):
        """A session that resumes and grows past the 8-message retain floor, but
        whose only genuinely new content still fits under that floor, must not
        fall through the crack between _has_compactable_idle_tail (which only
        sees the real archive path) and _needs_dream_tail_archive (the fallback)."""
        loop = _make_loop(tmp_path, session_ttl_minutes=15)
        session = loop.sessions.get_or_create("cli:edge")
        _add_turns(session, 2, prefix="original")  # 4 messages
        session.updated_at = datetime.now() - timedelta(minutes=20)
        loop.sessions.save(session)

        await _run_check_expired(loop)
        first_entries = _history_entries_for(loop, "cli:edge")
        assert len(first_entries) == 1
        assert "original" in first_entries[0]["content"]

        # 4 original + 6 new = 10 total messages: _has_compactable_idle_tail
        # (unpatched) would see 10 messages from index 0 and find something to
        # drop, routing into compact_idle_session — which then correctly starts
        # from the tail marker, finds only 6 new messages (<= 8), and no-ops,
        # silently losing this scan's worth of new content unless the boundary
        # check is itself marker-aware.
        session = loop.sessions.get_or_create("cli:edge")
        _add_turns(session, 3, prefix="resumed")  # 4 + 6 = 10 messages total
        session.updated_at = datetime.now() - timedelta(minutes=20)
        loop.sessions.save(session)

        await _run_check_expired(loop)

        all_entries = _history_entries_for(loop, "cli:edge")
        all_content = "\n".join(e.get("content", "") for e in all_entries)
        assert "resumed" in all_content, (
            "The new messages fell through the if/elif crack: neither the real "
            "archive path nor the dream-tail path picked them up. Entries: "
            + repr(all_entries)
        )
        original_reappears_in_new_entry = any(
            e["cursor"] != first_entries[0]["cursor"] and "original" in e.get("content", "")
            for e in all_entries
        )
        assert not original_reappears_in_new_entry, (
            "The already tail-archived 'original ...' messages were re-archived "
            "into a second entry — duplicate Dream input."
        )

        # Recent-8 legality: session.get_history should still return a coherent,
        # role-legal suffix regardless of which branch fired.
        session_after = loop.sessions.get_or_create("cli:edge")
        recent = session_after.get_history(max_messages=20)
        assert recent, "Expected some recent history to remain visible for the live prompt"
        await loop.close_mcp()


class TestDreamTailArchiveNoDuplicateOnRealConsolidation:
    """Neither direction of the two archive paths may re-cover content the other
    one already archived: real consolidation must not re-summarize tail-archived
    content, and tail-archive must not re-dump already-consolidated content."""

    @pytest.mark.asyncio
    async def test_tail_archive_never_fires_once_real_consolidation_has_touched_a_session(self, tmp_path):
        """A session that already went through real consolidation must never be
        routed to the tail-archive path again, even once its unconsolidated
        remainder shrinks to <= 8 messages (the normal post-compaction state).
        Without the last_consolidated == 0 gate, a session's entire protected
        recent suffix would get raw-dumped into Dream on the very next idle
        tick after any real compaction — a much bigger behavior change than
        this fix's scope (sessions that can never produce ANY entry at all)."""
        loop = _make_loop(tmp_path, session_ttl_minutes=15)
        session = loop.sessions.get_or_create("cli:consolidated-first")
        _add_turns(session, 6, prefix="old")  # 12 messages: > 8-message floor
        session.updated_at = datetime.now() - timedelta(minutes=20)
        loop.sessions.save(session)

        # First scan: real archive path fires (has_compactable_idle_tail=True for
        # 12 messages), archives a prefix via compact_idle_session, advances
        # last_consolidated. The tail marker is untouched (still 0).
        await _run_check_expired(loop)
        session = loop.sessions.get_or_create("cli:consolidated-first")
        assert session.last_consolidated > 0, "Expected real consolidation to have archived a prefix"
        assert Consolidator.dream_tail_marker(session) == 0, "Tail marker should be untouched by the real path"
        first_entries = _history_entries_for(loop, "cli:consolidated-first")
        assert len(first_entries) == 1

        # Second scan: session is idle again with zero new messages. The gate
        # must keep it out of the tail-archive branch entirely — no new entry.
        session.updated_at = datetime.now() - timedelta(minutes=20)
        loop.sessions.save(session)
        await _run_check_expired(loop)

        all_entries = _history_entries_for(loop, "cli:consolidated-first")
        assert len(all_entries) == 1, (
            "A session real consolidation has already touched must not get its "
            "protected recent-suffix raw-dumped by the tail path on a later "
            f"idle tick. Entries: {all_entries!r}"
        )
        await loop.close_mcp()

    @pytest.mark.asyncio
    async def test_formal_consolidation_does_not_recover_tail_archived_messages(self, tmp_path):
        # Small context window so real token-based consolidation actually triggers
        # once the session grows, using the real tokenizer (no fake override).
        bus = MessageBus()
        provider = MagicMock()
        provider.get_default_model.return_value = "test-model"
        provider.chat_with_retry = AsyncMock(
            return_value=LLMResponse(content="[SUMMARY of formal consolidation]", tool_calls=[])
        )
        provider.generation.max_tokens = 100
        loop = AgentLoop(
            bus=bus, provider=provider, workspace=tmp_path, model="test-model",
            context_window_tokens=1000, session_ttl_minutes=15,
        )
        loop.tools.get_definitions = MagicMock(return_value=[])

        session = loop.sessions.get_or_create("cli:grows")
        _add_turns(session, 2, prefix="original")  # 4 messages, the ones tail will cover
        session.updated_at = datetime.now() - timedelta(minutes=20)
        loop.sessions.save(session)

        # Step 1: idle tail-archive fires for the short session.
        await _run_check_expired(loop)
        tail_entries = _history_entries_for(loop, "cli:grows")
        assert len(tail_entries) == 1
        assert "original" in tail_entries[0]["content"]

        # Step 2: session "resumes" and grows enough to blow the (small) token budget.
        session = loop.sessions.get_or_create("cli:grows")
        _add_turns(session, 40, prefix="growth")
        loop.sessions.save(session)

        # Spy on the real archive() input: what was actually fed into consolidation,
        # not the LLM's (mocked, input-independent) output text.
        captured_chunks: list[list[dict]] = []
        real_archive = loop.consolidator.archive

        async def _spy_archive(messages, **kwargs):
            captured_chunks.append(messages)
            return await real_archive(messages, **kwargs)

        loop.consolidator.archive = _spy_archive

        runtime = loop.runtime_for_session(session)
        await loop.consolidator.maybe_consolidate_by_tokens(session, runtime=runtime)

        assert captured_chunks, "Expected maybe_consolidate_by_tokens to call archive() at least once"
        for chunk in captured_chunks:
            chunk_text = " ".join(str(m.get("content", "")) for m in chunk)
            assert "original" not in chunk_text, (
                "Formal consolidation's input chunk contains messages already "
                "delivered to Dream via the tail entry. Captured chunk: " + repr(chunk)
            )
        all_chunk_text = " ".join(
            str(m.get("content", "")) for chunk in captured_chunks for m in chunk
        )
        assert "growth" in all_chunk_text, (
            "Sanity check failed: formal consolidation's input chunk should still "
            "contain the newer 'growth ...' messages — if it doesn't, the boundary "
            "fix over-skipped and messages are being silently dropped, not just "
            "de-duplicated."
        )
        await loop.close_mcp()

    @pytest.mark.asyncio
    async def test_formal_consolidation_still_shows_the_llm_the_tail_archived_prefix_as_context(self, tmp_path):
        """Excluding tail-archived content from archive()'s removal/raw-fallback
        chunk (verified above) is correct — but that content must not also
        disappear from the LLM's summarization *context* (summary_messages),
        or a session's earliest content becomes invisible everywhere except
        Dream's raw history: not in the live prompt (trimmed by real
        consolidation), not in the persisted summary (excluded here), only in
        history.jsonl. summary_messages is never written anywhere itself, so
        including the tail-archived prefix there can't cause duplication."""
        bus = MessageBus()
        provider = MagicMock()
        provider.get_default_model.return_value = "test-model"
        provider.chat_with_retry = AsyncMock(
            return_value=LLMResponse(content="[SUMMARY]", tool_calls=[])
        )
        provider.generation.max_tokens = 100
        loop = AgentLoop(
            bus=bus, provider=provider, workspace=tmp_path, model="test-model",
            context_window_tokens=1000, session_ttl_minutes=15,
        )
        loop.tools.get_definitions = MagicMock(return_value=[])

        session = loop.sessions.get_or_create("cli:grows2")
        _add_turns(session, 2, prefix="original")  # 4 messages, tail will cover these
        session.updated_at = datetime.now() - timedelta(minutes=20)
        loop.sessions.save(session)

        await _run_check_expired(loop)
        assert len(_history_entries_for(loop, "cli:grows2")) == 1

        session = loop.sessions.get_or_create("cli:grows2")
        _add_turns(session, 40, prefix="growth")
        loop.sessions.save(session)

        captured_summary_messages: list[list[dict] | None] = []
        real_archive = loop.consolidator.archive

        async def _spy_archive(messages, **kwargs):
            captured_summary_messages.append(kwargs.get("summary_messages"))
            return await real_archive(messages, **kwargs)

        loop.consolidator.archive = _spy_archive

        runtime = loop.runtime_for_session(session)
        await loop.consolidator.maybe_consolidate_by_tokens(session, runtime=runtime)

        assert captured_summary_messages, "Expected archive() to be called at least once"
        all_summary_text = " ".join(
            str(m.get("content", ""))
            for msgs in captured_summary_messages if msgs
            for m in msgs
        )
        assert "original" in all_summary_text, (
            "The LLM's summarization context should still include the "
            "tail-archived prefix, even though it's excluded from the "
            "removal/raw-fallback chunk. Captured summary_messages: "
            + repr(captured_summary_messages)
        )
        await loop.close_mcp()


class TestDreamTailArchiveTruncationStillAdvancesMarker:
    """raw_archive() truncates at _RAW_ARCHIVE_MAX_CHARS (16k); the marker must
    still advance past all of new_messages regardless, matching every other
    raw-dump path in this codebase. The truncated remainder is permanently
    lost, not retried — a documented, accepted limitation (see the PR
    description), locked here so a future change can't silently alter it."""

    @pytest.mark.asyncio
    async def test_marker_advances_past_a_message_too_large_to_fit_in_the_dump(self, tmp_path):
        loop = _make_loop(tmp_path, session_ttl_minutes=15)
        session = loop.sessions.get_or_create("cli:huge")
        session.add_message("user", "x" * 20_000)  # exceeds the 16k raw-dump cap
        session.add_message("assistant", "ok")
        session.updated_at = datetime.now() - timedelta(minutes=20)
        loop.sessions.save(session)

        await _run_check_expired(loop)

        session_after = loop.sessions.get_or_create("cli:huge")
        marker = Consolidator.dream_tail_marker(session_after)
        assert marker == 2, (
            "The marker must advance past both messages even though the raw "
            f"dump truncated the oversized one — got marker={marker}. A "
            "marker that stalls here would make the idle scan retry the same "
            "oversized message forever."
        )
        entries = _history_entries_for(loop, "cli:huge")
        assert entries, "Expected a (truncated) entry to still be written"
        assert len(entries[0]["content"]) < 20_000, (
            "Sanity check: the entry should actually be truncated, not the "
            "full 20k message verbatim"
        )
        await loop.close_mcp()


class TestDreamTailArchiveConcurrentTurn:
    """session.messages is not protected by the consolidator lock against normal
    turn processing (only other archive-path callers respect it) — a message
    appended concurrently, between the tail-archive slice and the marker write,
    must not get silently marked as archived without ever being written."""

    @pytest.mark.asyncio
    async def test_marker_reflects_the_archived_range_not_live_length_at_write_time(self, tmp_path):
        loop = _make_loop(tmp_path, session_ttl_minutes=15)
        session = loop.sessions.get_or_create("cli:race")
        _add_turns(session, 2, prefix="short")  # 4 messages
        session.updated_at = datetime.now() - timedelta(minutes=20)
        loop.sessions.save(session)

        # Inject a concurrent append between the slice (inside raw_archive, called
        # after start/new_messages are already computed) and the marker write —
        # simulating a live turn racing the background tail-archive task.
        real_raw_archive = loop.consolidator.store.raw_archive

        def _raw_archive_then_concurrent_append(*args, **kwargs):
            real_raw_archive(*args, **kwargs)
            live_session = loop.sessions.get_or_create("cli:race")
            live_session.add_message("user", "concurrent turn message")

        loop.consolidator.store.raw_archive = _raw_archive_then_concurrent_append

        await _run_check_expired(loop)

        session_after = loop.sessions.get_or_create("cli:race")
        marker = Consolidator.dream_tail_marker(session_after)
        assert marker == 4, (
            "The marker must reflect exactly what was archived (4 messages), not "
            f"the live message count at write time (5, after the concurrent "
            f"append) — got marker={marker}. A marker of 5 here would mean the "
            "concurrently-appended message gets silently treated as already "
            "archived despite never having been written to history.jsonl."
        )
        entries = _history_entries_for(loop, "cli:race")
        assert "concurrent turn message" not in "\n".join(e["content"] for e in entries), (
            "Sanity check: the concurrent message should not appear in the "
            "archive from this scan (it arrived after the slice) — it should "
            "surface on the *next* idle scan instead, now that the marker "
            "correctly still considers it unarchived."
        )
        await loop.close_mcp()


class TestDreamTailArchiveYieldsToRealArchiveGateRace:
    """_needs_dream_tail_archive (the scan) and _dream_tail_archive (the task
    that actually runs under the consolidator lock) aren't atomic: real
    consolidation could advance last_consolidated in between. The task
    re-checks the gate under the lock and must bail out rather than raw-
    dumping content real consolidation already covered."""

    @pytest.mark.asyncio
    async def test_real_consolidation_winning_the_race_makes_the_task_bail_out(self, tmp_path):
        loop = _make_loop(tmp_path, session_ttl_minutes=15)
        session = loop.sessions.get_or_create("cli:gaterace")
        _add_turns(session, 2, prefix="short")  # 4 messages
        session.updated_at = datetime.now() - timedelta(minutes=20)
        loop.sessions.save(session)

        # Scan decides the tail path applies (last_consolidated == 0 here).
        assert loop.auto_compact._needs_dream_tail_archive("cli:gaterace")

        # Simulate real consolidation winning the race and completing first —
        # by the time the scheduled task actually acquires the lock and reads
        # the session, last_consolidated is no longer 0.
        session = loop.sessions.get_or_create("cli:gaterace")
        session.last_consolidated = 2
        loop.sessions.save(session)

        await loop.auto_compact._dream_tail_archive("cli:gaterace")

        entries = _history_entries_for(loop, "cli:gaterace")
        assert entries == [], (
            "The task should have bailed out under the re-checked gate instead "
            f"of raw-dumping content real consolidation already covered. Entries: {entries!r}"
        )
        session_after = loop.sessions.get_or_create("cli:gaterace")
        assert Consolidator.dream_tail_marker(session_after) == 0, (
            "Marker must not advance when the task bails out on the re-checked gate"
        )
        await loop.close_mcp()


class TestDreamTailArchiveYieldsToRealArchiveOnConcurrentGrowth:
    """The scan (_needs_dream_tail_archive) and the actual task
    (_dream_tail_archive) aren't atomic — a burst of activity between them
    could grow the session well past a "lightweight raw dump" amount. The task
    must bail out in that case rather than raw-dumping a large burst
    permanently (no LLM summary, ever, for that content)."""

    @pytest.mark.asyncio
    async def test_large_growth_between_scan_and_run_is_left_for_the_next_real_scan(self, tmp_path):
        loop = _make_loop(tmp_path, session_ttl_minutes=15)
        session = loop.sessions.get_or_create("cli:burst")
        _add_turns(session, 1, prefix="short")  # 2 messages, qualifies for tail-archive
        session.updated_at = datetime.now() - timedelta(minutes=20)
        loop.sessions.save(session)
        assert loop.auto_compact._needs_dream_tail_archive("cli:burst")

        # Simulate a burst of activity landing between the scan's decision and
        # the task actually running under the lock.
        session = loop.sessions.get_or_create("cli:burst")
        _add_turns(session, 20, prefix="burst")  # +40 messages, cleanly droppable
        loop.sessions.save(session)
        assert loop.auto_compact._has_compactable_idle_tail("cli:burst"), (
            "Precondition: this burst shape should be cleanly droppable by the "
            "real path, unlike the unanswered-tail shape in "
            "TestDreamTailArchiveUnanswerableTailDoesNotStarve"
        )

        await loop.auto_compact._dream_tail_archive("cli:burst")

        entries = _history_entries_for(loop, "cli:burst")
        assert entries == [], (
            "Expected the tail-archive task to bail out and leave this large "
            "burst for the next scan's real archive path instead of "
            f"permanently raw-dumping it. Entries: {entries!r}"
        )
        session_after = loop.sessions.get_or_create("cli:burst")
        assert Consolidator.dream_tail_marker(session_after) == 0, (
            "Marker must not advance when the task bails out — otherwise the "
            "burst content would look 'already archived' without ever having "
            "been written anywhere."
        )
        await loop.close_mcp()


class TestDreamTailArchiveUnanswerableTailDoesNotStarve:
    """A raw message count above _RECENT_SUFFIX_MESSAGES is not, by itself, proof
    that the real archive path is viable: retain_recent_legal_suffix(8,
    extend_to_user=True) walks backward to the nearest user turn, and for a
    session shaped like 4 complete Q&A pairs plus one trailing unanswered
    question (9 messages total), that walk lands on index 0 — nothing is
    droppable, so the real path permanently no-ops. The old bail condition
    (bare "> 8 messages") would make the tail task defer to that real path
    forever too, starving the session of any Dream input at all — exactly the
    bug this PR exists to fix, just in a shape the last_consolidated == 0 gate
    doesn't by itself prevent."""

    @pytest.mark.asyncio
    async def test_nine_message_session_with_unanswered_tail_still_gets_archived(self, tmp_path):
        loop = _make_loop(tmp_path, session_ttl_minutes=15)
        session = loop.sessions.get_or_create("cli:nine")
        _add_turns(session, 4, prefix="qa")  # 8 messages: 4 complete Q&A pairs
        session.add_message("user", "unanswered question")  # 9th, no reply
        session.updated_at = datetime.now() - timedelta(minutes=20)
        loop.sessions.save(session)

        assert not loop.auto_compact._has_compactable_idle_tail("cli:nine"), (
            "Precondition: retain_recent_legal_suffix's extend_to_user walk "
            "should find nothing droppable for this exact shape"
        )

        await _run_check_expired(loop)

        entries = _history_entries_for(loop, "cli:nine")
        assert len(entries) == 1, (
            "A session real consolidation can never make progress on must "
            "still get a tail-archive entry, even with > 8 messages. Entries: "
            + repr(entries)
        )

        # Idempotency: a second scan with nothing new must not duplicate.
        session = loop.sessions.get_or_create("cli:nine")
        session.updated_at = datetime.now() - timedelta(minutes=20)
        loop.sessions.save(session)
        await _run_check_expired(loop)
        entries_after_second_scan = _history_entries_for(loop, "cli:nine")
        assert len(entries_after_second_scan) == 1, (
            "Second scan should not duplicate: " + repr(entries_after_second_scan)
        )
        await loop.close_mcp()


class TestDreamTailArchiveCrashSafety:
    """If the process dies between writing the history entry and persisting the
    tail marker, a restarted process may re-archive that range once more — but
    only once the marker save actually succeeds does duplication stop."""

    @pytest.mark.asyncio
    async def test_crash_between_entry_write_and_marker_save_then_process_restart(self, tmp_path):
        loop1 = _make_loop(tmp_path, session_ttl_minutes=15)
        session = loop1.sessions.get_or_create("cli:short")
        _add_turns(session, 2, prefix="short")
        session.updated_at = datetime.now() - timedelta(minutes=20)
        loop1.sessions.save(session)

        # Really write the entry (a normal, completed append_history() call — it
        # is not fsync'd, but it does fully return, unlike a mid-write crash),
        # then raise before the metadata marker is ever set or saved.
        real_raw_archive = loop1.consolidator.store.raw_archive

        def _write_then_crash(*args, **kwargs):
            real_raw_archive(*args, **kwargs)
            raise RuntimeError("simulated process crash after entry write")

        loop1.consolidator.store.raw_archive = _write_then_crash
        await _run_check_expired(loop1)  # exception is caught+logged inside _dream_tail_archive

        entries_after_crash = _history_entries_for(loop1, "cli:short")
        assert len(entries_after_crash) == 1, "The entry write itself should have survived the crash"
        await loop1.close_mcp()

        # Process restart: brand new loop / SessionManager / MemoryStore, same workspace.
        loop2 = _make_loop(tmp_path, session_ttl_minutes=15)
        session_reloaded = loop2.sessions.get_or_create("cli:short")
        assert len(session_reloaded.messages) == 4, "Session content must survive the restart"
        assert Consolidator.DREAM_TAIL_MARKER_KEY not in session_reloaded.metadata, (
            "Precondition check: the marker genuinely was never persisted"
        )
        session_reloaded.updated_at = datetime.now() - timedelta(minutes=20)
        loop2.sessions.save(session_reloaded)

        # First post-restart scan: marker is still missing, so exactly one more
        # duplicate entry is expected (new process has no memory of the crash).
        await _run_check_expired(loop2)
        entries_after_restart_scan_1 = _history_entries_for(loop2, "cli:short")
        assert len(entries_after_restart_scan_1) == 2, (
            f"Expected exactly one duplicate from the first post-restart scan, got "
            f"{len(entries_after_restart_scan_1)} entries total"
        )

        # This scan's marker save should have succeeded (no crash injected this time) —
        # a second post-restart scan must not add a third entry.
        session_reloaded = loop2.sessions.get_or_create("cli:short")
        session_reloaded.updated_at = datetime.now() - timedelta(minutes=20)
        loop2.sessions.save(session_reloaded)
        await _run_check_expired(loop2)
        entries_after_restart_scan_2 = _history_entries_for(loop2, "cli:short")
        assert len(entries_after_restart_scan_2) == 2, (
            "Once a marker save succeeds, duplication must stop — got "
            f"{len(entries_after_restart_scan_2)} entries after a third scan"
        )
        await loop2.close_mcp()


class TestDreamTailMarkerRemappedOnFileCapTrim:
    """Session.enforce_file_cap (triggered past FILE_MAX_MESSAGES, tested here
    with a small custom limit) must remap the tail-archive marker the same way
    it already remaps last_consolidated when trimming session.messages —
    otherwise the marker either duplicates already-covered content or, worse,
    silently excludes a range that was never actually archived."""

    def test_marker_remapped_not_just_clamped_on_trim(self, tmp_path):
        from nanobot.session.manager import Session

        session = Session(key="cli:cap", messages=[], metadata={"_dream_tail_through": 6})
        for i in range(6):
            session.add_message("user", f"msg{i}")
            session.add_message("assistant", f"reply{i}")
        # 12 messages total; marker=6 covers the first 3 user/assistant pairs.

        archived: list[dict] = []
        session.enforce_file_cap(on_archive=archived.extend, limit=8)

        assert len(session.messages) == 8
        new_marker = Consolidator.dream_tail_marker(session)
        # Of the original marker=6 range (indices 0-5), only indices 4-5
        # (msg2/reply2) survive into the retained last-8 window — so the
        # correctly remapped marker is 2, not 6 (unclamped/stale) and not
        # dropped-to-0 (which would falsely treat msg2/reply2 as brand new).
        assert new_marker == 2, (
            f"Expected the marker to be remapped to 2 (how many of the "
            f"originally-covered messages survived the trim), got {new_marker}. "
            "An unremapped/merely-clamped marker would either point at the "
            "wrong message or silently exclude content that was never "
            "actually archived."
        )
        # Everything file-cap dropped (msg0/reply0/msg1/reply1) was already
        # covered by the tail marker (before_marker=6 > all 4 dropped
        # indices), so on_archive must not be called with any of it — doing
        # so would raw-dump content that's already in Dream's input verbatim.
        assert archived == [], (
            "file-cap re-archived content already covered by the tail marker: "
            + repr(archived)
        )

    def test_archive_chunk_still_covers_genuinely_new_content_past_the_marker(self, tmp_path):
        """The marker-awareness fix must not over-exclude: dropped content
        that was never covered by the marker (or last_consolidated) still
        needs to reach on_archive, or it's lost entirely."""
        from nanobot.session.manager import Session

        session = Session(key="cli:cap2", messages=[], metadata={"_dream_tail_through": 2})
        for i in range(6):
            session.add_message("user", f"msg{i}")
            session.add_message("assistant", f"reply{i}")
        # 12 messages; marker=2 covers indices 0-1 (msg0, reply0). Trim to last
        # 8 drops indices 0-3 (msg0/reply0/msg1/reply1) — msg0/reply0 are
        # marker-covered; msg1/reply1 are genuinely new and must still reach
        # on_archive.

        archived: list[dict] = []
        session.enforce_file_cap(on_archive=archived.extend, limit=8)

        archived_text = " ".join(str(m.get("content", "")) for m in archived)
        assert "msg0" not in archived_text and "reply0" not in archived_text, (
            "msg0/reply0 were already marker-covered, should not be re-archived: " + repr(archived)
        )
        assert "msg1" in archived_text and "reply1" in archived_text, (
            "Genuinely unarchived dropped content must still reach on_archive: " + repr(archived)
        )


class TestDreamTailArchiveForkDoesNotDuplicateContent:
    """End-to-end: forking a tail-archived session and letting the fork go idle
    must not produce a second history.jsonl entry with the same verbatim
    content the source session's entry already covers."""

    @pytest.mark.asyncio
    async def test_fork_of_tail_archived_session_does_not_redump_copied_prefix(self, tmp_path):
        loop = _make_loop(tmp_path, session_ttl_minutes=15)
        session = loop.sessions.get_or_create("websocket:source")
        _add_turns(session, 2, prefix="orig")  # 4 messages
        session.updated_at = datetime.now() - timedelta(minutes=20)
        loop.sessions.save(session)

        await _run_check_expired(loop)
        source_entries = _history_entries_for(loop, "websocket:source")
        assert len(source_entries) == 1
        assert "orig user 0" in source_entries[0]["content"]

        forked = loop.sessions.fork_session_before_user_index(
            "websocket:source", "websocket:fork", 1,
            extra_index_metadata_keys=(Consolidator.DREAM_TAIL_MARKER_KEY,),
        )
        assert forked is not None
        forked.updated_at = datetime.now() - timedelta(minutes=20)
        loop.sessions.save(forked)
        await _run_check_expired(loop)

        fork_entries = _history_entries_for(loop, "websocket:fork")
        assert fork_entries == [], (
            "The fork's copy of an already tail-archived prefix must not be "
            "raw-dumped again under the fork's own session_key — that content "
            "is already in Dream's input via the source session's entry. Got: "
            + repr(fork_entries)
        )
        await loop.close_mcp()


class TestDreamTailArchiveLivePromptImpact:
    """A tail-archived entry must not surface in a resumed session's own
    "# Recent History" section: that content is already visible via normal
    conversation history (session.messages is untouched), so re-injecting it
    from history.jsonl would duplicate it in the prompt. Entries are written
    under a "tail:{session_key}" key (see AutoCompact._dream_tail_archive)
    specifically so read_recent_history_for_prompt's exact-match filtering
    (the default, unified_session=False) never picks them up for the real
    session_key, and its unified-session prefix-exclusion also excludes them
    via MemoryStore._INTERNAL_HISTORY_SESSION_PREFIXES. Dream itself is
    unaffected either way: build_dream_prompt consumes history.jsonl by
    cursor only, never by session_key."""

    @pytest.mark.asyncio
    async def test_recent_history_section_excludes_the_tail_dump(self, tmp_path):
        loop = _make_loop(tmp_path, session_ttl_minutes=15)
        session = loop.sessions.get_or_create("cli:resumed")
        _add_turns(session, 2, prefix="short")  # 4 messages
        session.updated_at = datetime.now() - timedelta(minutes=20)
        loop.sessions.save(session)

        await _run_check_expired(loop)
        entries = _history_entries_for(loop, "cli:resumed")
        assert len(entries) == 1

        prompt = loop.context.build_system_prompt(session_key="cli:resumed")
        assert "# Recent History" not in prompt, (
            "The tail-archived entry leaked into Recent History for a resumed "
            "turn on the same session — this duplicates content already "
            "present in normal conversation history, and is permanent (never "
            "self-heals) whenever dream.enabled=False."
        )
        assert "short user 0" not in prompt, (
            "The tail-dump content should not appear anywhere in the system "
            "prompt via Recent History"
        )
        await loop.close_mcp()

    @pytest.mark.asyncio
    async def test_dream_still_consumes_the_tail_entry_by_cursor(self, tmp_path):
        """The "tail:" key rename must not hide the entry from Dream itself —
        build_dream_prompt reads by cursor only, never by session_key."""
        loop = _make_loop(tmp_path, session_ttl_minutes=15)
        session = loop.sessions.get_or_create("cli:resumed2")
        _add_turns(session, 2, prefix="short")  # 4 messages
        session.updated_at = datetime.now() - timedelta(minutes=20)
        loop.sessions.save(session)

        await _run_check_expired(loop)
        result = loop.context.memory.build_dream_prompt()
        assert result is not None, "Expected Dream to have unprocessed input from the tail entry"
        prompt, _last_cursor = result
        assert "short user 0" in prompt, (
            "The tail-archived content should still reach Dream's own prompt "
            "despite being stored under a 'tail:' prefixed session_key"
        )
        await loop.close_mcp()

    @pytest.mark.asyncio
    async def test_write_side_and_filter_side_use_the_same_prefix_constant(self, tmp_path):
        """The write side (AutoCompact._dream_tail_archive) and the filter
        side (MemoryStore._INTERNAL_HISTORY_SESSION_PREFIXES) must derive from
        the same DREAM_TAIL_SESSION_KEY_PREFIX constant, not two independently
        maintained "tail:" literals that could drift apart."""
        loop = _make_loop(tmp_path, session_ttl_minutes=15)
        session = loop.sessions.get_or_create("cli:constcheck")
        _add_turns(session, 2, prefix="short")
        session.updated_at = datetime.now() - timedelta(minutes=20)
        loop.sessions.save(session)

        await _run_check_expired(loop)

        entries = loop.context.memory.read_unprocessed_history(since_cursor=0)
        written_key = next(e["session_key"] for e in entries if "short user 0" in e.get("content", ""))
        assert written_key == f"{DREAM_TAIL_SESSION_KEY_PREFIX}cli:constcheck"
        assert written_key.startswith(DREAM_TAIL_SESSION_KEY_PREFIX)
        await loop.close_mcp()


class TestDreamTailArchiveSafety:
    """The tail-archive path must reuse the same content-safety treatment as
    every other raw-dump path in this codebase."""

    @pytest.mark.asyncio
    async def test_runtime_context_suffix_does_not_leak_into_history(self, tmp_path):
        loop = _make_loop(tmp_path, session_ttl_minutes=15)
        session = loop.sessions.get_or_create("cli:ctx")
        session.add_message(
            "user",
            "visible user text\n\nSECRET_RUNTIME_BLOCK_MARKER",
            **{
                RUNTIME_CONTEXT_HISTORY_META: {
                    "version": 1,
                    "sources": ["webui-quote"],
                    "suffix": "SECRET_RUNTIME_BLOCK_MARKER",
                }
            },
        )
        session.add_message("assistant", "ok")
        session.updated_at = datetime.now() - timedelta(minutes=20)
        loop.sessions.save(session)

        await _run_check_expired(loop)

        entries = _history_entries_for(loop, "cli:ctx")
        assert entries, "Expected the short session to produce a tail entry"
        all_content = "\n".join(e.get("content", "") for e in entries)
        assert "visible user text" in all_content
        assert "SECRET_RUNTIME_BLOCK_MARKER" not in all_content, (
            "Trusted runtime-context content leaked into history.jsonl (and therefore "
            "into Dream's input) — the tail-archive path must apply the same "
            "public_history_messages() stripping that Consolidator.archive() applies "
            "(it does, via MemoryStore.raw_archive())."
        )
        await loop.close_mcp()


class TestDreamTailMarkerDefensiveReads:
    """dream_tail_marker() must reject bool (isinstance(True, int) is True in
    Python — must not silently treat it as 1) and clamp to the current message
    count (a stale marker left over from a trim must not point past the end of
    session.messages, which would make every archive path conclude there's
    permanently nothing to do rather than just re-covering a small range once)."""

    def test_bool_marker_value_is_rejected(self, tmp_path):
        from nanobot.session.manager import Session

        session = Session(key="cli:bool", messages=[], metadata={"_dream_tail_through": True})
        assert Consolidator.dream_tail_marker(session) == 0

    def test_marker_beyond_message_count_is_clamped_not_left_dangling(self, tmp_path):
        from nanobot.session.manager import Session

        session = Session(
            key="cli:stale",
            messages=[{"role": "user", "content": "only one message"}],
            metadata={"_dream_tail_through": 999},
        )
        assert Consolidator.dream_tail_marker(session) == 1, (
            "An unclamped marker (999) would make session.messages[999:] "
            "always empty, permanently hiding this session from every "
            "archive path — not just risking a one-time duplicate."
        )


class TestCmdNewSnapshotSkipsTailArchivedContent:
    """cmd_new (/new) archives an outgoing session's unarchived tail via
    Consolidator.archive() before clearing it. That snapshot must start from
    Consolidator.archive_start(session), not session.last_consolidated alone —
    otherwise a session that was only ever dream-tail-archived would have its
    already-archived prefix fed into a second, real LLM summarization pass."""

    @pytest.mark.asyncio
    async def test_new_snapshot_excludes_already_tail_archived_prefix(self, tmp_path):
        from types import SimpleNamespace
        from unittest.mock import AsyncMock, MagicMock

        from nanobot.bus.events import InboundMessage
        from nanobot.command.builtin import cmd_new
        from nanobot.command.router import CommandContext
        from nanobot.session.manager import SessionManager

        sessions = SessionManager(tmp_path)
        session = sessions.get_or_create("cli:new-after-tail")
        _add_turns(session, 2, prefix="old")  # 4 messages
        session.metadata[Consolidator.DREAM_TAIL_MARKER_KEY] = 4  # already tail-archived
        _add_turns(session, 1, prefix="unarchived")  # +2 messages, never archived
        sessions.save(session)

        admitted_runtime = MagicMock(name="admitted_runtime")
        loop = SimpleNamespace(
            sessions=sessions,
            consolidator=SimpleNamespace(archive=AsyncMock(return_value="summary")),
            _cancel_active_tasks=AsyncMock(return_value=0),
            llm_runtime=MagicMock(return_value=MagicMock()),
            schedule_background=lambda coro: asyncio.ensure_future(coro),
        )
        msg = InboundMessage(
            channel="cli", sender_id="user1", chat_id="1", content="/new",
        )
        ctx = CommandContext(
            msg=msg, session=None, key="cli:new-after-tail", raw="/new",
            loop=loop, runtime=admitted_runtime,
        )

        await cmd_new(ctx)

        loop.consolidator.archive.assert_called_once()
        snapshot = loop.consolidator.archive.call_args.args[0]
        snapshot_text = " ".join(str(m.get("content", "")) for m in snapshot)
        assert "old" not in snapshot_text, (
            "The /new snapshot re-fed already tail-archived messages into a "
            "real LLM summarization pass: " + repr(snapshot)
        )
        assert "unarchived" in snapshot_text, (
            "Sanity check: the genuinely unarchived messages should still be "
            "in the snapshot"
        )
        await asyncio.sleep(0)  # let the scheduled archive() coroutine settle


class TestDreamTailMarkerClearedOnSessionReset:
    """/new (Session.clear()) must reset the tail-archive marker along with
    last_consolidated — otherwise a brand new conversation under the same
    session key inherits a stale marker and its early messages are silently
    treated as already archived, forever."""

    @pytest.mark.asyncio
    async def test_new_conversation_after_clear_is_not_silently_skipped(self, tmp_path):
        loop = _make_loop(tmp_path, session_ttl_minutes=15)
        session = loop.sessions.get_or_create("cli:reset")
        _add_turns(session, 2, prefix="old")  # 4 messages
        session.updated_at = datetime.now() - timedelta(minutes=20)
        loop.sessions.save(session)

        await _run_check_expired(loop)
        first_entries = _history_entries_for(loop, "cli:reset")
        assert len(first_entries) == 1

        session = loop.sessions.get_or_create("cli:reset")
        assert Consolidator.dream_tail_marker(session) == 4
        session.clear()
        assert Consolidator.DREAM_TAIL_MARKER_KEY not in session.metadata, (
            "Session.clear() must drop any registered position-dependent "
            "metadata key, the same way it already drops last_consolidated "
            "and _last_summary."
        )
        loop.sessions.save(session)

        session = loop.sessions.get_or_create("cli:reset")
        _add_turns(session, 1, prefix="new")  # 2 messages in the fresh conversation
        session.updated_at = datetime.now() - timedelta(minutes=20)
        loop.sessions.save(session)
        await _run_check_expired(loop)

        all_entries = _history_entries_for(loop, "cli:reset")
        assert len(all_entries) == 2, (
            f"Expected the post-clear() conversation to produce its own new "
            f"entry, got {len(all_entries)} total entries: {all_entries!r}"
        )
        assert "new user 0" in all_entries[-1]["content"]
        await loop.close_mcp()


class TestLastConsolidatedMustNotCoverTheLiveSuffix:
    """last_consolidated must never advance to cover the entire session:
    doing so would make a resumed short session lose all raw context on the
    next turn, contradicting the documented intent behind retaining a recent
    live suffix (commit 1cb28b3: 'preserve freshest live context' on resume)."""

    def test_advancing_last_consolidated_to_end_loses_raw_resume_context(self, tmp_path):
        loop = _make_loop(tmp_path)
        session = loop.sessions.get_or_create("cli:tiny")
        _add_turns(session, 2, prefix="tiny")  # 4 messages

        # last_consolidated == len(messages) is the scenario this test locks against.
        session.last_consolidated = len(session.messages)

        unconsolidated = Consolidator._full_unconsolidated_history(session)
        assert unconsolidated == [], (
            "Once last_consolidated == len(messages), a resumed short session has "
            "zero raw messages available for the live prompt — it would see only "
            "the (thinner) tail summary, contradicting the documented intent of "
            "commit 1cb28b3 ('preserve freshest live context')."
        )
