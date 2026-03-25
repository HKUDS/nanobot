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

    def set_context(self, channel: str, chat_id: str, session_key: str | None = None) -> None:
        """Set the origin context for subagent announcements."""
        self._origin_channel = channel
        self._origin_chat_id = chat_id
        self._session_key = session_key or f"{channel}:{chat_id}"

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
                "task": {"type": "string", "description": "The task for the subagent to complete"},
                "label": {"type": "string", "description": "Optional short label (for display)"},
                "role": {"type": "string", "description": "Optional registered role name"},
                "model": {"type": "string", "description": "Optional model override"},
                "allowed_tools": {
                    "type": "array", "items": {"type": "string"},
                    "description": "Optional tool subset (default: all tools)",
                },
            },
            "required": ["task"],
        }

    async def execute(self, task: str, label: str | None = None, *,
                      role: str | None = None, model: str | None = None,
                      allowed_tools: list[str] | None = None, **kw: Any) -> str:
        """Spawn a subagent to execute the given task."""
        return await self._manager.spawn(
            task=task, label=label,
            origin_channel=self._origin_channel, origin_chat_id=self._origin_chat_id,
            session_key=self._session_key, role=role, model=model,
            allowed_tools=allowed_tools,
        )


class CheckAgentsTool(Tool):
    """Tool to check progress of running / recently completed subagents."""

    def __init__(self, manager: "SubagentManager"):
        self._manager = manager

    @property
    def name(self) -> str:
        return "check_agents"

    @property
    def description(self) -> str:
        return (
            "Check the real-time progress of all running (and recently completed) subagents. "
            "Use this when the user asks about subagent status or progress."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {"type": "object", "properties": {
            "task_id": {"type": "string", "description": "Check a specific subagent by ID. Omit to show all."},
        }, "required": []}

    async def execute(self, task_id: str | None = None, **kw: Any) -> str:
        if task_id:
            p = self._manager.get_progress(task_id)
            if not p:
                ids = ", ".join(self._manager.get_running_ids()) or "(none)"
                return f"No subagent found with id '{task_id}'. Active: {ids}"
            return p.summary()
        return self._manager.get_status_report()
