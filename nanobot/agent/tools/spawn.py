"""Spawn tool for creating background subagents."""

from typing import Any, TYPE_CHECKING, TypedDict

from nanobot.agent.tools.base import Tool

if TYPE_CHECKING:
    from nanobot.agent.subagent import SubagentManager

class SubagentEntry(TypedDict):
    manager: "SubagentManager"
    role: str

class SpawnTool(Tool):
    """
    Tool to spawn a subagent for background task execution.
    
    The subagent runs asynchronously and announces its result back
    to the main agent when complete.
    """
    
    def __init__(self, subagents: dict[str, SubagentEntry]):
        self._subagents = subagents
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
        model_info = []
        available_models = []
        for model_name, entry in self._subagents.items():
            role = entry.get("role", "general tasks")
            model_info.append(f"- {model_name}: {role}")
            available_models.append(model_name)
        model_description = "Optional model to use for the subagent based on specific tasks.\nAvailable models and their roles:\n" + "\n".join(model_info)
        
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
                    "enum": available_models,
                    "description": model_description,
                }
            },
            "required": ["task"],
        }
    
    async def execute(self, task: str, label: str | None = None, **kwargs: Any) -> str:
        """Spawn a subagent to execute the given task."""
        media = kwargs.get("media", None)
        model = kwargs.get("model", None)
        entry = self._subagents.get(model) or self._subagents.get("default")
        if not entry:
            raise RuntimeError("No suitable subagent manager found.")

        sub_manager = entry["manager"]
        return await sub_manager.spawn(
            task=task,
            label=label,
            media=media,
            origin_channel=self._origin_channel,
            origin_chat_id=self._origin_chat_id,
        )
