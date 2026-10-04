"""Task observations shared by execution and private child sessions."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Literal

from nanobot.providers.base import LLMUsage

SubagentState = Literal["queued", "running", "stopping", "done", "incomplete", "error", "cancelled", "interrupted"]


@dataclass(slots=True)
class SubagentStatus:
    """Observable task data, detached from execution and process resources."""

    task_id: str
    label: str
    task_description: str
    started_at: float          # time.monotonic()
    finished_at: float | None = None
    # Runner checkpoints refine phase without changing the control lifecycle state.
    phase: str = "queued"
    owner: str = ""
    state: SubagentState = "queued"
    receipts: dict[str, str] = field(default_factory=dict)
    result: str | None = None
    partial: bool = False
    iteration: int = 0
    tool_events: list[dict[str, str]] = field(default_factory=list)
    usage: LLMUsage | None = None
    stop_reason: str | None = None
    error: str | None = None
    origin_message_id: str | None = None
    origin_turn_id: str | None = None
    created_at: float = field(default_factory=time.time)
    completed_at: float | None = None
    revision: int = 0

    def as_dict(self) -> dict[str, object]:
        """Serialize task observations without exposing ownership or resources."""
        end = self.finished_at if self.finished_at is not None else time.monotonic()
        return {
            "task_id": self.task_id,
            "revision": self.revision,
            "origin_message_id": self.origin_message_id,
            "origin_turn_id": self.origin_turn_id,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "label": self.label,
            "task_description": self.task_description,
            "state": self.state,
            "phase": self.phase,
            "elapsed_seconds": round(max(0.0, end - self.started_at), 1),
            "iteration": self.iteration,
            "tool_events": [dict(event) for event in self.tool_events],
            "usage": self.usage.to_dict() if self.usage is not None else None,
            "receipts": dict(self.receipts),
            "result": self.result,
            "partial": self.partial,
            "stop_reason": self.stop_reason,
            "error": self.error,
        }
