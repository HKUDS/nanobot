"""Media transcription cache -- avoids re-processing the same image twice.

Images are identified by SHA-256 content hash.  The vision model's description
is stored in ~/.nanobot/media/transcription_cache.json and reused on subsequent
turns that reference the same file.

Flow:
  1. Incoming image -> compute hash -> check cache
  2a. Cache HIT  -> return stored description as text (no LLM call, file deleted)
  2b. Cache MISS -> call vision model with surrounding context -> store description
                   -> return description as text -> file deleted
"""

import hashlib
import json
import time
from pathlib import Path
from typing import Any


class MediaCache:
    """Persistent cache of image-to-text transcriptions."""

    _VERSION = 1

    def __init__(self, workspace: Path):
        self._dir = workspace / "media"
        self._path = self._dir / "transcription_cache.json"
        self._cache: dict[str, dict[str, Any]] = {}
        self._dirty = False
        self._load()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get(self, file_hash: str) -> str | None:
        """Return cached description, or None on cache miss."""
        entry = self._cache.get(file_hash)
        if entry:
            entry["hits"] = entry.get("hits", 0) + 1
            entry["last_used"] = time.time()
            self._dirty = True
        return entry["description"] if entry else None

    def put(self, file_hash: str, description: str, original_path: str) -> None:
        """Store a description for an image hash."""
        self._cache[file_hash] = {
            "description": description,
            "original_path": original_path,
            "created": time.time(),
            "last_used": time.time(),
            "hits": 0,
        }
        self._dirty = True
        self.flush()

    def flush(self) -> None:
        """Persist the cache to disk if it has changed."""
        if not self._dirty:
            return
        self._dir.mkdir(parents=True, exist_ok=True)
        data = {"_version": self._VERSION, "entries": self._cache}
        tmp = self._path.with_suffix(".tmp")
        try:
            tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self._path)
        except OSError:
            pass
        self._dirty = False

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def hash_file(path: str | Path) -> str | None:
        """Compute SHA-256 of a file's contents.  Returns None if unreadable."""
        try:
            h = hashlib.sha256()
            with open(path, "rb") as f:
                for chunk in iter(lambda: f.read(65536), b""):
                    h.update(chunk)
            return h.hexdigest()
        except OSError:
            return None

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            self._cache = data.get("entries", {})
        except (json.JSONDecodeError, OSError):
            self._cache = {}
