"""Spawn status tool — list running subagent tasks."""

from __future__ import annotations

from typing import Any

from nanobot.agent.tools.base import Tool


class SpawnStatusTool(Tool):
    """Check the status of spawned subagents."""

    def __init__(self, subagent_manager) -> None:
        self._manager = subagent_manager

    @property
    def name(self) -> str:
        return "spawn_status"

    @property
    def description(self) -> str:
        return (
            "Check the status of spawned subagents. "
            "Returns task ID, label, elapsed time, and status (running/done/error). "
            "Use without arguments to list all subagents, or pass a specific task_id."
        )

    async def execute(self, task_id: str | None = None, **kwargs: Any) -> str:
        if task_id:
            return self._manager.get_task_status(task_id)
        return self._manager.get_all_status()

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "Optional: task ID of a specific subagent to check",
                },
            },
        }
