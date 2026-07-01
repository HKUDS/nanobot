"""Structured Dream writer support for lifecycle memory concepts."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from nanobot.agent.memory_wiki import (
    ACTIVE_STATUS,
    INACTIVE_STATUSES,
    MemoryWikiConcept,
    MemoryWikiStore,
    slugify_concept_id,
)
from nanobot.agent.tools.base import Tool, tool_parameters

VALID_STATUSES = {ACTIVE_STATUS, *INACTIVE_STATUSES}
EVENT_RE = re.compile(
    r"^\[(?P<source>[^\]]*cursor[^\]]*)\](?:\s+\[[^\]]+\])?\s+"
    r"\[(?P<tag>[a-z]+)\]\s+(?P<text>.+)$"
)
MARKER_RE = re.compile(r"\b[A-Z][A-Z0-9]+(?:-[A-Z0-9]+){1,}\b")
DATE_RE = re.compile(r"\b20\d{2}-\d{2}-\d{2}\b")

CONCEPT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "id": {"type": "string", "description": "Stable slug-safe concept id."},
        "type": {"type": "string", "description": "Concept type, for example user_preference."},
        "title": {"type": "string", "description": "Short human-readable concept title."},
        "status": {
            "type": "string",
            "enum": sorted(VALID_STATUSES),
            "description": "Lifecycle status. Only active concepts enter prompt context.",
        },
        "tags": {"type": "array", "items": {"type": "string"}},
        "source": {"type": "array", "items": {"type": "string"}},
        "body": {"type": "string", "description": "Atomic memory fact without history tags."},
        "created_at": {"type": "string"},
        "last_verified_at": {"type": "string"},
        "expires_at": {"type": "string"},
        "supersedes": {"type": "array", "items": {"type": "string"}},
        "superseded_by": {"type": "array", "items": {"type": "string"}},
        "confidence": {"type": "number"},
    },
    "required": ["id", "type", "title", "status", "tags", "source", "body"],
}

MEMORY_CONCEPTS_TOOL_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "concepts": {
            "type": "array",
            "items": CONCEPT_SCHEMA,
            "description": "Lifecycle memory concepts to validate and write.",
        }
    },
    "required": ["concepts"],
}


@dataclass(frozen=True)
class ValidationResult:
    errors: list[str]
    warnings: list[str]

    @property
    def ok(self) -> bool:
        return not self.errors


@dataclass(frozen=True)
class WriterProviderCapability:
    provider: str | None
    model: str | None
    reasoning_effort: str | None
    supports_required_tool_choice: bool
    supports_named_tool_choice: bool
    selected_tool_choice: str
    reason: str


def build_memory_concepts_tool_schema() -> dict[str, Any]:
    """Return an OpenAI-compatible schema for the structured writer tool."""
    return {
        "type": "function",
        "function": {
            "name": "write_memory_concepts",
            "description": "Write derived memory wiki concepts with lifecycle metadata.",
            "parameters": MEMORY_CONCEPTS_TOOL_PARAMETERS,
        },
    }


def infer_writer_provider_capability(
    *,
    provider: str | None = None,
    model: str | None = None,
    reasoning_effort: str | None = None,
) -> WriterProviderCapability:
    """Infer safe Dream writer tool-choice settings from static provider config."""
    provider_norm = (provider or "").lower()
    model_norm = (model or "").lower()
    thinking_enabled = bool(reasoning_effort and reasoning_effort.lower() not in {"none", "off", "false"})
    deepseek_thinking = thinking_enabled and (
        provider_norm == "deepseek" or model_norm.startswith("deepseek-") or "deepseek-v4" in model_norm
    )
    if deepseek_thinking:
        return WriterProviderCapability(
            provider=provider,
            model=model,
            reasoning_effort=reasoning_effort,
            supports_required_tool_choice=False,
            supports_named_tool_choice=False,
            selected_tool_choice="auto",
            reason="provider thinking mode rejects required or named tool choice",
        )
    return WriterProviderCapability(
        provider=provider,
        model=model,
        reasoning_effort=reasoning_effort,
        supports_required_tool_choice=True,
        supports_named_tool_choice=True,
        selected_tool_choice="required",
        reason="required tool choice is allowed by static config",
    )


def repair_memory_concepts(
    concepts: list[dict[str, Any]],
    history_text: str = "",
    *,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Repair obvious lifecycle operations before validation.

    Model output is still the primary signal. This deterministic pass handles
    simple cases the model should not be trusted to enforce alone: correction
    tags, forget requests, expired facts, and duplicate active concepts.
    """
    current = {concept.id: concept for concept in _concepts_from_payloads(concepts)}
    groups: dict[str, list[str]] = {}
    for concept in current.values():
        groups.setdefault(_concept_group(concept.id), []).append(concept.id)

    for source, tag, text in _iter_history_events(history_text):
        marker = _first_marker(text)
        if tag == "skip":
            continue
        if tag == "correction" and "forget" in text.lower():
            target = marker
            if target:
                target_id = slugify_concept_id(target)
                existing = current.get(target_id)
                if existing:
                    existing.status = "forgotten"
                    existing.source = _sorted_unique([*existing.source, source])
                else:
                    current[target_id] = MemoryWikiConcept(
                        id=target_id,
                        title=target,
                        body=f"{target} was explicitly forgotten.",
                        type="user_private_data",
                        status="forgotten",
                        tags=["forgotten"],
                        source=[source],
                    )
            continue
        if not marker:
            continue

        concept_id = slugify_concept_id(marker)
        group = _concept_group(concept_id)
        previous_ids = groups.setdefault(group, [])
        if tag == "correction":
            for previous_id in previous_ids:
                previous = current.get(previous_id)
                if previous and previous.status == ACTIVE_STATUS and previous.id != concept_id:
                    previous.status = "invalidated"
                    previous.superseded_by = _sorted_unique([*previous.superseded_by, concept_id])

        expires_at = None
        if tag == "ephemeral":
            date = _first_date(text)
            if date:
                expires_at = f"{date}T23:59:59Z"

        status = ACTIVE_STATUS
        if expires_at and _is_expired(expires_at, now):
            status = "expired"

        concept = current.get(concept_id)
        if concept is None:
            concept = MemoryWikiConcept(
                id=concept_id,
                title=marker,
                body=_body_after_marker(text, marker),
                type=_infer_type(marker, text),
                status=status,
                tags=_sorted_unique(["dream", *_marker_tags(marker)]),
                source=[source],
                expires_at=expires_at,
            )
            current[concept_id] = concept
        else:
            event_body = _body_after_marker(text, marker)
            concept.id = concept_id
            concept.title = marker
            concept.body = event_body
            concept.type = _infer_type(marker, text)
            concept.status = status
            concept.tags = _sorted_unique([*concept.tags, *_marker_tags(marker)])
            concept.source = _sorted_unique([*concept.source, source])
            concept.expires_at = concept.expires_at or expires_at
        if tag == "correction":
            concept.supersedes = _sorted_unique([*concept.supersedes, *previous_ids])
        if concept_id not in previous_ids:
            previous_ids.append(concept_id)

    _expire_old_active(current.values(), now)
    _resolve_duplicate_active_groups(current.values())
    return [concept_to_dict(concept) for concept in sorted(current.values(), key=lambda item: item.id)]


