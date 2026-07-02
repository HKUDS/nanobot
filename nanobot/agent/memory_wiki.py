"""Derived memory wiki storage with explicit lifecycle metadata."""

from __future__ import annotations

import os
import re
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from nanobot.utils.helpers import ensure_dir, truncate_text

_FRONTMATTER_RE = re.compile(r"\A---\r?\n(?P<meta>.*?)\r?\n---\r?\n?(?P<body>.*)\Z", re.S)
_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_-]*")
_SLUG_RE = re.compile(r"[^a-z0-9_-]+")

ACTIVE_STATUS = "active"
INACTIVE_STATUSES = {"invalidated", "forgotten", "superseded", "expired"}
DEFAULT_CONTEXT_MAX_CHARS = 8_000
DEFAULT_CONTEXT_MAX_ITEMS = 16


@dataclass
class MemoryWikiConcept:
    """One derived memory concept stored as Markdown plus YAML frontmatter."""

    id: str
    title: str
    body: str
    type: str = "fact"
    status: str = ACTIVE_STATUS
    tags: list[str] = field(default_factory=list)
    source: list[str] = field(default_factory=list)
    created_at: str | None = None
    last_verified_at: str | None = None
    expires_at: str | None = None
    supersedes: list[str] = field(default_factory=list)
    superseded_by: list[str] = field(default_factory=list)
    confidence: float | None = None
    path: Path | None = None

    def is_current(self, now: datetime | None = None) -> bool:
        """Return True when this concept is active and not expired."""
        if self.status != ACTIVE_STATUS:
            return False
        expires_at = _parse_datetime(self.expires_at)
        if not expires_at:
            return True
        return _normalize_datetime(now) < expires_at

    def source_label(self) -> str:
        """Return a compact, deterministic source label for prompt context."""
        return ", ".join(self.source) if self.source else "unknown"

    def searchable_text(self) -> str:
        return " ".join(
            [
                self.id,
                self.type,
                self.title,
                " ".join(self.tags),
                self.body,
                self.source_label(),
            ]
        )

    def to_markdown(self) -> str:
        metadata: dict[str, Any] = {
            "id": self.id,
            "type": self.type,
            "title": self.title,
            "status": self.status,
            "tags": self.tags,
            "source": self.source,
        }
        optional = {
            "created_at": self.created_at,
            "last_verified_at": self.last_verified_at,
            "expires_at": self.expires_at,
            "supersedes": self.supersedes,
            "superseded_by": self.superseded_by,
            "confidence": self.confidence,
        }
        metadata.update({key: value for key, value in optional.items() if value not in (None, [])})
        frontmatter = yaml.safe_dump(
            metadata,
            allow_unicode=False,
            sort_keys=False,
            default_flow_style=False,
        ).strip()
        body = self.body.strip()
        return f"---\n{frontmatter}\n---\n{body}\n"


