"""Low-level persistence for memory files and JSON payloads.

``MemoryPersistence`` owns all direct file I/O for the memory subsystem.
It manages four files under ``<workspace>/memory/``:

- ``events.jsonl`` — append-only structured events (one JSON object per line)
- ``profile.json`` — current user profile state (facts, preferences)
- ``MEMORY.md``    — active knowledge snapshot injected into system prompts
- ``HISTORY.md``   — human-readable event log

All reads/writes are synchronous (file sizes are small).  Callers should
not bypass this class to touch memory files directly.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from nanobot.utils.helpers import ensure_dir


class MemoryPersistence:
    """Low-level persistence for memory files and JSON payloads."""

    def __init__(self, workspace: Path):
        self.memory_dir = ensure_dir(workspace / "memory")
        self.memory_file = self.memory_dir / "MEMORY.md"
        self.history_file = self.memory_dir / "HISTORY.md"
        self.events_file = self.memory_dir / "events.jsonl"
        self.profile_file = self.memory_dir / "profile.json"

    @staticmethod
    def read_json(path: Path) -> dict[str, Any] | list[Any] | None:
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, (dict, list)):
                return data
        except Exception:  # crash-barrier: varied file I/O + encoding
            return None
        return None

    @staticmethod
    def write_json(path: Path, payload: dict[str, Any] | list[Any]) -> None:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def read_jsonl(path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        out: list[dict[str, Any]] = []
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(item, dict):
                    out.append(item)
        return out

    @staticmethod
    def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
        with open(path, "w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")

    @staticmethod
    def append_text(path: Path, text: str) -> None:
        with open(path, "a", encoding="utf-8") as f:
            f.write(text)

    @staticmethod
    def read_text(path: Path) -> str:
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8")

    @staticmethod
    def write_text(path: Path, text: str) -> None:
        path.write_text(text, encoding="utf-8")
