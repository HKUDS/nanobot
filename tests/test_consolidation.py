"""Tests for nanobot.agent.consolidation.ConsolidationOrchestrator."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from nanobot.agent.consolidation import ConsolidationOrchestrator

# ---------------------------------------------------------------------------
# Unit tests
# ---------------------------------------------------------------------------


class TestConsolidationLocks:
    def test_get_lock_creates_new(self):
        store = MagicMock()
        orch = ConsolidationOrchestrator(store)
        lock = orch.get_lock("session-1")
        assert lock is not None
        # Same session returns same lock
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
            assert "session-1" in orch._locks  # still held
        finally:
            lock.release()


class TestConsolidateDelegate:
    async def test_delegates_to_memory_store(self):
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


class TestFallbackArchive:
    def test_empty_snapshot(self):
        store = MagicMock()
        orch = ConsolidationOrchestrator(store)
        assert orch.fallback_archive_snapshot([]) is True

    def test_basic_snapshot(self):
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

    def test_snapshot_with_empty_content(self):
        store = MagicMock()
        orch = ConsolidationOrchestrator(store)
        snapshot = [
            {"role": "user", "content": ""},
            {"role": "user", "content": None},
            {"role": "user", "content": "actual content"},
        ]
        result = orch.fallback_archive_snapshot(snapshot)
        assert result is True
        entry = store.persistence.append_text.call_args[0][1]
        assert "actual content" in entry

    def test_exception_returns_false(self):
        store = MagicMock()
        store.persistence.append_text.side_effect = RuntimeError("disk full")
        orch = ConsolidationOrchestrator(store)
        snapshot = [{"role": "user", "content": "Hello"}]
        result = orch.fallback_archive_snapshot(snapshot)
        assert result is False
