# nanobot/agent/memory/migration.py
# NOTE: Not exported from __init__.py during transition.
# Will be added to package exports in Task 10.
"""One-time migration from file-based storage to unified SQLite.

Converts events.jsonl, profile.json, HISTORY.md, and MEMORY.md into
memory.db. Renames old files to .bak. Runs automatically on first
MemoryStore construction when memory.db does not exist.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from .unified_db import UnifiedMemoryDB

if TYPE_CHECKING:
    from .embedder import Embedder

__all__ = ["migrate_to_sqlite"]

_PINNED_START = "<!-- user-pinned -->"
_PINNED_END = "<!-- end-user-pinned -->"


def migrate_to_sqlite(
    memory_dir: Path,
    *,
    dims: int,
    embedder: Embedder | None,
) -> UnifiedMemoryDB:
    """Open or create memory.db, migrating old files if needed.

    If memory.db already exists, returns it directly (no migration).
    If old files exist but memory.db does not, migrates data and
    renames old files to .bak.
    """
    db_path = memory_dir / "memory.db"

    if db_path.exists():
        return UnifiedMemoryDB(db_path, dims=dims)

    db = UnifiedMemoryDB(db_path, dims=dims)

    old_files_exist = any(
        (memory_dir / f).exists()
        for f in ("events.jsonl", "profile.json", "HISTORY.md", "MEMORY.md")
    )

    if not old_files_exist:
        return db

    logger.info("Migrating file-based memory to SQLite: {}", memory_dir)

    # 1. Events
    events_file = memory_dir / "events.jsonl"
    if events_file.exists():
        _migrate_events(db, events_file, embedder)

    # 2. Profile
    profile_file = memory_dir / "profile.json"
    if profile_file.exists():
        _migrate_profile(db, profile_file)

    # 3. History
    history_file = memory_dir / "HISTORY.md"
    if history_file.exists():
        _migrate_history(db, history_file)

    # 4. MEMORY.md → snapshots
    memory_file = memory_dir / "MEMORY.md"
    if memory_file.exists():
        _migrate_memory_md(db, memory_file)

    # 5. Rename old files
    for name in ("events.jsonl", "profile.json", "HISTORY.md", "MEMORY.md"):
        src = memory_dir / name
        if src.exists():
            dst = src.with_suffix(src.suffix + ".bak")
            if dst.exists():
                logger.warning("Backup {} already exists, skipping rename", dst.name)
            else:
                src.rename(dst)

    logger.info("Migration complete")
    return db


def _migrate_events(
    db: UnifiedMemoryDB,
    events_file: Path,
    embedder: Embedder | None,
) -> None:
    """Read events.jsonl and insert into the events table."""
    with open(events_file) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                event: dict[str, Any] = json.loads(line)
            except json.JSONDecodeError:
                logger.warning("Skipping malformed event line")
                continue
            # Ensure required fields
            if not event.get("id") or not event.get("summary"):
                continue
            event.setdefault("type", "fact")
            event.setdefault("timestamp", event.get("created_at", ""))
            event.setdefault("created_at", event.get("timestamp", ""))
            event.setdefault("status", "active")
            # Serialize metadata if it's a dict
            if isinstance(event.get("metadata"), dict):
                event["metadata"] = json.dumps(event["metadata"])
            db.insert_event(event, embedding=None)

    # Embedding backfill is NOT done during migration. Events are inserted
    # without vectors. The first maintenance.reindex() call (which runs at
    # startup via ensure_health()) will batch-embed all events using the
    # embedder. This avoids async complexity in the synchronous migration path.
    if embedder is None:
        logger.warning(
            "No embedder available during migration — events inserted without "
            "vectors. Run maintenance.reindex() to backfill embeddings."
        )
    else:
        logger.info(
            "Events migrated without embeddings — reindex will backfill vectors on next startup."
        )


def _migrate_profile(db: UnifiedMemoryDB, profile_file: Path) -> None:
    """Read profile.json and insert as a single profile row."""
    try:
        data = json.loads(profile_file.read_text())
        if isinstance(data, dict):
            db.write_profile("profile", data)
    except (json.JSONDecodeError, OSError):
        logger.warning("Failed to read profile.json — skipping")


def _migrate_history(db: UnifiedMemoryDB, history_file: Path) -> None:
    """Read HISTORY.md and insert each non-empty block as a history entry."""
    try:
        text = history_file.read_text()
    except OSError:
        logger.warning("Failed to read {} — skipping", history_file.name)
        return
    # Split on double newlines (each block is one entry)
    blocks = [b.strip() for b in text.split("\n\n") if b.strip()]
    for block in blocks:
        db.append_history(block)


def _migrate_memory_md(db: UnifiedMemoryDB, memory_file: Path) -> None:
    """Read MEMORY.md, extract user-pinned section, store both in snapshots."""
    try:
        text = memory_file.read_text()
    except OSError:
        logger.warning("Failed to read {} — skipping", memory_file.name)
        return

    # Extract user-pinned section if present
    pinned = ""
    start = text.find(_PINNED_START)
    end = text.find(_PINNED_END)
    if start != -1 and end != -1 and end > start:
        pinned = text[start + len(_PINNED_START) : end].strip()

    db.write_snapshot("current", text)
    if pinned:
        db.write_snapshot("user_pinned", pinned)
