"""Spawn cancel tool — cancel a running subagent by task ID."""

from __future__ import annotations

from typing import Any

from nanobot.agent.tools.base import Tool


class SpawnCancelTool(Tool):
    """Cancel a running subagent by its task ID."""

    def __init__(self, subagent_manager) -> None:
        self._manager = subagent_manager

    @property
    def name(self) -> str:
        return "spawn_cancel"

    @property
    def description(self) -> str:
        return (
            "Cancel a running subagent by its task ID. "
            "Use spawn_status first to see running tasks and their IDs."
        )

    async def execute(self, task_id: str, **kwargs: Any) -> str:
        if not task_id:
            return "Error: task_id is required."
        count = await self._manager.cancel_by_id(task_id)
        if count > 0:
            return f"Cancelled subagent {task_id}."
        return f"No running subagent found with ID {task_id}."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "Task ID of the subagent to cancel",
                },
            },
            "required": ["task_id"],
        }
