"""GEPA run status persistence for ``{workspace}/.nanobot/gepa_run.json``."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Literal

from filelock import FileLock, Timeout
from loguru import logger

GepaRunPhase = Literal[
    "idle",
    "starting",
    "selecting",
    "optimizing",
    "writing",
    "completed",
    "failed",
    "skipped",
]
GepaRunTrigger = Literal["cron", "cli", "slash"]

_PHASES: frozenset[str] = frozenset(
    {"idle", "starting", "selecting", "optimizing", "writing", "completed", "failed", "skipped"}
)
_TRIGGERS: frozenset[str] = frozenset({"cron", "cli", "slash"})

GEPA_SKIP_ALREADY_RUNNING = "already running"


@dataclass(frozen=True, slots=True)
class GepaRunStatus:
    """Latest GEPA run state for a workspace."""

    run_id: str = ""
    trigger: GepaRunTrigger | None = None
    skill_name: str | None = None
    phase: GepaRunPhase = "idle"
    message: str = ""
    started_at: str = ""
    finished_at: str = ""
    proposals_created: tuple[str, ...] = ()
    traces_consumed: tuple[str, ...] = ()
    budget_usd_spent: float = 0.0
    error: str = ""

    @classmethod
    def idle(cls) -> GepaRunStatus:
        """Return the default empty workspace state."""
        return cls()

    def with_updates(self, **changes: Any) -> GepaRunStatus:
        """Return a copy with selected fields replaced."""
        return replace(self, **changes)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "run_id": self.run_id,
            "phase": self.phase,
            "message": self.message,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "proposals_created": list(self.proposals_created),
            "traces_consumed": list(self.traces_consumed),
            "budget_usd_spent": self.budget_usd_spent,
            "error": self.error,
        }
        if self.trigger is not None:
            payload["trigger"] = self.trigger
        if self.skill_name is not None:
            payload["skill_name"] = self.skill_name
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GepaRunStatus:
        phase_raw = str(data.get("phase") or "idle")
        phase: GepaRunPhase = phase_raw if phase_raw in _PHASES else "idle"  # type: ignore[assignment]

        trigger_raw = data.get("trigger")
        trigger: GepaRunTrigger | None = None
        if isinstance(trigger_raw, str) and trigger_raw in _TRIGGERS:
            trigger = trigger_raw  # type: ignore[assignment]

        skill_name_raw = data.get("skill_name")
        skill_name = str(skill_name_raw) if skill_name_raw else None

        proposals = _coerce_str_list(data.get("proposals_created"))
        traces = _coerce_str_list(data.get("traces_consumed"))

        try:
            budget = float(data.get("budget_usd_spent") or 0.0)
        except (TypeError, ValueError):
            budget = 0.0

        return cls(
            run_id=str(data.get("run_id") or ""),
            trigger=trigger,
            skill_name=skill_name,
            phase=phase,
            message=str(data.get("message") or ""),
            started_at=str(data.get("started_at") or ""),
            finished_at=str(data.get("finished_at") or ""),
            proposals_created=tuple(proposals),
            traces_consumed=tuple(traces),
            budget_usd_spent=budget,
            error=str(data.get("error") or ""),
        )


class GepaRunStore:
    """Read/write GEPA run status at ``{workspace}/.nanobot/gepa_run.json``."""

    def __init__(self, workspace: Path) -> None:
        self._path = workspace.expanduser().resolve() / ".nanobot" / "gepa_run.json"

    @property
    def path(self) -> Path:
        return self._path

    def get(self) -> GepaRunStatus:
        """Load status from disk; missing or corrupt files degrade to idle."""
        if not self._path.exists():
            return GepaRunStatus.idle()
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("GEPA run status unreadable ({}): {}", self._path, exc)
            return GepaRunStatus.idle()
        if not isinstance(raw, dict):
            logger.warning("GEPA run status is not an object: {}", self._path)
            return GepaRunStatus.idle()
        return GepaRunStatus.from_dict(raw)

    def save(self, status: GepaRunStatus) -> None:
        """Persist *status* atomically as JSON."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(status.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


class GepaRunLock:
    """Cross-process single-flight lock at ``{workspace}/.nanobot/gepa_run.lock``."""

    def __init__(self, workspace: Path) -> None:
        self._path = workspace.expanduser().resolve() / ".nanobot" / "gepa_run.lock"
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = FileLock(str(self._path))
        self._held = False

    @property
    def path(self) -> Path:
        return self._path

    def try_acquire_run_lock(self) -> bool:
        """Try to acquire the lock without blocking."""
        if self._held:
            return True
        try:
            self._lock.acquire(timeout=0)
        except Timeout:
            return False
        self._held = True
        return True

    def release_run_lock(self) -> None:
        """Release the lock when held by this instance."""
        if not self._held:
            return
        self._lock.release()
        self._held = False


def _coerce_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if item is not None and str(item)]
