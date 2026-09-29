"""Portable session exports; exported files are not runtime state."""

from __future__ import annotations

import json
import os
from contextlib import suppress
from pathlib import Path

from filelock import FileLock

from nanobot.session.location import SessionLocation
from nanobot.session.sqlite_store import SqliteSessionStore
from nanobot.utils.helpers import atomic_write_lines

_EXPORT_LOCK = ".nanobot-export.lock"


def export_sessions(store: SqliteSessionStore, destination: Path) -> int:
    """Synchronize one complete JSONL snapshot of the authoritative store."""
    if destination.is_symlink():
        raise ValueError(f"session export destination must not be a symlink: {destination}")
    destination.mkdir(mode=0o700, parents=True, exist_ok=True)
    with suppress(OSError):
        os.chmod(destination, 0o700)

    with FileLock(destination / _EXPORT_LOCK, timeout=30):
        sessions = store.snapshot_sessions()
        exported: dict[str, list[str]] = {}
        for session in sessions:
            filename = f"{SessionLocation.storage_key(session.key)}.jsonl"
            records = [{
                "_type": "metadata",
                "key": session.key,
                "created_at": session.created_at.isoformat(),
                "updated_at": session.updated_at.isoformat(),
                "metadata": session.metadata,
                "last_archived": session.last_archived,
            }]
            if session.provider_state is not None:
                records.append({
                    "_type": "provider_state",
                    "state": session.provider_state.to_private_record(),
                })
            records.extend(session.messages)
            exported[filename] = [
                json.dumps(record, ensure_ascii=False) for record in records
            ]

        # Publish every current file before pruning stale files. A successful
        # invocation leaves exactly the migration-consumable snapshot represented
        # by SQLite, so deleted conversations cannot be restored from an old export.
        for filename, records in exported.items():
            path = destination / filename
            atomic_write_lines(path, records, fsync=True)
            with suppress(OSError):
                os.chmod(path, 0o600)

        expected = set(exported)
        for path in destination.glob("*.jsonl"):
            if path.name not in expected:
                path.unlink()
        # Checkpoint state is embedded in exported metadata. Legacy sidecars in
        # the destination would otherwise override the current snapshot on import.
        for path in destination.glob("*.checkpoint.json"):
            path.unlink()

    return len(exported)
