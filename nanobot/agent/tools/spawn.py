"""Spawn tool for creating background subagents."""

from typing import TYPE_CHECKING, Any

from nanobot.agent.tools.base import Tool

if TYPE_CHECKING:
    from nanobot.agent.subagent import SubagentManager


class SpawnTool(Tool):
    """Tool to spawn a subagent for background task execution."""

    def __init__(self, manager: "SubagentManager"):
        self._manager = manager
        self._origin_channel = "cli"
        self._origin_chat_id = "direct"
        self._session_key = "cli:direct"

    def set_context(self, channel: str, chat_id: str) -> None:
        """Set the origin context for subagent announcements."""
        self._origin_channel = channel
        self._origin_chat_id = chat_id
        self._session_key = f"{channel}:{chat_id}"

    @property
    def name(self) -> str:
        return "spawn"

    @property
    def description(self) -> str:
        base = (
            "Spawn a subagent to handle a task in the background. "
            "Use this for complex or time-consuming tasks that can run independently. "
            "The subagent will complete the task and report back when done."
        )
        if self._manager.subagent_configs:
            info_lines = ["\n\nAvailable subagents:"]
            for k, v in self._manager.subagent_configs.items():
                details = [f"Model: {v.model}"]
                if v.latency:
                    details.append(f"Latency: {v.latency}")
                if v.cost:
                    details.append(f"Cost: {v.cost}")
                info_lines.append(f"- {k}: {v.description} ({', '.join(details)})")
            return base + "\n".join(info_lines)
        return base

    @property
    def parameters(self) -> dict[str, Any]:
        props = {
            "task": {
                "type": "string",
                "description": "The task for the subagent to complete",
            },
            "label": {
                "type": "string",
                "description": "Optional short label for the task (for display)",
            },
        }

        if self._manager.subagent_configs:
            props["subagent_id"] = {
                "type": "string",
                "description": "Optional ID of a specific subagent to use.",
                "enum": list(self._manager.subagent_configs.keys()),
            }

        return {
            "type": "object",
            "properties": props,
            "required": ["task"],
        }

    async def execute(self, task: str, label: str | None = None, subagent_id: str | None = None, **kwargs: Any) -> str:
        """Spawn a subagent to execute the given task."""
        return await self._manager.spawn(
            task=task,
            label=label,
            subagent_id=subagent_id,
            origin_channel=self._origin_channel,
            origin_chat_id=self._origin_chat_id,
            session_key=self._session_key,
        )
