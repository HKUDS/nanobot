"""Portable session exports; exported files are not runtime state."""

from __future__ import annotations

import json
from pathlib import Path

from nanobot.session.location import SessionLocation
from nanobot.session.sqlite_store import SqliteSessionStore
from nanobot.utils.helpers import atomic_write_lines


def export_sessions(store: SqliteSessionStore, destination: Path) -> int:
    destination.mkdir(parents=True, exist_ok=True)
    count = 0
    with store.transaction(write=False):
        for row in store.list_sessions():
            session = store.load(row["key"])
            assert session is not None
            records = [{"_type": "metadata", "key": session.key,
                        "created_at": session.created_at.isoformat(),
                        "updated_at": session.updated_at.isoformat(),
                        "metadata": session.metadata, "last_archived": session.last_archived}]
            if session.provider_state is not None:
                records.append({"_type": "provider_state", "state": session.provider_state.to_private_record()})
            records.extend(session.messages)
            atomic_write_lines(destination / f"{SessionLocation.storage_key(session.key)}.jsonl",
                               [json.dumps(record, ensure_ascii=False) for record in records], fsync=True)
            count += 1
    return count
