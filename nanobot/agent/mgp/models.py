"""Lightweight dataclasses for the MGP sidecar.

These models intentionally have **no** dependency on ``mgp_client``. They can
be imported even when the optional ``mgp-client`` package is not installed,
which keeps tooling such as ``/mgp-status`` and tests cheap.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RuntimeState:
    """Per-call runtime context fed into MGP policy and recall payloads.

    The fields mirror what the MGP ``PolicyContextBuilder`` consumes; we keep
    them in a plain dataclass so callers (sidecar / tool / consolidator hook)
    can build it without importing ``mgp_client``.
    """

    actor_agent: str
    user_id: str
    session_key: str
    workspace_id: str
    channel: str
    chat_id: str | None = None
    subject_kind: str = "user"
    tenant_id: str | None = None
    correlation_id: str | None = None


@dataclass
class RecallIntent:
    """A recall request constructed from agent tool-call params."""

    query: str
    limit: int = 5
    scope: str = "user"
    types: list[str] | None = None


@dataclass
class RecallItem:
    """One normalized hit from MGP search response."""

    memory: dict[str, Any]
    score: float | None = None
    score_kind: str | None = None
    retrieval_mode: str | None = None
    return_mode: str = "raw"
    redaction_info: dict[str, Any] | None = None
    backend_origin: str | None = None
    consumable_text: str | None = None
    matched_terms: list[str] | None = None
    explanation: str | None = None


@dataclass
class RecallOutcome:
    """Result of a single ``sidecar.recall(...)`` call.

    ``executed`` flips to ``False`` when the sidecar shorted out (e.g. fail-open
    swallowed a transport error). ``degraded`` indicates the call was attempted
    but failed. The tool layer is expected to handle ``degraded`` gracefully.
    """

    executed: bool
    degraded: bool
    results: list[RecallItem] = field(default_factory=list)
    request_id: str | None = None
    error_code: str | None = None
    error_message: str | None = None


@dataclass
class CommitOutcome:
    """Result of a single ``write_candidate`` attempt."""

    executed: bool
    written: bool
    memory_id: str | None = None
    request_id: str | None = None
    error_code: str | None = None
    error_message: str | None = None


@dataclass
class ParsedFact:
    """Intermediate structure produced by parsers.

    Both ``parse_consolidator_bullets`` and ``parse_dream_phase1_tags``
    normalize their inputs into a list of these so the sidecar can issue
    uniform ``write_candidate`` calls regardless of source.
    """

    scope: str          # "user" / "agent" / "session"
    type: str           # "preference" / "semantic_fact" / "profile" / "episodic_event"
    statement: str
    preference_value: str | None = None
    source_ref: str | None = None
