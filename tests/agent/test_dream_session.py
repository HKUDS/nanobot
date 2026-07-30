"""Tests for Dream session key generation and rotation."""

from datetime import datetime, timedelta
from unittest.mock import patch

from nanobot.agent.memory import MemoryStore
from nanobot.session.manager import Session, SessionManager


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
    def test_keeps_n_most_recent(self, tmp_path):
        manager = SessionManager(tmp_path)
        for i in range(15):
            key = f"dream:20260528-{100000 + i:06d}"
            manager.save(
                Session(
                    key=key,
                    created_at=datetime(2026, 5, 28, 10, 0, i),
                    updated_at=datetime(2026, 5, 28, 10, 0, i),
                )
            )
        manager.save(Session(key="telegram:123"))

        MemoryStore.prune_dream_sessions(manager, keep=10)

        keys = {row["key"] for row in manager.list_sessions()}
        assert keys == {
            "telegram:123",
            *(f"dream:20260528-{100000 + i:06d}" for i in range(5, 15)),
        }

    def test_ignores_non_dream_session_keys(self, tmp_path):
        manager = SessionManager(tmp_path)
        for i in range(2):
            key = f"dream:20260713-{100000 + i:06d}"
            manager.save(
                Session(
                    key=key,
                    updated_at=datetime(2026, 7, 13, 10, 0, i),
                )
            )
        manager.save(Session(key="dream_20260713-095959"))

        MemoryStore.prune_dream_sessions(manager, keep=1)

        assert manager.read_session_file("dream:20260713-100000") is None
        assert manager.read_session_file("dream:20260713-100001") is not None
        assert manager.read_session_file("dream_20260713-095959") is not None

    def test_noop_when_under_limit(self, tmp_path):
        manager = SessionManager(tmp_path)
        for i in range(3):
            key = f"dream:20260528-{100000 + i:06d}"
            manager.save(Session(key=key))

        MemoryStore.prune_dream_sessions(manager, keep=10)
        assert len(manager.list_sessions()) == 3

    def test_empty_dir_noop(self, tmp_path):
        manager = SessionManager(tmp_path)
        MemoryStore.prune_dream_sessions(manager, keep=10)
        assert manager.list_sessions() == []