def validate_memory_concepts(
    concepts: list[dict[str, Any]] | list[MemoryWikiConcept],
    *,
    now: datetime | None = None,
) -> ValidationResult:
    """Validate lifecycle invariants for derived memory concepts."""
    parsed = _concepts_from_payloads(concepts)
    errors: list[str] = []
    warnings: list[str] = []
    seen: set[str] = set()
    active_groups: dict[str, list[str]] = {}
    ids = {concept.id for concept in parsed}

    for concept in parsed:
        if not concept.id:
            errors.append("concept id is required")
            continue
        if concept.id in seen:
            errors.append(f"duplicate concept id: {concept.id}")
        seen.add(concept.id)
        if concept.status not in VALID_STATUSES:
            errors.append(f"{concept.id}: invalid status {concept.status!r}")
        if not concept.title.strip():
            errors.append(f"{concept.id}: title is required")
        if not concept.body.strip():
            errors.append(f"{concept.id}: body is required")
        if concept.status == ACTIVE_STATUS and not concept.source:
            errors.append(f"{concept.id}: active concept must include source")
        if concept.status == ACTIVE_STATUS and _is_expired(concept.expires_at, now):
            errors.append(f"{concept.id}: active concept is expired")
        if concept.status == ACTIVE_STATUS and _looks_forgotten(concept):
            errors.append(f"{concept.id}: forgotten/private removal cannot be active")
        if concept.status == ACTIVE_STATUS:
            active_groups.setdefault(_concept_group(concept.id), []).append(concept.id)
        for ref in [*concept.supersedes, *concept.superseded_by]:
            if ref and ref not in ids:
                warnings.append(f"{concept.id}: supersession reference not found: {ref}")

    for group, group_ids in active_groups.items():
        if len(group_ids) > 1:
            errors.append(f"{group}: multiple active concepts: {', '.join(sorted(group_ids))}")

    return ValidationResult(errors=errors, warnings=warnings)


