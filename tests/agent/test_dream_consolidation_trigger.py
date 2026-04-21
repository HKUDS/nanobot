"""Tests for event-driven Dream triggering on consolidation archive.

Verifies that:
1. Consolidator fires on_archive callback after successful archive
2. Consolidator fires on_archive callback even on LLM failure (raw dump)
3. on_archive callback errors are swallowed (don't break consolidation)
4. Dream.run() is re-entrant safe (concurrent calls don't double-run)
5. AgentLoop wires Consolidator.on_archive → Dream.run() via _schedule_background
6. Concurrency: multi-round archive fires callback each round, Dream lock
   prevents overlapping runs
7. Concurrency: parallel maybe_consolidate_by_tokens on different sessions
8. Concurrency: Dream reads history while Consolidator is still writing
9. Background Dream task exceptions don't crash the event loop
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import pytest

from nanobot.providers.base import LLMResponse


# ═══════════════════════════════════════════════════════════════════════
# 1. Consolidator on_archive callback
# ═══════════════════════════════════════════════════════════════════════

class TestConsolidatorOnArchive:
    """Consolidator should fire on_archive after writing to history."""

    @pytest.fixture
    def consolidator(self):
        from nanobot.agent.memory import Consolidator

        store = MagicMock()
        provider = MagicMock()
        provider.chat_with_retry = AsyncMock(
            return_value=LLMResponse(content="summary", tool_calls=[])
        )
        sessions = MagicMock()
        callback = MagicMock()

        c = Consolidator(
            store=store,
            provider=provider,
            model="test-model",
            sessions=sessions,
            context_window_tokens=128_000,
            build_messages=MagicMock(return_value=[]),
            get_tool_definitions=MagicMock(return_value=[]),
            max_completion_tokens=4096,
            on_archive=callback,
        )
        return c, callback, store, provider

    @pytest.mark.asyncio
    async def test_archive_success_fires_callback(self, consolidator):
        c, callback, store, provider = consolidator
        messages = [{"role": "user", "content": "hello"}]

        result = await c.archive(messages)

        assert result == "summary"
        store.append_history.assert_called_once_with("summary")
        callback.assert_called_once()

    @pytest.mark.asyncio
    async def test_archive_llm_failure_fires_callback(self, consolidator):
        c, callback, store, provider = consolidator
        provider.chat_with_retry = AsyncMock(side_effect=RuntimeError("LLM down"))
        messages = [{"role": "user", "content": "hello"}]

        result = await c.archive(messages)

        assert result is None
        store.raw_archive.assert_called_once_with(messages)
        callback.assert_called_once()

    @pytest.mark.asyncio
    async def test_archive_empty_messages_no_callback(self, consolidator):
        c, callback, store, provider = consolidator

        result = await c.archive([])

        assert result is None
        callback.assert_not_called()

    @pytest.mark.asyncio
    async def test_callback_error_swallowed(self, consolidator):
        c, callback, store, provider = consolidator
        callback.side_effect = RuntimeError("callback boom")
        messages = [{"role": "user", "content": "hello"}]

        # Should NOT raise
        result = await c.archive(messages)

        assert result == "summary"
        callback.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_callback_configured(self):
        """Consolidator without on_archive should work normally."""
        from nanobot.agent.memory import Consolidator

        store = MagicMock()
        provider = MagicMock()
        provider.chat_with_retry = AsyncMock(
            return_value=LLMResponse(content="summary", tool_calls=[])
        )

        c = Consolidator(
            store=store,
            provider=provider,
            model="test-model",
            sessions=MagicMock(),
            context_window_tokens=128_000,
            build_messages=MagicMock(return_value=[]),
            get_tool_definitions=MagicMock(return_value=[]),
            max_completion_tokens=4096,
            # on_archive not set → defaults to None
        )

        result = await c.archive([{"role": "user", "content": "hi"}])
        assert result == "summary"


# ═══════════════════════════════════════════════════════════════════════
# 2. Dream re-entrant lock
# ═══════════════════════════════════════════════════════════════════════

class TestDreamReentrantLock:
    """Dream.run() should skip if already running."""

    @pytest.fixture
    def dream(self, tmp_path):
        from nanobot.agent.memory import Dream

        store = MagicMock()
        store.get_last_dream_cursor.return_value = 0
        store.read_history_since.return_value = []
        provider = MagicMock()

        d = Dream(
            store=store,
            provider=provider,
            model="test-model",
        )
        return d

    @pytest.mark.asyncio
    async def test_concurrent_runs_skip(self, dream):
        """Second concurrent call should return False immediately."""
        barrier = asyncio.Event()
        original_run_inner = dream._run_inner

        async def slow_run_inner():
            await barrier.wait()
            return await original_run_inner()

        dream._run_inner = slow_run_inner

        # Start first run (will block on barrier)
        task1 = asyncio.create_task(dream.run())
        await asyncio.sleep(0.01)  # let task1 acquire the lock

        # Second run should skip immediately
        result2 = await dream.run()
        assert result2 is False

        # Release first run
        barrier.set()
        result1 = await task1
        # First run returns False because no entries (empty history)
        assert result1 is False

    @pytest.mark.asyncio
    async def test_sequential_runs_both_execute(self, dream):
        """Sequential calls should both execute normally."""
        result1 = await dream.run()
        result2 = await dream.run()
        # Both return False (no entries to process)
        assert result1 is False
        assert result2 is False
        # get_last_dream_cursor called twice (once per run)
        assert dream.store.get_last_dream_cursor.call_count == 2

    @pytest.mark.asyncio
    async def test_lock_released_on_error(self, dream):
        """Lock should be released even if _run_inner raises."""
        dream._run_inner = AsyncMock(side_effect=RuntimeError("boom"))

        with pytest.raises(RuntimeError, match="boom"):
            await dream.run()

        # Lock should be released — next run should work
        assert not dream._lock.locked()


# ═══════════════════════════════════════════════════════════════════════
# 3. AgentLoop wiring: Consolidator.on_archive → Dream.run()
# ═══════════════════════════════════════════════════════════════════════

class TestAgentLoopWiring:
    """AgentLoop should wire consolidator.on_archive to schedule dream.run()."""

    def _make_loop(self, tmp_path):
        from nanobot.agent.loop import AgentLoop
        from nanobot.bus.queue import MessageBus

        bus = MessageBus()
        provider = MagicMock()
        provider.get_default_model.return_value = "test-model"
        provider.generation.max_tokens = 4096

        with patch("nanobot.agent.loop.ContextBuilder"), \
             patch("nanobot.agent.loop.SessionManager"), \
             patch("nanobot.agent.loop.SubagentManager") as MockSubMgr:
            MockSubMgr.return_value.cancel_by_session = AsyncMock(return_value=0)
            loop = AgentLoop(bus=bus, provider=provider, workspace=tmp_path)
        return loop

    def test_consolidator_has_on_archive(self, tmp_path):
        loop = self._make_loop(tmp_path)
        assert loop.consolidator._on_archive is not None

    def test_on_archive_is_callable(self, tmp_path):
        loop = self._make_loop(tmp_path)
        assert callable(loop.consolidator._on_archive)

    def test_dream_has_lock(self, tmp_path):
        loop = self._make_loop(tmp_path)
        assert hasattr(loop.dream, '_lock')
        assert isinstance(loop.dream._lock, asyncio.Lock)

    def test_on_archive_calls_schedule_background(self, tmp_path):
        loop = self._make_loop(tmp_path)

        # Mock _schedule_background to capture calls and consume the coroutine
        original_schedule = loop._schedule_background

        captured = []
        def fake_schedule(coro):
            # Consume the coroutine to avoid RuntimeWarning
            captured.append(coro)
            coro.close()

        loop._schedule_background = fake_schedule

        # Fire the callback
        loop.consolidator._on_archive()

        assert len(captured) == 1


# ═══════════════════════════════════════════════════════════════════════
# 4. Consolidator backward compatibility
# ═══════════════════════════════════════════════════════════════════════

class TestConsolidatorBackwardCompat:
    """Existing code that creates Consolidator without on_archive should work."""

    def test_default_on_archive_is_none(self):
        from nanobot.agent.memory import Consolidator

        c = Consolidator(
            store=MagicMock(),
            provider=MagicMock(),
            model="test-model",
            sessions=MagicMock(),
            context_window_tokens=128_000,
            build_messages=MagicMock(return_value=[]),
            get_tool_definitions=MagicMock(return_value=[]),
        )
        assert c._on_archive is None

    @pytest.mark.asyncio
    async def test_fire_on_archive_noop_when_none(self):
        from nanobot.agent.memory import Consolidator

        c = Consolidator(
            store=MagicMock(),
            provider=MagicMock(),
            model="test-model",
            sessions=MagicMock(),
            context_window_tokens=128_000,
            build_messages=MagicMock(return_value=[]),
            get_tool_definitions=MagicMock(return_value=[]),
        )
        # Should not raise
        c._fire_on_archive()


# ═══════════════════════════════════════════════════════════════════════
# 5. Concurrency: multi-round archive & Dream lock interaction
# ═══════════════════════════════════════════════════════════════════════

class TestConcurrencyMultiRoundArchive:
    """When maybe_consolidate_by_tokens loops N rounds, on_archive fires N
    times but Dream's lock ensures only one run executes."""

    @pytest.mark.asyncio
    async def test_multi_round_archive_fires_callback_each_round(self):
        """Each archive() call in the consolidation loop fires on_archive."""
        from nanobot.agent.memory import Consolidator

        store = MagicMock()
        provider = MagicMock()
        provider.chat_with_retry = AsyncMock(
            return_value=LLMResponse(content="summary", tool_calls=[])
        )
        callback = MagicMock()

        c = Consolidator(
            store=store,
            provider=provider,
            model="test-model",
            sessions=MagicMock(),
            context_window_tokens=128_000,
            build_messages=MagicMock(return_value=[]),
            get_tool_definitions=MagicMock(return_value=[]),
            on_archive=callback,
        )

        # Simulate 3 rounds of archive (as the consolidation loop would do)
        for _ in range(3):
            await c.archive([{"role": "user", "content": "msg"}])

        assert callback.call_count == 3

    @pytest.mark.asyncio
    async def test_multi_round_archive_dream_lock_prevents_overlap(self):
        """Multiple on_archive callbacks schedule Dream, but only one runs."""
        from nanobot.agent.memory import Dream

        store = MagicMock()
        store.get_last_dream_cursor.return_value = 0
        store.read_unprocessed_history.return_value = []

        dream = Dream(store=store, provider=MagicMock(), model="test-model")

        # Slow down _run_inner so we can observe lock contention
        barrier = asyncio.Event()
        call_count = 0
        original_run_inner = dream._run_inner

        async def counting_run_inner():
            nonlocal call_count
            call_count += 1
            await barrier.wait()
            return await original_run_inner()

        dream._run_inner = counting_run_inner

        # Simulate 5 rapid on_archive triggers (as if consolidation loop
        # called archive() 5 times)
        tasks = [asyncio.create_task(dream.run()) for _ in range(5)]
        await asyncio.sleep(0.02)  # let first task acquire lock

        # Release the barrier so the first run can finish
        barrier.set()
        results = await asyncio.gather(*tasks)

        # Exactly 1 task actually ran _run_inner, the rest were skipped
        assert call_count == 1
        assert results.count(False) == 5  # all return False (no entries)

    @pytest.mark.asyncio
    async def test_dream_processes_all_entries_written_before_read(self):
        """Dream should see all history entries that were written before it
        reads, even if they came from multiple archive() calls."""
        from nanobot.agent.memory import Dream

        store = MagicMock()
        store.get_last_dream_cursor.return_value = 0
        # Simulate 3 entries already written by the time Dream reads
        store.read_unprocessed_history.return_value = [
            {"cursor": 1, "timestamp": "2026-01-01 00:00", "content": "chunk1"},
            {"cursor": 2, "timestamp": "2026-01-01 00:01", "content": "chunk2"},
            {"cursor": 3, "timestamp": "2026-01-01 00:02", "content": "chunk3"},
        ]

        provider = MagicMock()
        provider.chat_with_retry = AsyncMock(
            return_value=LLMResponse(content="analysis", tool_calls=[])
        )

        dream = Dream(store=store, provider=provider, model="test-model")

        # Mock _runner.run to avoid full AgentRunner execution
        mock_result = MagicMock()
        mock_result.stop_reason = "completed"
        mock_result.tool_events = []
        dream._runner.run = AsyncMock(return_value=mock_result)

        # Mock git
        store.git.is_initialized.return_value = False

        result = await dream.run()

        assert result is True
        # Dream should advance cursor to the last entry
        store.set_last_dream_cursor.assert_called_once_with(3)
        store.compact_history.assert_called_once()


