"""Spawn tool for creating background subagents."""

from typing import TYPE_CHECKING, Any

from nanobot.agent.tools.base import Tool, tool_parameters
from nanobot.agent.tools.schema import StringSchema, IntegerSchema, tool_parameters_schema

if TYPE_CHECKING:
    from nanobot.agent.subagent import SubagentManager

# Default values matching AgentLoop defaults
_DEFAULT_MAX_ITERATIONS = 15
_DEFAULT_TIMEOUT_SECONDS = 300


@tool_parameters(
    tool_parameters_schema(
        task=StringSchema("The task for the subagent to complete"),
        label=StringSchema("Optional short label for the task (for display)"),
        max_iterations=IntegerSchema(
            description="Optional maximum model iterations for the subagent (default 15)",
            minimum=1, maximum=100,
        ),
        timeout_seconds=IntegerSchema(
            description="Optional maximum wall-clock time in seconds before the subagent is cancelled (default 300)",
            minimum=1, maximum=3600,
        ),
        expected_files=StringSchema(
            "Optional comma-separated list of file paths the subagent must create",
        ),
        required=["task"],
    )
)
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
        self._origin_channel = channel
        self._origin_chat_id = chat_id
        self._session_key = f"{channel}:{chat_id}"

    @property
    def name(self) -> str:
        return "spawn"

    @property
    def description(self) -> str:
        return (
            "Spawn a subagent to handle a task in the background. "
            "Use this for complex or time-consuming tasks that can run independently. "
            "The subagent will complete the task and report back when done. "
            "For deliverables or existing projects, inspect the workspace first "
            "and use a dedicated subdirectory when helpful."
        )

    async def execute(self, task: str, label: str | None = None, **kwargs: Any) -> str:
        """Spawn a subagent to execute the given task."""
        max_iterations = kwargs.get("max_iterations") or _DEFAULT_MAX_ITERATIONS
        timeout_seconds = kwargs.get("timeout_seconds") or _DEFAULT_TIMEOUT_SECONDS
        expected_files = kwargs.get("expected_files")
        if isinstance(expected_files, str):
            expected_files = [f.strip() for f in expected_files.split(",") if f.strip()]

        return await self._manager.spawn(
            task=task,
            label=label,
            origin_channel=self._origin_channel,
            origin_chat_id=self._origin_chat_id,
            session_key=self._session_key,
            max_iterations=max_iterations,
            timeout_seconds=timeout_seconds,
            expected_files=expected_files,
        )
