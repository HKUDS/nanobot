"""Types for gateway conditional-trigger runtime.

ConditionMonitor / TriggerDecision / MonitorConfig contract.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class TriggerDecision:
    """Result of one ConditionMonitor.evaluate()."""

    should_wake: bool
    trigger_id: str = ""
    content: str = ""
    dedupe_key: str | None = None
    cooldown_until_ms: int | None = None
    evidence: dict[str, Any] | None = None
    reason: str = ""

    def __post_init__(self) -> None:
        if self.should_wake:
            if not self.trigger_id.strip():
                raise ValueError("TriggerDecision.should_wake=True requires trigger_id")
            if not self.content.strip():
                raise ValueError("TriggerDecision.should_wake=True requires content")


@dataclass(frozen=True, slots=True)
class MonitorConfig:
    """Static scheduling knobs per monitor — runtime owns the clock."""

    interval_s: float = 2700.0
    timeout_s: float = 15.0
    max_backoff_s: float = 1800.0
    initial_backoff_s: float = 30.0
    backoff_factor: float = 2.0
    enabled: bool = True

    def __post_init__(self) -> None:
        if self.interval_s <= 0:
            raise ValueError("interval_s must be > 0")
        if self.timeout_s <= 0:
            raise ValueError("timeout_s must be > 0")


@runtime_checkable
class ConditionMonitor(Protocol):
    """Lightweight pure-Python checker. Never touches LLM."""

    id: str  # unique monitor identifier, e.g. "script_signal"
    name: str  # human-readable label
    config: MonitorConfig

    async def evaluate(self, now: datetime) -> TriggerDecision | None:
        """Return None or TriggerDecision(should_wake=False) to stay silent."""
        ...


# Audit event emitted per evaluation (for file log / metrics).
@dataclass(slots=True)
class MonitorAuditEvent:
    monitor_id: str
    at_ms: int
    should_wake: bool
    trigger_id: str | None = None
    dedupe_key: str | None = None
    reason: str = ""
    evidence: dict[str, Any] | None = None
    error: str | None = None
    duration_ms: int = 0
    enqueued: bool = False
    skipped_reason: str | None = None  # cooldown/dedupe/disabled/not_due