# ═══════════════════════════════════════════════════════════════════════
# 6. Concurrency: parallel consolidation on different sessions
# ═══════════════════════════════════════════════════════════════════════

class TestConcurrencyParallelSessions:
    """Two sessions consolidating in parallel should both fire on_archive,
    and Dream lock should serialize their Dream triggers."""

    @pytest.mark.asyncio
    async def test_parallel_sessions_both_fire_callback(self):
        """Concurrent archive() from different sessions both fire on_archive."""
        from nanobot.agent.memory import Consolidator

        store = MagicMock()
        provider = MagicMock()
        # Make archive take a little time to simulate real LLM call
        async def slow_chat(**kwargs):
            await asyncio.sleep(0.01)
            return LLMResponse(content="summary", tool_calls=[])

        provider.chat_with_retry = slow_chat
        callback = MagicMock()

        c = Consolidator(
            store=store,
            provider=provider,
            model="test-model",
            sessions=MagicMock(),
            context_window_tokens=128_000,
            build_messages=MagicMock(return_value=[]),
            get_tool_definitions=MagicMock(return_value=[]),
            on_archive=callback,
        )

        # Two sessions archive concurrently
        msgs1 = [{"role": "user", "content": "session1 msg"}]
        msgs2 = [{"role": "user", "content": "session2 msg"}]

        results = await asyncio.gather(
            c.archive(msgs1),
            c.archive(msgs2),
        )

        assert results[0] == "summary"
        assert results[1] == "summary"
        assert callback.call_count == 2

    @pytest.mark.asyncio
    async def test_parallel_sessions_dream_serialized(self):
        """When two sessions trigger Dream concurrently, only one executes."""
        from nanobot.agent.memory import Dream

        store = MagicMock()
        store.get_last_dream_cursor.return_value = 0
        store.read_unprocessed_history.return_value = []

        dream = Dream(store=store, provider=MagicMock(), model="test-model")

        run_inner_count = 0
        original = dream._run_inner

        async def counting_inner():
            nonlocal run_inner_count
            run_inner_count += 1
            await asyncio.sleep(0.02)  # simulate work
            return await original()

        dream._run_inner = counting_inner

        # Two sessions trigger Dream at the same time
        task1 = asyncio.create_task(dream.run())
        await asyncio.sleep(0.005)  # let task1 acquire lock
        task2 = asyncio.create_task(dream.run())

        r1, r2 = await asyncio.gather(task1, task2)

        # task1 ran _run_inner, task2 was skipped
        assert run_inner_count == 1
        assert r2 is False


