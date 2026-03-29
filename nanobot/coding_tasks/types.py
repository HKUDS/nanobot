"""Types for Codex-backed coding tasks."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def now_ms() -> int:
    """Return the current Unix timestamp in milliseconds."""
    import time

    return int(time.time() * 1000)


TASK_STATUS_VALUES = (
    "queued",
    "starting",
    "running",
    "waiting_user",
    "completed",
    "failed",
    "cancelled",
)

HARNESS_STATE_VALUES = (
    "missing",
    "initializing",
    "active",
)

HARNESS_RESOLUTION_VALUES = (
    "resume_existing",
    "start_new_goal",
)


@dataclass(slots=True)
class CodingTask:
    """Persistent metadata for one Codex-backed coding task."""

    id: str
    title: str
    repo_path: str
    goal: str
    status: str = "queued"
    branch_name: str | None = None
    tmux_session: str | None = None
    codex_session_hint: str | None = None
    harness_state: str = "missing"
    approval_policy: str = "local_only"
    last_progress_summary: str = ""
    last_progress_at_ms: int | None = None
    last_user_control: str | None = None
    created_at_ms: int = field(default_factory=now_ms)
    updated_at_ms: int = field(default_factory=now_ms)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class CodingRunEvent:
    """Append-only run log entry for one coding task."""

    task_id: str
    event: str
    status: str
    message: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    run_at_ms: int = field(default_factory=now_ms)
