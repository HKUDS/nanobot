"""Delegate tool for calling named agents synchronously."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Awaitable, Callable

from nanobot.agent.tools.base import Tool

if TYPE_CHECKING:
    pass


class DelegateTool(Tool):
    """Delegate a task to a named agent and get the result synchronously."""

    def __init__(
        self,
        run_callback: Callable[[str, str, str, str], Awaitable[str]],
        list_callback: Callable[[], list[str]],
    ):
        self._run = run_callback  # (agent_name, task, channel, chat_id) -> result
        self._list = list_callback  # () -> [agent_name, ...]
        self._origin_channel = "cli"
        self._origin_chat_id = "direct"

    def set_context(self, channel: str, chat_id: str) -> None:
        self._origin_channel = channel
        self._origin_chat_id = chat_id

    @property
    def name(self) -> str:
        return "delegate"

    @property
    def description(self) -> str:
        return (
            "Delegate a task to a named agent. The agent processes the task with its own "
            "context and memory, and returns the result. Use this when the user asks you to "
            "have a specific agent handle something, e.g. '让小b帮我做xxx'."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "agent": {
                    "type": "string",
                    "description": "Name of the agent to delegate to",
                },
                "task": {
                    "type": "string",
                    "description": "The task or message to send to the agent",
                },
            },
            "required": ["agent", "task"],
        }

    async def execute(self, agent: str, task: str, **kwargs: Any) -> str:
        available = self._list()
        if not available:
            return "No named agents available. Use manage_agents to create one first."
        if agent not in available:
            return f"Agent '{agent}' not found. Available agents: {', '.join(available)}"
        return await self._run(agent, task, self._origin_channel, self._origin_chat_id)