# ═══════════════════════════════════════════════════════════════════════
# 7. Concurrency: Dream reads while Consolidator writes
# ═══════════════════════════════════════════════════════════════════════

class TestConcurrencyDreamReadsWhileConsolidatorWrites:
    """Simulate the race where Consolidator writes more entries to
    history.jsonl while Dream is already processing a batch."""

    @pytest.mark.asyncio
    async def test_dream_snapshot_isolation(self):
        """Dream reads entries once at the start. New entries written by
        Consolidator during Dream's run are NOT included in the current
        batch — they'll be picked up on the next Dream run."""
        from nanobot.agent.memory import Dream

        store = MagicMock()
        store.get_last_dream_cursor.return_value = 0
        store.git.is_initialized.return_value = False

        # First call returns 2 entries; simulate Consolidator writing more
        # during Dream's Phase 1 LLM call
        initial_entries = [
            {"cursor": 1, "timestamp": "2026-01-01 00:00", "content": "entry1"},
            {"cursor": 2, "timestamp": "2026-01-01 00:01", "content": "entry2"},
        ]
        store.read_unprocessed_history.return_value = initial_entries

        provider = MagicMock()

        # During Phase 1 LLM call, simulate Consolidator appending entry3
        entries_after_write = initial_entries + [
            {"cursor": 3, "timestamp": "2026-01-01 00:02", "content": "entry3"},
        ]

        async def phase1_chat(**kwargs):
            # Simulate: Consolidator writes entry3 while Dream is in Phase 1
            store.read_unprocessed_history.return_value = entries_after_write
            return LLMResponse(content="analysis of entry1 and entry2", tool_calls=[])

        provider.chat_with_retry = phase1_chat

        dream = Dream(store=store, provider=provider, model="test-model")

        mock_result = MagicMock()
        mock_result.stop_reason = "completed"
        mock_result.tool_events = []
        dream._runner.run = AsyncMock(return_value=mock_result)

        result = await dream.run()

        assert result is True
        # Dream should advance cursor to 2 (the last entry in its batch),
        # NOT to 3 (which was written after Dream started)
        store.set_last_dream_cursor.assert_called_once_with(2)

    @pytest.mark.asyncio
    async def test_late_entries_picked_up_on_next_run(self):
        """Entries written during a Dream run are processed on the next run."""
        from nanobot.agent.memory import Dream

        store = MagicMock()
        store.git.is_initialized.return_value = False

        provider = MagicMock()
        provider.chat_with_retry = AsyncMock(
            return_value=LLMResponse(content="analysis", tool_calls=[])
        )

        dream = Dream(store=store, provider=provider, model="test-model")

        mock_result = MagicMock()
        mock_result.stop_reason = "completed"
        mock_result.tool_events = []
        dream._runner.run = AsyncMock(return_value=mock_result)

        # Run 1: cursor=0, 2 entries
        store.get_last_dream_cursor.return_value = 0
        store.read_unprocessed_history.return_value = [
            {"cursor": 1, "timestamp": "2026-01-01 00:00", "content": "entry1"},
            {"cursor": 2, "timestamp": "2026-01-01 00:01", "content": "entry2"},
        ]

        r1 = await dream.run()
        assert r1 is True
        store.set_last_dream_cursor.assert_called_with(2)

        # Run 2: cursor=2, entry3 now visible
        store.get_last_dream_cursor.return_value = 2
        store.read_unprocessed_history.return_value = [
            {"cursor": 3, "timestamp": "2026-01-01 00:02", "content": "entry3"},
        ]

        r2 = await dream.run()
        assert r2 is True
        store.set_last_dream_cursor.assert_called_with(3)


