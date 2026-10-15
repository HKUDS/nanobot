"""Idle compact must not pay for WebUI preview extraction on every scan (#6192)."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

from nanobot.agent.autocompact import AutoCompact
from nanobot.session.manager import JsonlSessionStore, Session, SessionManager


def _write_session(path: Path, key: str, updated_at: datetime, *, body_lines: int = 200) -> None:
    """Persist a session whose transcript dwarfs the metadata line."""
    meta = {
        "_type": "metadata",
        "key": key,
        "created_at": updated_at.isoformat(),
        "updated_at": updated_at.isoformat(),
        "metadata": {"title": key},
    }
    lines = [json.dumps(meta)]
    # Large assistant payloads: a full list_sessions preview walks these lines.
    blob = "x" * 4000
    for i in range(body_lines):
        lines.append(json.dumps({"role": "assistant", "content": f"{blob}-{i}"}))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _store_with_session(tmp_path: Path, *, body_lines: int = 200):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    sessions_root = tmp_path / "sessions-root"
    sessions_root.mkdir()
    store = JsonlSessionStore(workspace, sessions_root=sessions_root)
    key = "cli:heavy"
    updated = datetime.now() - timedelta(hours=2)
    path = store.sessions_dir / f"{JsonlSessionStore.storage_key(key)}.jsonl"
    _write_session(path, key, updated, body_lines=body_lines)
    return store, key, updated, path


def test_list_session_activity_reads_only_the_metadata_line(tmp_path, monkeypatch):
    store, key, updated, path = _store_with_session(tmp_path, body_lines=300)

    reads: list[int] = []
    import builtins
    real_open = builtins.open
    target = str(path.resolve())

    def counting_open(file, *args, **kwargs):
        handle = real_open(file, *args, **kwargs)
        name = str(Path(file).resolve()) if not hasattr(file, "read") else None
        if name == target:
            wrapped_readline = handle.readline

            def readline(*a, **k):
                line = wrapped_readline(*a, **k)
                if line:
                    reads.append(1)
                return line

            handle.readline = readline  # type: ignore[method-assign]
        return handle

    monkeypatch.setattr(builtins, "open", counting_open)

    rows = store.list_session_activity()

    assert rows == [{"key": key, "updated_at": updated.isoformat()}]
    assert sum(reads) == 1, f"activity listing must stop after metadata; read {sum(reads)} lines"


def test_list_sessions_still_scans_preview_lines(tmp_path):
    store, key, _updated, _path = _store_with_session(tmp_path, body_lines=50)
    rows = store.list_sessions()
    assert len(rows) == 1 and rows[0]["key"] == key
    assert rows[0]["preview"]  # full listing still builds a preview from the body


def test_check_expired_uses_activity_listing_not_full_preview():
    sessions = MagicMock()
    old = datetime.now() - timedelta(hours=2)
    sessions.list_session_activity.return_value = [
        {"key": "cli:idle", "updated_at": old.isoformat()},
    ]

    def boom(*_a, **_k):
        raise AssertionError("idle compact must not call list_sessions (preview scan)")

    sessions.list_sessions.side_effect = boom
    session = Session(key="cli:idle", messages=[{"role": "user", "content": "hi"}])
    session.updated_at = old
    sessions.get_or_create.return_value = session

    consolidator = MagicMock()
    ac = AutoCompact(
        sessions=sessions,
        consolidator=consolidator,
        session_ttl_minutes=15,
        session_lock=lambda _key: asyncio.Lock(),
    )
    scheduled: list = []

    def schedule(pending):
        scheduled.append(pending)
        pending.close()

    ac.check_expired(schedule, lambda _s: MagicMock())

    sessions.list_session_activity.assert_called_once_with()
    assert len(scheduled) == 1


def test_session_manager_exposes_activity_listing(tmp_path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    sessions_root = tmp_path / "sessions-root"
    sessions_root.mkdir()
    manager = SessionManager(workspace, sessions_root=sessions_root)
    key = "cli:heavy"
    updated = datetime.now() - timedelta(hours=2)
    path = manager.sessions_dir / f"{JsonlSessionStore.storage_key(key)}.jsonl"
    _write_session(path, key, updated, body_lines=20)
    rows = manager.list_session_activity()
    assert rows == [{"key": key, "updated_at": updated.isoformat()}]
