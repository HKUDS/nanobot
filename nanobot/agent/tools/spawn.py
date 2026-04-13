"""Spawn tool for creating background subagents."""

from typing import TYPE_CHECKING, Any

from nanobot.agent.tools.base import Tool
from nanobot.providers.base import LLMProvider

if TYPE_CHECKING:
    from nanobot.agent.subagent import SubagentManager


class SpawnTool(Tool):
    """Tool to spawn a subagent for background task execution."""

    def __init__(self, manager: "SubagentManager"):
        self._manager = manager
        self._origin_channel = "cli"
        self._origin_chat_id = "direct"
        self._session_key = "cli:direct"
        self._provider: LLMProvider | None = None
        self._model: str | None = None

    def set_context(
        self,
        channel: str,
        chat_id: str,
        provider: LLMProvider | None = None,
        model: str | None = None,
    ) -> None:
        """Set the origin context for subagent announcements."""
        self._origin_channel = channel
        self._origin_chat_id = chat_id
        self._session_key = f"{channel}:{chat_id}"
        self._provider = provider
        self._model = model

    @property
    def name(self) -> str:
        return "spawn"

    @property
    def description(self) -> str:
        return (
            "Spawn a subagent to handle a task in the background. "
            "Use this for complex or time-consuming tasks that can run independently. "
            "You can include the task goal, constraints, relevant paths, and done criteria. "
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
                "goal": {
                    "type": "string",
                    "description": "Optional higher-level goal explaining why the task matters",
                },
                "constraints": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional constraints the subagent must follow",
                },
                "relevant_paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional files or directories the subagent should prioritize",
                },
                "done_when": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional completion criteria for the task",
                },
            },
            "required": ["task"],
        }

    async def execute(
        self,
        task: str,
        label: str | None = None,
        goal: str | None = None,
        constraints: list[str] | None = None,
        relevant_paths: list[str] | None = None,
        done_when: list[str] | None = None,
        **kwargs: Any,
    ) -> str:
        """Spawn a subagent to execute the given task."""
        return await self._manager.spawn(
            task=task,
            label=label,
            goal=goal,
            constraints=constraints or [],
            relevant_paths=relevant_paths or [],
            done_when=done_when or [],
            origin_channel=self._origin_channel,
            origin_chat_id=self._origin_chat_id,
            session_key=self._session_key,
            provider=self._provider,
            model=self._model,
        )
