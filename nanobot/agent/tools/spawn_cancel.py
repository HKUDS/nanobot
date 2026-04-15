"""Spawn cancel tool for cancelling running subagents."""

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

    def __init__(self, manager: "SubagentManager"):
        self._manager = manager

    @property
    def name(self) -> str:
        return "spawn_cancel"

    @property
    def description(self) -> str:
        return (
            "Cancel a running subagent by its task ID. The subagent will be "
            "stopped gracefully. Use spawn_status first to see running tasks "
            "and their IDs."
        )

    async def execute(self, task_id: str, **kwargs: Any) -> str:
        """Cancel a subagent by its task ID."""
        return await self._manager.cancel_by_task_id(task_id)
