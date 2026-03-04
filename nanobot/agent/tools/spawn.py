"""Spawn tool for creating background subagents."""

import time
from typing import TYPE_CHECKING, Any

from nanobot.agent.tools.base import Tool

if TYPE_CHECKING:
    from nanobot.agent.subagent import SubagentManager


class SpawnTool(Tool):
    """Tool to spawn a subagent for background task execution."""

    # Deduplication: skip duplicate spawn calls within this time window (seconds)
    _DEDUP_WINDOW = 5.0

    def __init__(self, manager: "SubagentManager"):
        self._manager = manager
        self._origin_channel = "cli"
        self._origin_chat_id = "direct"
        self._session_key = "cli:direct"
        # Track recent spawn calls for deduplication: (task, label) -> timestamp
        self._recent_spawns: dict[tuple[str, str | None], float] = {}

    def set_context(self, channel: str, chat_id: str) -> None:
        """Set the origin context for subagent announcements."""
        self._origin_channel = channel
        self._origin_chat_id = chat_id
        self._session_key = f"{channel}:{chat_id}"

    def _is_duplicate(self, task: str, label: str | None) -> bool:
        """Check if this is a duplicate spawn call within the deduplication window."""
        now = time.time()
        key = (task, label)
        if key in self._recent_spawns:
            if now - self._recent_spawns[key] < self._DEDUP_WINDOW:
                return True
        self._recent_spawns[key] = now
        # Clean up old entries to prevent memory growth
        self._recent_spawns = {k: v for k, v in self._recent_spawns.items() if now - v < self._DEDUP_WINDOW}
        return False

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
            },
            "required": ["task"],
        }

    async def execute(self, task: str, label: str | None = None, **kwargs: Any) -> str:
        """Spawn a subagent to execute the given task."""
        # Deduplicate: skip if same task+label called within window
        if self._is_duplicate(task, label):
            return f"Skipped duplicate spawn for task: {label or 'unnamed'}"
        return await self._manager.spawn(
            task=task,
            label=label,
            origin_channel=self._origin_channel,
            origin_chat_id=self._origin_chat_id,
            session_key=self._session_key,
        )
