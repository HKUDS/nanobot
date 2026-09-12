"""Versioned DTOs stored by the evolution subsystem."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import IntEnum
from typing import Any

SCHEMA_VERSION = 1


class RiskLevel(IntEnum):
    """Risk levels from harmless records to prohibited autonomous changes."""

    OBSERVATION = 0
    REVERSIBLE = 1
    APPROVAL_REQUIRED = 2
    PROHIBITED = 3


@dataclass(frozen=True, slots=True)
class Experience:
    id: str
    created_at: str
    turn_id: str
    session_hash: str
    channel: str
    kind: str
    model: str
    outcome: str
    failure_error_kind: str | None
    latency_ms: int | None
    usage: dict[str, Any] | None
    input_chars: int
    input_hash: str
    output_chars: int
    tool_calls: int
    tools: tuple[str, ...]
    correction_signal: bool
    model_rounds: int = 0
    runtime_context_chars: int = 0
    input_excerpt: str | None = None
    output_excerpt: str | None = None
    schema_version: int = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["tools"] = list(self.tools)
        return value


@dataclass(frozen=True, slots=True)
class Proposal:
    id: str
    created_at: str
    issue: str
    evidence_ids: tuple[str, ...]
    evidence_summary: dict[str, Any]
    proposed_change: str
    change_type: str
    risk: RiskLevel
    status: str = "open"
    schema_version: int = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["evidence_ids"] = list(self.evidence_ids)
        value["risk"] = int(self.risk)
        return value


@dataclass(frozen=True, slots=True)
class Experiment:
    id: str
    created_at: str
    proposal_id: str
    hypothesis: str
    risk: RiskLevel
    baseline: dict[str, float]
    candidate: dict[str, float]
    critical_metrics: tuple[str, ...] = field(default_factory=tuple)
    minimum_improvement: float = 0.0
    status: str = "pending"
    schema_version: int = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["risk"] = int(self.risk)
        value["critical_metrics"] = list(self.critical_metrics)
        return value