def concept_to_dict(concept: MemoryWikiConcept) -> dict[str, Any]:
    data = asdict(concept)
    data.pop("path", None)
    return {key: value for key, value in data.items() if value not in (None, [])}


@tool_parameters(MEMORY_CONCEPTS_TOOL_PARAMETERS)
class WriteMemoryConceptsTool(Tool):
    """Dream-only tool that validates and writes derived memory concepts."""

    def __init__(
        self,
        store: MemoryWikiStore,
        *,
        history_text: str = "",
        now: datetime | None = None,
    ) -> None:
        self._store = store
        self._history_text = history_text
        self._now = now

    @property
    def name(self) -> str:
        return "write_memory_concepts"

    @property
    def description(self) -> str:
        return (
            "Validate and write derived memory wiki concepts. Use this for long-term "
            "facts with lifecycle metadata instead of free-form memory edits."
        )

    async def execute(self, concepts: list[dict[str, Any]]) -> str:
        repaired = repair_memory_concepts(concepts, self._history_text, now=self._now)
        validation = validate_memory_concepts(repaired, now=self._now)
        if not validation.ok:
            return "Error: invalid memory concepts: " + "; ".join(validation.errors[:8])

        parsed = _concepts_from_payloads(repaired)
        for concept in parsed:
            self._store.write_concept(concept)

        active_ids = [concept.id for concept in parsed if concept.status == ACTIVE_STATUS]
        summary = {
            "status": "ok",
            "written": len(parsed),
            "active": active_ids,
            "warnings": validation.warnings[:5],
        }
        return json.dumps(summary, ensure_ascii=False)


def _concepts_from_payloads(payloads: list[dict[str, Any]] | list[MemoryWikiConcept]) -> list[MemoryWikiConcept]:
    concepts: list[MemoryWikiConcept] = []
    for idx, payload in enumerate(payloads, start=1):
        if isinstance(payload, MemoryWikiConcept):
            payload.id = slugify_concept_id(payload.id or payload.title)
            payload.supersedes = [slugify_concept_id(item) for item in payload.supersedes]
            payload.superseded_by = [slugify_concept_id(item) for item in payload.superseded_by]
            concepts.append(payload)
            continue
        if not isinstance(payload, dict):
            continue
        title = str(payload.get("title") or payload.get("id") or f"memory-concept-{idx}")
        concept = MemoryWikiConcept(
            id=slugify_concept_id(payload.get("id") or title),
            title=title,
            body=str(payload.get("body") or payload.get("content") or ""),
            type=str(payload.get("type") or "fact"),
            status=str(payload.get("status") or ACTIVE_STATUS),
            tags=_as_str_list(payload.get("tags")),
            source=_as_str_list(payload.get("source")),
            created_at=_optional_str(payload.get("created_at")),
            last_verified_at=_optional_str(payload.get("last_verified_at")),
            expires_at=_optional_str(payload.get("expires_at")),
            supersedes=[slugify_concept_id(item) for item in _as_str_list(payload.get("supersedes"))],
            superseded_by=[
                slugify_concept_id(item) for item in _as_str_list(payload.get("superseded_by"))
            ],
            confidence=_as_float(payload.get("confidence")),
        )
        concepts.append(concept)
    return concepts


