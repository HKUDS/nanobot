"""Spawn cancel tool — cancel a running subagent by task ID."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nanobot.agent.tools.base import Tool, tool_parameters
from nanobot.agent.tools.schema import StringSchema, tool_parameters_schema

if TYPE_CHECKING:
    from nanobot.agent.subagent import SubagentManager


@tool_parameters(
    tool_parameters_schema(
        task_id=StringSchema("Task ID of the subagent to cancel"),
        required=["task_id"],
    )
)
class SpawnCancelTool(Tool):
    """Cancel a running subagent by its task ID."""

    def __init__(self, manager: "SubagentManager") -> None:
        self._manager = manager

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
