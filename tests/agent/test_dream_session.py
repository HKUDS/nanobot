"""Tests for Dream session key generation and rotation."""

from datetime import datetime, timedelta
from unittest.mock import patch

from nanobot.agent.memory import MemoryStore
from nanobot.session.manager import SessionManager


class TestDreamSessionKey:
    def test_contains_timestamp(self):
        key = MemoryStore.dream_session_key()
        assert key.startswith("dream:")
        ts_part = key.split(":", 1)[1]
        datetime.strptime(ts_part, "%Y%m%d-%H%M%S")

    def test_unique_across_calls(self):
        now = datetime(2026, 5, 28, 10, 0, 0)
        with patch("nanobot.agent.memory.datetime") as mock_dt:
            mock_dt.now.side_effect = [now, now + timedelta(seconds=1)]
            k1 = MemoryStore.dream_session_key()
            k2 = MemoryStore.dream_session_key()

        assert k1 != k2


class TestPruneDreamSessions:
    async def test_keeps_n_most_recent(self, tmp_path):
        manager = SessionManager(tmp_path / "workspace", sessions_root=tmp_path / "runtime")
        keys = [f"dream:20260528-{100000 + i:06d}" for i in range(15)]
        for i, key in enumerate(keys):
            session = manager.get_or_create(key)
            session.updated_at = datetime(2026, 5, 28, 10, 0, i)
            manager.save(session)
        manager.save(manager.get_or_create("telegram:normal"))

        assert await manager.state.prune_dream_sessions(keep=10) == 5
        await manager.state.aclose()

        assert [manager.read_session_snapshot(key) is not None for key in keys] == [False] * 5 + [True] * 10
        assert manager.read_session_snapshot("telegram:normal") is not None

    async def test_leaves_legacy_backup_untouched(self, tmp_path):
        manager = SessionManager(tmp_path / "workspace", sessions_root=tmp_path / "runtime")
        path = manager.sessions_dir / "dream_20260713-095959.jsonl"
        path.write_text('legacy backup', encoding="utf-8")
        await manager.state.prune_dream_sessions(keep=0)
        await manager.state.aclose()
        assert path.read_text(encoding="utf-8") == 'legacy backup'

    async def test_noop_when_under_limit(self, tmp_path):
        manager = SessionManager(tmp_path / "workspace", sessions_root=tmp_path / "runtime")
        for i in range(3):
            manager.save(manager.get_or_create(f"dream:20260528-{100000 + i:06d}"))
        assert await manager.state.prune_dream_sessions(keep=10) == 0
        await manager.state.aclose()
        assert len(manager.list_sessions()) == 3

    async def test_empty_store_noop(self, tmp_path):
        manager = SessionManager(tmp_path / "workspace", sessions_root=tmp_path / "runtime")
        assert await manager.state.prune_dream_sessions(keep=10) == 0
        await manager.state.aclose()
        assert manager.list_sessions() == []
