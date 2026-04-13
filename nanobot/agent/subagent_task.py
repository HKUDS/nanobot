"""Structured task contract for background subagents."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SubagentTask:
    """Minimal task contract passed from the main agent to a subagent."""

    task: str
    label: str | None = None
    goal: str | None = None
    constraints: list[str] = field(default_factory=list)
    relevant_paths: list[str] = field(default_factory=list)
    done_when: list[str] = field(default_factory=list)

    def display_label(self) -> str:
        """Return the UI label shown for this task."""
        if self.label:
            return self.label
        return self.task[:30] + ("..." if len(self.task) > 30 else "")
