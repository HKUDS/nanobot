"""Spawn status tool for checking running/completed subagents."""

from typing import TYPE_CHECKING, Any

from nanobot.agent.tools.base import Tool, tool_parameters
from nanobot.agent.tools.schema import StringSchema, tool_parameters_schema

if TYPE_CHECKING:
    from nanobot.agent.subagent import SubagentManager


@tool_parameters(
    tool_parameters_schema(
        task_id=StringSchema("Optional task ID to check a specific subagent (omit to list all)"),
    )
)
class SpawnStatusTool(Tool):
    """Check the status of spawned subagents."""

    def __init__(self, manager: "SubagentManager"):
        self._manager = manager

    @property
    def name(self) -> str:
        return "spawn_status"

    @property
    def description(self) -> str:
        return (
            "Check the status of spawned subagents. Returns task ID, label, "
            "elapsed time, and status (running/done/error). Use without arguments "
            "to list all subagents, or pass a specific task_id."
        )

    async def execute(self, **kwargs: Any) -> str:
        """Return status of running or recently completed subagents."""
        task_id = kwargs.get("task_id")
        return self._manager.get_task_status(task_id)
