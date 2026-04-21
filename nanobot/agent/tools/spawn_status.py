"""Spawn status and cancel tools for managing background subagents."""

from typing import TYPE_CHECKING, Any

from nanobot.agent.tools.base import Tool, tool_parameters
from nanobot.agent.tools.schema import StringSchema, tool_parameters_schema

if TYPE_CHECKING:
    from nanobot.agent.subagent import SubagentManager


@tool_parameters(
    tool_parameters_schema(
        task_id=StringSchema("Optional task ID to check status of specific subagent (omit to list all)"),
        required=[],
    )
)
class SpawnStatusTool(Tool):
    """Tool to check the status of spawned subagents."""

    def __init__(self, manager: "SubagentManager"):
        self._manager = manager

    @property
    def name(self) -> str:
        return "spawn_status"

    @property
    def description(self) -> str:
        return (
            "Check the status of spawned subagents. Returns task ID, label, "
            "elapsed time, and status (running/done/error). "
            "Use without arguments to list all subagents, or pass a specific task_id."
        )

    async def execute(self, **kwargs: Any) -> str:
        task_id = kwargs.get("task_id")
        return self._manager.get_status_summary(task_id=task_id)


@tool_parameters(
    tool_parameters_schema(
        task_id=StringSchema("Task ID of the subagent to cancel"),
        required=["task_id"],
    )
)
class SpawnCancelTool(Tool):
    """Tool to cancel a running subagent."""

    def __init__(self, manager: "SubagentManager"):
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
        return await self._manager.cancel_task(task_id)
