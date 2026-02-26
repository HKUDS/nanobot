"""Spawn tool for creating background subagents."""

from typing import Any, TYPE_CHECKING

from nanobot.agent.tools.base import Tool

if TYPE_CHECKING:
    from nanobot.agent.subagent import SubagentManager
    from nanobot.providers.base import LLMProvider


class SpawnTool(Tool):
    """Tool to spawn a subagent for background task execution."""
    
    def __init__(self, manager: "SubagentManager"):
        self._manager = manager
        self._origin_channel = "cli"
        self._origin_chat_id = "direct"
        self._session_key = "cli:direct"
        # Profile-inherited defaults (set per-message from active agent profile)
        self._profile_model: str | None = None
        self._profile_temperature: float | None = None
        self._profile_max_tokens: int | None = None
        self._profile_provider: "LLMProvider | None" = None


    def set_context(self, channel: str, chat_id: str) -> None:
        """Set the origin context for subagent announcements."""
        self._origin_channel = channel
        self._origin_chat_id = chat_id
        self._session_key = f"{channel}:{chat_id}"

    def set_profile_context(
        self,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        provider: "LLMProvider | None" = None,
    ) -> None:
        """Set inherited profile defaults for spawned subagents.

        Called before each agent loop run so subagents inherit the active
        agent profile's settings unless the agent explicitly overrides them.
        """
        self._profile_model = model
        self._profile_temperature = temperature
        self._profile_max_tokens = max_tokens
        self._profile_provider = provider
    
    @property
    def name(self) -> str:
        return "spawn"
    
    @property
    def description(self) -> str:
        return (
            "Spawn a subagent to handle a task in the background. "
            "Use this for complex or time-consuming tasks that can run independently. "
            "The subagent will complete the task and report back when done. "
            "Leave 'model' unset — the subagent will use the same default model as you. "
            "Only override 'model' if you have a specific reason and know the provider is configured."
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
                "model": {
                    "type": "string",
                    "description": (
                        "Model override for this subagent. "
                        "LEAVE EMPTY in almost all cases — the subagent will inherit the current default model. "
                        "Only specify if you have a concrete reason to use a different model "
                        "AND you are certain that model's provider API key is configured. "
                        "Specifying an unconfigured model will cause the task to fail silently."
                    ),
                },
            },
            "required": ["task"],
        }

    async def execute(self, task: str, label: str | None = None, model: str | None = None, **kwargs: Any) -> str:
        """Spawn a subagent to execute the given task."""
        # Tool arg > profile inherited > SubagentManager default
        return await self._manager.spawn(
            task=task,
            label=label,
            origin_channel=self._origin_channel,
            origin_chat_id=self._origin_chat_id,
            model=model or self._profile_model,
            temperature=self._profile_temperature,
            max_tokens=self._profile_max_tokens,
            provider=self._profile_provider,
            session_key=self._session_key,
        )
