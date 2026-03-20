"""Checkpoint store for subagent error recovery.

Saves subagent state after each successful tool execution so that
failed tasks can be resumed from the last checkpoint instead of
replaying from scratch.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.utils.helpers import ensure_dir


@dataclass
class CheckpointState:
    """Snapshot of subagent state at a checkpoint."""

    task_id: str
    iteration: int
    messages: list[dict[str, Any]]
    task: str
    label: str
    origin: dict[str, str]
    completed_tools: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CheckpointState:
        return cls(
            task_id=data["task_id"],
            iteration=data["iteration"],
            messages=data["messages"],
            task=data["task"],
            label=data["label"],
            origin=data["origin"],
            completed_tools=data.get("completed_tools", []),
        )


class CheckpointStore:
    """Manages checkpoint persistence for subagent tasks.

    Checkpoints are stored as JSON files under workspace/.tasks/{task_id}/checkpoint.json.
    Each save overwrites the previous checkpoint for that task.
    """

    def __init__(self, workspace: Path):
        self._tasks_dir = ensure_dir(workspace / ".tasks")

    def _checkpoint_path(self, task_id: str) -> Path:
        return self._tasks_dir / task_id / "checkpoint.json"

    def save(self, state: CheckpointState) -> None:
        """Save a checkpoint for the given task."""
        path = self._checkpoint_path(state.task_id)
        ensure_dir(path.parent)
        path.write_text(
            json.dumps(state.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.debug(
            "Checkpoint saved for task {} at iteration {}",
            state.task_id,
            state.iteration,
        )

    def load(self, task_id: str) -> CheckpointState | None:
        """Load the latest checkpoint for a task, or None if none exists."""
        path = self._checkpoint_path(task_id)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return CheckpointState.from_dict(data)
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.warning("Corrupt checkpoint for task {}: {}", task_id, e)
            return None

    def cleanup(self, task_id: str) -> None:
        """Remove checkpoint files for a completed task."""
        task_dir = self._tasks_dir / task_id
        if task_dir.exists():
            for f in task_dir.iterdir():
                f.unlink()
            task_dir.rmdir()
            logger.debug("Cleaned up checkpoint for task {}", task_id)

    def has_checkpoint(self, task_id: str) -> bool:
        """Check whether a checkpoint exists for the given task."""
        return self._checkpoint_path(task_id).exists()
