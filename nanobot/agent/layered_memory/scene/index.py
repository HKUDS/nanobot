"""L2 scene index at ``{workspace}/memory/scene_index.json``."""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from loguru import logger

from nanobot.utils.helpers import _write_text_atomic, ensure_dir

_INDEX_NAME = "scene_index.json"
_SCENES_DIR = "memory/scenes"
_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


@dataclass
class SceneEntry:
    slug: str
    title: str
    path: str
    session_keys: list[str] = field(default_factory=list)
    updated_at: float = 0.0
    summary: str = ""
    source_atom_ids: list[str] = field(default_factory=list)


class SceneIndex:
    """Read/write ``memory/scene_index.json`` and scene markdown files."""

    def __init__(self, workspace: Path) -> None:
        self._workspace = workspace
        self._index_path = workspace / "memory" / _INDEX_NAME
        self._scenes_dir = workspace / _SCENES_DIR

    @property
    def index_path(self) -> Path:
        return self._index_path

    @property
    def scenes_dir(self) -> Path:
        return self._scenes_dir

    def scene_path(self, slug: str) -> Path:
        return self._scenes_dir / f"{normalize_slug(slug)}.md"

    def load(self) -> list[SceneEntry]:
        if not self._index_path.is_file():
            return []
        try:
            raw = json.loads(self._index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.warning("layered_memory scene_index_read_failed path={}", self._index_path)
            return []
        if not isinstance(raw, dict):
            return []
        items = raw.get("scenes")
        if not isinstance(items, list):
            return []
        entries: list[SceneEntry] = []
        for item in items:
            entry = _parse_entry(item)
            if entry is not None:
                entries.append(entry)
        return entries

    def save(self, entries: list[SceneEntry]) -> None:
        ensure_dir(self._index_path.parent)
        payload = {"scenes": [_entry_to_dict(entry) for entry in entries]}
        _write_text_atomic(
            self._index_path,
            json.dumps(payload, ensure_ascii=False, indent=2),
        )

    def upsert(self, entry: SceneEntry) -> None:
        slug = normalize_slug(entry.slug)
        if not slug:
            raise ValueError("scene slug is required")
        entries = self.load()
        replaced = False
        for idx, existing in enumerate(entries):
            if existing.slug == slug:
                entries[idx] = entry
                replaced = True
                break
        if not replaced:
            entries.append(entry)
        entries.sort(key=lambda row: row.updated_at, reverse=True)
        self.save(entries)

    def write_scene_markdown(self, slug: str, content: str) -> Path:
        path = self.scene_path(slug)
        ensure_dir(path.parent)
        _write_text_atomic(path, content.rstrip() + "\n")
        return path

    def list_for_session(self, session_key: str, *, limit: int = 50) -> list[SceneEntry]:
        entries = self.load()
        matched = [row for row in entries if session_key in row.session_keys]
        if matched:
            return matched[:limit]
        return entries[:limit]

    def format_navigation(
        self,
        *,
        session_key: str | None = None,
        max_entries: int = 8,
    ) -> list[str]:
        """Build recall navigation lines (title + relative path, no full body)."""
        if max_entries <= 0:
            return []
        if session_key:
            entries = self.list_for_session(session_key, limit=max_entries)
        else:
            entries = sorted(self.load(), key=lambda row: row.updated_at, reverse=True)[:max_entries]
        if not entries:
            return []
        lines = ["[Scene navigation]"]
        for entry in entries:
            lines.append(f"- {entry.title} → {entry.path}")
        lines.append("(Use read_file to load a scene; navigation only.)")
        return lines


def normalize_slug(raw: str) -> str:
    text = raw.strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = text.strip("-")
    if not text or not _SLUG_RE.match(text):
        return ""
    return text


def relative_scene_path(slug: str) -> str:
    return f"{_SCENES_DIR}/{normalize_slug(slug)}.md"


def _parse_entry(raw: object) -> SceneEntry | None:
    if not isinstance(raw, dict):
        return None
    slug = normalize_slug(str(raw.get("slug", "")))
    title = str(raw.get("title", "")).strip()
    path = str(raw.get("path", "")).strip() or relative_scene_path(slug)
    if not slug or not title:
        return None
    session_keys = _parse_str_list(raw.get("session_keys"))
    source_atom_ids = _parse_str_list(raw.get("source_atom_ids"))
    try:
        updated_at = float(raw.get("updated_at", 0.0))
    except (TypeError, ValueError):
        updated_at = 0.0
    summary = str(raw.get("summary", "")).strip()
    return SceneEntry(
        slug=slug,
        title=title,
        path=path,
        session_keys=session_keys,
        updated_at=updated_at,
        summary=summary,
        source_atom_ids=source_atom_ids,
    )


def _entry_to_dict(entry: SceneEntry) -> dict[str, object]:
    return {
        "slug": entry.slug,
        "title": entry.title,
        "path": entry.path,
        "session_keys": list(entry.session_keys),
        "updated_at": entry.updated_at,
        "summary": entry.summary,
        "source_atom_ids": list(entry.source_atom_ids),
    }


def _parse_str_list(raw: object) -> list[str]:
    if not isinstance(raw, list):
        return []
    return [str(item).strip() for item in raw if str(item).strip()]
