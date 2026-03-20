"""Session-scoped scratchpad for multi-agent artifact sharing.

Each conversation session gets its own scratchpad file (JSONL).  Agents
write intermediate results, plans, and artifacts here; other agents (or the
same agent in a later turn) can read them back.

Thread-safe via ``asyncio.Lock`` for writes.  Capped at ``max_entries``
(oldest evicted on overflow).
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from loguru import logger


class Scratchpad:
    """Per-session JSONL-backed scratchpad."""

    def __init__(self, session_dir: Path, *, max_entries: int = 50) -> None:
        self._path = session_dir / "scratchpad.jsonl"
        self._max_entries = max_entries
        self._lock = asyncio.Lock()
        self._entries: list[dict[str, Any]] = []
        self._loaded = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def write(
        self, *, role: str, label: str, content: str, metadata: dict[str, Any] | None = None
    ) -> str:
        """Append an entry and return its ID."""
        entry_id = uuid.uuid4().hex[:8]
        entry: dict[str, Any] = {
            "id": entry_id,
            "role": role,
            "label": label,
            "content": content,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        if metadata:
            entry["metadata"] = metadata
        async with self._lock:
            self._ensure_loaded()
            self._entries.append(entry)
            # Evict oldest if over cap — full rewrite needed on eviction (LAN-128).
            if len(self._entries) > self._max_entries:
                self._entries = self._entries[-self._max_entries :]
                self._flush(full_rewrite=True)
            else:
                self._flush(full_rewrite=False)
        return entry_id

    def read(self, entry_id: str | None = None) -> str:
        """Read a specific entry by ID, or all entries if *entry_id* is ``None``."""
        self._ensure_loaded()
        if entry_id:
            for e in self._entries:
                if e["id"] == entry_id:
                    tag = self._grounded_tag(e)
                    return f"[{e['id']}]{tag} ({e['role']}) {e['label']}\n{e['content']}"
            return f"Entry {entry_id} not found."
        if not self._entries:
            return "Scratchpad is empty."
        parts = []
        for e in self._entries:
            tag = self._grounded_tag(e)
            parts.append(f"[{e['id']}]{tag} ({e['role']}) {e['label']}: {e['content'][:200]}")
        return "\n".join(parts)

    @staticmethod
    def _grounded_tag(entry: dict[str, Any]) -> str:
        """Return a short verification tag from entry metadata."""
        meta = entry.get("metadata")
        if not isinstance(meta, dict):
            return ""
        grounded = meta.get("grounded")
        if grounded is True:
            return " ✓"
        if grounded is False:
            return " ⚠ungrounded"
        return ""

    def list_entries(self) -> list[dict[str, Any]]:
        """Return all entries as dicts."""
        self._ensure_loaded()
        return list(self._entries)

    async def clear(self) -> None:
        """Remove all entries."""
        async with self._lock:
            self._entries.clear()
            if self._path.exists():
                self._path.unlink()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        if not self._path.exists():
            return
        try:
            for line in self._path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line:
                    self._entries.append(json.loads(line))
        except (json.JSONDecodeError, OSError):
            logger.warning("Failed to load scratchpad {}", self._path)

    def _flush(self, *, full_rewrite: bool = True) -> None:
        """Write scratchpad entries to disk.

        When *full_rewrite* is False, append only the latest entry (faster for
        the common non-eviction case). When True, rewrite the entire file (used
        after eviction). Keeping I/O minimal avoids blocking the event loop
        under parallel agent writes (LAN-128).
        """
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            if full_rewrite or not self._path.exists():
                self._path.write_text(
                    "\n".join(json.dumps(e, ensure_ascii=False) for e in self._entries) + "\n",
                    encoding="utf-8",
                )
            else:
                with self._path.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(self._entries[-1], ensure_ascii=False) + "\n")
        except OSError:
            logger.warning("Failed to flush scratchpad {}", self._path)
