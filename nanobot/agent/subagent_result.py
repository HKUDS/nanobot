"""Structured result payload for background subagents."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

SubagentStatus = Literal["ok", "error", "partial", "timeout", "cancelled"]


@dataclass
class SubagentResult:
    """Normalized subagent result passed back to the main agent."""

    task_id: str
    label: str
    task: str
    status: SubagentStatus
    summary: str
    artifacts: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    error: str | None = None

    def to_payload(self) -> dict:
        """Serialize for transport via message metadata."""
        return {
            "type": "subagent_result",
            "task_id": self.task_id,
            "label": self.label,
            "task": self.task,
            "status": self.status,
            "summary": self.summary,
            "artifacts": self.artifacts,
            "notes": self.notes,
            "error": self.error,
        }

    @classmethod
    def from_payload(cls, payload: dict) -> "SubagentResult":
        """Deserialize from message metadata payload."""
        return cls(
            task_id=str(payload["task_id"]),
            label=str(payload["label"]),
            task=str(payload["task"]),
            status=payload["status"],
            summary=str(payload["summary"]),
            artifacts=list(payload.get("artifacts", [])),
            notes=list(payload.get("notes", [])),
            error=payload.get("error"),
        )