def _iter_history_events(history_text: str) -> list[tuple[str, str, str]]:
    events: list[tuple[str, str, str]] = []
    for line in history_text.splitlines():
        match = EVENT_RE.match(line.strip())
        if match:
            events.append((match.group("source"), match.group("tag"), match.group("text")))
    return events


def _resolve_duplicate_active_groups(concepts: Any) -> None:
    groups: dict[str, list[MemoryWikiConcept]] = {}
    for concept in concepts:
        if concept.status == ACTIVE_STATUS:
            groups.setdefault(_concept_group(concept.id), []).append(concept)
    for group_concepts in groups.values():
        if len(group_concepts) <= 1:
            continue
        winner = sorted(group_concepts, key=_latest_source_key)[-1]
        for concept in group_concepts:
            if concept is winner:
                continue
            concept.status = "invalidated"
            concept.superseded_by = _sorted_unique([*concept.superseded_by, winner.id])
            winner.supersedes = _sorted_unique([*winner.supersedes, concept.id])


def _expire_old_active(concepts: Any, now: datetime | None) -> None:
    for concept in concepts:
        if concept.status == ACTIVE_STATUS and _is_expired(concept.expires_at, now):
            concept.status = "expired"


def _latest_source_key(concept: MemoryWikiConcept) -> tuple[int, str]:
    cursor = 0
    for source in concept.source:
        match = re.search(r"cursor:(\d+)", source)
        if match:
            cursor = max(cursor, int(match.group(1)))
    return (cursor, concept.id)


def _concept_group(value: str) -> str:
    raw = slugify_concept_id(value)
    return re.sub(r"-(old|current)$", "", raw)


def _first_marker(text: str) -> str | None:
    match = MARKER_RE.search(text)
    return match.group(0) if match else None


def _body_after_marker(text: str, marker: str) -> str:
    idx = text.find(marker)
    if idx < 0:
        return text.strip()
    body = text[idx + len(marker):].lstrip(": ").strip()
    return body or marker


def _first_date(text: str) -> str | None:
    match = DATE_RE.search(text)
    return match.group(0) if match else None


def _marker_tags(marker: str) -> list[str]:
    return [
        slugify_concept_id(part)
        for part in marker.split("-")
        if part and part.lower() not in {"rlv", "holdout"}
    ]


def _infer_type(marker: str, text: str) -> str:
    lowered = f"{marker} {text}".lower()
    if "phone" in lowered or "private" in lowered:
        return "user_private_data"
    if any(token in lowered for token in ("lang", "bullet", "preferred", "prefers")):
        return "user_preference"
    if "demo" in lowered or "deadline" in lowered:
        return "time_bound_fact"
    if any(token in lowered for token in ("port", "index", "nanobot", "nanobook")):
        return "project_decision"
    return "fact"


def _looks_forgotten(concept: MemoryWikiConcept) -> bool:
    text = f"{concept.id} {concept.title} {concept.body} {' '.join(concept.tags)}".lower()
    return "forgotten" in text or "asked to forget" in text


def _is_expired(value: str | None, now: datetime | None = None) -> bool:
    if not value:
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc) >= parsed.astimezone(timezone.utc)


def _sorted_unique(values: list[str]) -> list[str]:
    return sorted({str(value) for value in values if value})


def _as_str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if item is not None]
    return [str(value)]


def _optional_str(value: Any) -> str | None:
    return None if value is None else str(value)


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
