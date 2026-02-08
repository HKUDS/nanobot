from nanobot.agent.tools.base import Tool
from typing import Any


class CancelSubagentTool(Tool):
    """Cancel a running background subagent by ID."""

    def __init__(self, subagents):
        self.subagents = subagents

    @property
    def name(self) -> str:
        return "cancel_subagent"

    @property
    def description(self) -> str:
        return "Cancel a running background subagent by its task ID."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "ID of the subagent task to cancel"
                }
            },
            "required": ["task_id"]
        }

    async def execute(self, task_id: str, **kwargs: Any) -> str:
        success = self.subagents.cancel(task_id)
        if success:
            return f"Subagent {task_id} cancelled successfully."
        return f"No running subagent found with id {task_id}."