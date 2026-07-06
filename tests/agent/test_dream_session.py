"""Tests for Dream session key generation and rotation."""
from datetime import datetime, timedelta
from unittest.mock import patch

from nanobot.agent.memory import MemoryStore


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
        import os
        import time

        sessions_dir = tmp_path / "sessions"
        sessions_dir.mkdir()

        base_time = time.time() - 100

        for i in range(15):
            key = f"dream:20260528-{100000 + i:06d}"
            safe_key = key.replace(":", "_")
            path = sessions_dir / f"{safe_key}.jsonl"
            path.write_text(
                f'{{"_type": "metadata", "key": "{key}", '
                f'"created_at": "2026-05-28T10:00:{i:02d}", '
                f'"updated_at": "2026-05-28T10:00:{i:02d}"}}\n',
                encoding="utf-8",
            )
            os.utime(path, (base_time + i, base_time + i))

        normal_path = sessions_dir / "telegram_123.jsonl"
        normal_path.write_text('{"_type": "metadata"}\n', encoding="utf-8")

        MemoryStore.prune_dream_sessions(sessions_dir, keep=10)

        dream_files = sorted(sessions_dir.glob("dream_*.jsonl"))
        assert len(dream_files) == 10
        remaining_keys = [f.stem for f in dream_files]
        assert "dream_20260528-100000" not in remaining_keys
        assert "dream_20260528-100014" in remaining_keys
        assert normal_path.exists()

    def test_noop_when_under_limit(self, tmp_path):
        sessions_dir = tmp_path / "sessions"
        sessions_dir.mkdir()
        for i in range(3):
            key = f"dream:20260528-{100000 + i:06d}"
            safe_key = key.replace(":", "_")
            (sessions_dir / f"{safe_key}.jsonl").write_text("{}", encoding="utf-8")

        MemoryStore.prune_dream_sessions(sessions_dir, keep=10)
        assert len(list(sessions_dir.glob("dream_*.jsonl"))) == 3

    def test_empty_dir_noop(self, tmp_path):
        sessions_dir = tmp_path / "sessions"
        sessions_dir.mkdir()
        MemoryStore.prune_dream_sessions(sessions_dir, keep=10)
        assert list(sessions_dir.iterdir()) == []