# ═══════════════════════════════════════════════════════════════════════
# 8. Background task exception safety
# ═══════════════════════════════════════════════════════════════════════

class TestBackgroundDreamExceptionSafety:
    """Dream exceptions in background tasks should not crash the loop."""

    @pytest.mark.asyncio
    async def test_dream_phase1_failure_returns_false_and_releases_lock(self):
        """If Dream Phase 1 LLM call fails, _run_inner catches the exception
        internally and returns False. The lock is released so subsequent
        runs can proceed."""
        from nanobot.agent.memory import Dream

        store = MagicMock()
        store.get_last_dream_cursor.return_value = 0
        store.read_unprocessed_history.return_value = [
            {"cursor": 1, "timestamp": "2026-01-01", "content": "x"},
        ]

        provider = MagicMock()
        provider.chat_with_retry = AsyncMock(
            side_effect=RuntimeError("Phase 1 exploded")
        )

        dream = Dream(store=store, provider=provider, model="test-model")

        # Simulate _schedule_background: fire-and-forget task
        task = asyncio.create_task(dream.run())
        result = await task

        # Phase 1 failure is caught internally → returns False, no exception
        assert result is False
        # Lock must be released so next run can proceed
        assert not dream._lock.locked()

    @pytest.mark.asyncio
    async def test_dream_recovers_after_phase1_failure(self):
        """After a failed Phase 1, the next Dream run works normally."""
        from nanobot.agent.memory import Dream

        store = MagicMock()
        store.get_last_dream_cursor.return_value = 0
        store.git.is_initialized.return_value = False

        provider = MagicMock()

        dream = Dream(store=store, provider=provider, model="test-model")

        # Run 1: Phase 1 fails (caught internally)
        store.read_unprocessed_history.return_value = [
            {"cursor": 1, "timestamp": "2026-01-01", "content": "x"},
        ]
        provider.chat_with_retry = AsyncMock(
            side_effect=RuntimeError("temporary failure")
        )

        result1 = await dream.run()
        assert result1 is False
        assert not dream._lock.locked()

        # Run 2: succeeds
        provider.chat_with_retry = AsyncMock(
            return_value=LLMResponse(content="analysis", tool_calls=[])
        )
        store.read_unprocessed_history.return_value = [
            {"cursor": 1, "timestamp": "2026-01-01", "content": "x"},
        ]

        mock_result = MagicMock()
        mock_result.stop_reason = "completed"
        mock_result.tool_events = []
        dream._runner.run = AsyncMock(return_value=mock_result)

        result2 = await dream.run()
        assert result2 is True

    @pytest.mark.asyncio
    async def test_dream_uncaught_exception_still_releases_lock(self):
        """If _run_inner raises an unexpected exception (not caught by
        Dream's internal try/except), the async-with lock is still released."""
        from nanobot.agent.memory import Dream

        store = MagicMock()
        provider = MagicMock()
        dream = Dream(store=store, provider=provider, model="test-model")

        # Force an unexpected error before any try/except in _run_inner
        async def exploding_inner():
            raise SystemError("totally unexpected")

        dream._run_inner = exploding_inner

        with pytest.raises(SystemError, match="totally unexpected"):
            await dream.run()

        # Lock released by async-with even on unexpected exception
        assert not dream._lock.locked()

    @pytest.mark.asyncio
    async def test_on_archive_exception_does_not_block_consolidator(self):
        """Even if the on_archive callback raises (e.g., _schedule_background
        fails), the Consolidator's archive() still returns normally."""
        from nanobot.agent.memory import Consolidator

        store = MagicMock()
        provider = MagicMock()
        provider.chat_with_retry = AsyncMock(
            return_value=LLMResponse(content="summary", tool_calls=[])
        )

        def exploding_callback():
            raise TypeError("_schedule_background broke")

        c = Consolidator(
            store=store,
            provider=provider,
            model="test-model",
            sessions=MagicMock(),
            context_window_tokens=128_000,
            build_messages=MagicMock(return_value=[]),
            get_tool_definitions=MagicMock(return_value=[]),
            on_archive=exploding_callback,
        )

        # archive() should succeed despite callback explosion
        result = await c.archive([{"role": "user", "content": "hello"}])
        assert result == "summary"
        store.append_history.assert_called_once()
