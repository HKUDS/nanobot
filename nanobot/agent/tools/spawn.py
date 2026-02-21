"""Spawn tool for creating background subagents."""

from typing import Any, TYPE_CHECKING

from nanobot.agent.tools.base import Tool

if TYPE_CHECKING:
    from nanobot.agent.subagent import SubagentManager


class SpawnTool(Tool):
    """
    Tool to spawn a subagent for background task execution.
    
    The subagent runs asynchronously and announces its result back
    to the main agent when complete.
    """
    
    def __init__(self, manager: "SubagentManager"):
        self._manager = manager
        self._origin_channel = "cli"
        self._origin_chat_id = "direct"
    
    def set_context(self, channel: str, chat_id: str) -> None:
        """Set the origin context for subagent announcements."""
        self._origin_channel = channel
        self._origin_chat_id = chat_id
    
    @property
    def name(self) -> str:
        return "spawn"
    
    @property
    def description(self) -> str:
        return (
            "Spawn a subagent to handle a task in the background. "
            "Use this for complex or time-consuming tasks that can run independently. "
            "The subagent will complete the task and report back when done."
        )
    
    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "The task for the subagent to complete",
                },
                "label": {
                    "type": "string",
                    "description": "Optional short label for the task (for display)",
                },
                "media": {
                    "type": "array",
                    "description": "Optional media files to attach to the task, e.g. images or videos",
                },
                "model": {
                    "type": "string",
                    "description": "Optional model to use for the subagent based on specific tasks",
                }
            },
            "required": ["task"],
        }
    
    async def execute(self, task: str, label: str | None = None, **kwargs: Any) -> str:
        """Spawn a subagent to execute the given task."""
        media = kwargs.get("media", [])
        model = kwargs.get("model", None)
        if isinstance(self._manager, dict):
            sub_manager = self._manager.get(model, self._manager.get("default"))
            return await sub_manager.spawn(
                task=task,
                label=label,
                media=media,
                origin_channel=self._origin_channel,
                origin_chat_id=self._origin_chat_id,
            )
        else:
            return await self._manager.spawn(
                task=task,
                label=label,
                media=media,
                origin_channel=self._origin_channel,
                origin_chat_id=self._origin_chat_id,
            )