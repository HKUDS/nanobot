"""Tests for ConsolidationOrchestrator (rewritten for TaskGroup API).

The old API (get_lock, prune_lock, consolidate, fallback_archive_snapshot)
was removed in the TaskGroup rewrite. These tests cover the new API.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from nanobot.agent.consolidation import ConsolidationOrchestrator


def _orch(archive_fn=None):
    memory = MagicMock()
    memory.consolidate = AsyncMock(return_value=True)
    return ConsolidationOrchestrator(
        memory=memory,
        archive_fn=archive_fn or MagicMock(),
        max_concurrent=2,
        memory_window=50,
        enable_contradiction_check=True,
    ), memory


class TestInProgressDeduplication:
    async def test_second_submit_for_same_session_is_noop(self):
        orch, memory = _orch()
        session = MagicMock()
        session.messages = []
        async with orch:
            orch.submit("s", session, MagicMock(), "m")
            orch.submit("s", session, MagicMock(), "m")
        assert memory.consolidate.call_count == 1


class TestSubmitAndConsolidateAndWait:
    async def test_submit_runs_in_background(self):
        orch, memory = _orch()
        session = MagicMock()
        session.messages = []
        async with orch:
            orch.submit("s", session, MagicMock(), "m")
        memory.consolidate.assert_called_once()

    async def test_consolidate_and_wait_is_awaitable(self):
        orch, memory = _orch()
        session = MagicMock()
        session.messages = []
        async with orch:
            result = await orch.consolidate_and_wait("s", session, MagicMock(), "m")
        assert result is True


class TestArchiveFnOnFailure:
    async def test_archive_fn_called_on_consolidate_failure(self):
        archive = MagicMock()
        orch, memory = _orch(archive_fn=archive)
        memory.consolidate = AsyncMock(side_effect=RuntimeError("boom"))
        session = MagicMock()
        session.messages = [{"role": "user", "content": "hi"}]
        async with orch:
            orch.submit("s", session, MagicMock(), "m")
        archive.assert_called_once()


class TestBackwardCompatAPI:
    """Tests for the backward-compatible shim methods."""

    def test_get_lock_creates_new(self):
        store = MagicMock()
        orch = ConsolidationOrchestrator(store)
        lock = orch.get_lock("session-1")
        assert lock is not None
        assert orch.get_lock("session-1") is lock

    def test_get_lock_different_sessions(self):
        store = MagicMock()
        orch = ConsolidationOrchestrator(store)
        lock1 = orch.get_lock("session-1")
        lock2 = orch.get_lock("session-2")
        assert lock1 is not lock2

    def test_prune_lock_removes_unlocked(self):
        store = MagicMock()
        orch = ConsolidationOrchestrator(store)
        lock = orch.get_lock("session-1")
        orch.prune_lock("session-1", lock)
        assert "session-1" not in orch._locks

    async def test_prune_lock_keeps_locked(self):
        store = MagicMock()
        orch = ConsolidationOrchestrator(store)
        lock = orch.get_lock("session-1")
        await lock.acquire()
        try:
            orch.prune_lock("session-1", lock)
            assert "session-1" in orch._locks
        finally:
            lock.release()

    async def test_consolidate_delegates_to_memory_store(self):
        store = MagicMock()
        store.consolidate = AsyncMock(return_value=True)
        orch = ConsolidationOrchestrator(store)

        session = MagicMock()
        provider = MagicMock()
        result = await orch.consolidate(
            session,
            provider,
            "gpt-4",
            memory_window=10,
            enable_contradiction_check=False,
        )
        assert result is True
        store.consolidate.assert_awaited_once()

    def test_fallback_archive_empty_snapshot(self):
        store = MagicMock()
        orch = ConsolidationOrchestrator(store)
        assert orch.fallback_archive_snapshot([]) is True

    def test_fallback_archive_basic_snapshot(self):
        store = MagicMock()
        orch = ConsolidationOrchestrator(store)
        snapshot = [
            {
                "role": "user",
                "content": "Hello",
                "timestamp": "2026-01-01T00:00:00",
            },
            {
                "role": "assistant",
                "content": "Hi there!",
                "timestamp": "2026-01-01T00:01:00",
                "tools_used": ["web_search"],
            },
        ]
        result = orch.fallback_archive_snapshot(snapshot)
        assert result is True
        store.persistence.append_text.assert_called_once()
        entry = store.persistence.append_text.call_args[0][1]
        assert "USER: Hello" in entry
        assert "[tools: web_search]" in entry
        assert "ASSISTANT" in entry

    def test_fallback_archive_exception_returns_false(self):
        store = MagicMock()
        store.persistence.append_text.side_effect = RuntimeError("disk full")
        orch = ConsolidationOrchestrator(store)
        snapshot = [{"role": "user", "content": "Hello"}]
        result = orch.fallback_archive_snapshot(snapshot)
        assert result is False