class MemoryWikiStore:
    """File-backed derived memory concepts with lifecycle-aware retrieval."""

    def __init__(self, root: Path):
        self.root = root

    def write_concept(self, concept: MemoryWikiConcept) -> Path:
        """Write a concept atomically and return its path."""
        ensure_dir(self.root)
        concept_id = _slugify(concept.id or concept.title)
        path = self.root / f"{concept_id}.md"
        concept.id = concept_id
        concept.path = path
        _atomic_write_text(path, concept.to_markdown())
        return path

    def read_concept(self, concept_id: str) -> MemoryWikiConcept | None:
        path = self.root / f"{_slugify(concept_id)}.md"
        return self._read_concept_file(path)

    def mark_status(
        self,
        concept_id: str,
        status: str,
        *,
        superseded_by: list[str] | None = None,
    ) -> bool:
        """Update a concept status without deleting the audit record."""
        concept = self.read_concept(concept_id)
        if not concept:
            return False
        concept.status = status
        if superseded_by is not None:
            concept.superseded_by = [_slugify(item) for item in superseded_by]
        self.write_concept(concept)
        return True

    def iter_concepts(self) -> list[MemoryWikiConcept]:
        """Return all parseable concepts, skipping missing and malformed files."""
        if not self.root.exists():
            return []
        return [
            concept
            for path in sorted(self.root.glob("*.md"))
            if (concept := self._read_concept_file(path)) is not None
        ]

    def current_concepts(self, now: datetime | None = None) -> list[MemoryWikiConcept]:
        return [concept for concept in self.iter_concepts() if concept.is_current(now)]

    def has_current_context(self, now: datetime | None = None) -> bool:
        return bool(self.current_concepts(now))

    def retrieve(
        self,
        query: str | None = None,
        *,
        now: datetime | None = None,
        max_items: int = DEFAULT_CONTEXT_MAX_ITEMS,
    ) -> list[MemoryWikiConcept]:
        """Retrieve active concepts by lexical relevance."""
        concepts = self.current_concepts(now)
        if not concepts:
            return []

        query_tokens = _tokens(query or "")
        if not query_tokens:
            return sorted(concepts, key=_stable_concept_key)[:max_items]

        scored = [(_score_concept(concept, query_tokens), concept) for concept in concepts]
        matches = [(score, concept) for score, concept in scored if score > 0]
        if not matches:
            return []
        return [
            concept
            for _score, concept in sorted(
                matches,
                key=lambda item: (-item[0], _stable_concept_key(item[1])),
            )
        ][:max_items]

    def get_context(
        self,
        query: str | None = None,
        *,
        now: datetime | None = None,
        max_chars: int = DEFAULT_CONTEXT_MAX_CHARS,
        max_items: int = DEFAULT_CONTEXT_MAX_ITEMS,
    ) -> str:
        """Build bounded prompt context from active derived memories only."""
        concepts = self.retrieve(query, now=now, max_items=max_items)
        if not concepts:
            return ""

        lines = [
            "Only active, non-expired derived memories are listed here. "
            "Invalidated, forgotten, superseded, and expired memories are omitted.",
        ]
        for concept in concepts:
            tags = f"; tags: {', '.join(concept.tags)}" if concept.tags else ""
            source = f"; source: {concept.source_label()}"
            meta = f"id: {concept.id}; type: {concept.type}; status: {concept.status}{tags}{source}"
            body = " ".join(concept.body.strip().split())
            lines.append(f"- {concept.title} ({meta})")
            if body:
                lines.append(f"  {truncate_text(body, 500)}")

        return truncate_text("\n".join(lines), max_chars)

    def _read_concept_file(self, path: Path) -> MemoryWikiConcept | None:
        with suppress(OSError, UnicodeError, yaml.YAMLError):
            text = path.read_text(encoding="utf-8")
            match = _FRONTMATTER_RE.match(text)
            if not match:
                return None
            metadata = yaml.safe_load(match.group("meta")) or {}
            if not isinstance(metadata, dict):
                return None
            title = _as_str(metadata.get("title"))
            if not title:
                return None
            return MemoryWikiConcept(
                id=_slugify(_as_str(metadata.get("id")) or path.stem),
                type=_as_str(metadata.get("type")) or "fact",
                title=title,
                status=_as_str(metadata.get("status")) or ACTIVE_STATUS,
                tags=_as_list(metadata.get("tags")),
                source=_as_list(metadata.get("source")),
                created_at=_optional_str(metadata.get("created_at")),
                last_verified_at=_optional_str(metadata.get("last_verified_at")),
                expires_at=_optional_str(metadata.get("expires_at")),
                supersedes=[_slugify(item) for item in _as_list(metadata.get("supersedes"))],
                superseded_by=[
                    _slugify(item) for item in _as_list(metadata.get("superseded_by"))
                ],
                confidence=_as_float(metadata.get("confidence")),
                body=match.group("body").strip(),
                path=path,
            )
        return None


def slugify_concept_id(value: Any) -> str:
    return _slugify(value)


def _atomic_write_text(path: Path, content: str) -> None:
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        f.write(content)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, path)


def _slugify(value: Any) -> str:
    normalized = str(value).strip().lower().replace(" ", "-")
    normalized = _SLUG_RE.sub("-", normalized).strip("-")
    return normalized or "memory"


def _stable_concept_key(concept: MemoryWikiConcept) -> tuple[str, str]:
    return (concept.type.lower(), concept.title.lower())


def _tokens(text: str) -> set[str]:
    return set(_TOKEN_RE.findall(text.lower()))


def _score_concept(concept: MemoryWikiConcept, query_tokens: set[str]) -> int:
    text_tokens = _tokens(concept.searchable_text())
    title_tokens = _tokens(concept.title)
    tag_tokens = _tokens(" ".join(concept.tags))
    source_tokens = _tokens(concept.source_label())
    id_tokens = _tokens(concept.id)
    score = 0
    for token in query_tokens:
        if token in text_tokens:
            score += 1
        if token in id_tokens:
            score += 3
        if token in title_tokens:
            score += 2
        if token in tag_tokens:
            score += 2
        if token in source_tokens:
            score += 1
    return score


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if item is not None]
    if isinstance(value, tuple):
        return [str(item) for item in value if item is not None]
    return [str(value)]


def _as_str(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    with suppress(TypeError, ValueError):
        return float(value)
    return None


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    with suppress(ValueError):
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        return _normalize_datetime(parsed)
    return None


def _normalize_datetime(value: datetime | None) -> datetime:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        return current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc)
