"""Delegate tool for routing tasks to specialist agents."""

from typing import TYPE_CHECKING, Any

from nanobot.agent.tools.base import Tool

if TYPE_CHECKING:
    from nanobot.agent.specialist import SpecialistRunner


class DelegateTool(Tool):
    """Tool to delegate a task to a specialist agent."""

    def __init__(self, runner: "SpecialistRunner"):
        self._runner = runner
        self._session_key: str | None = None

    def set_context(self, channel: str, chat_id: str) -> None:
        """Set the session key for passing conversation context to the specialist."""
        self._session_key = f"{channel}:{chat_id}"

    @property
    def name(self) -> str:
        return "delegate"

    @property
    def description(self) -> str:
        return (
            "Delegate a task to a specialist agent. The specialist will process "
            "the task with access to conversation context and shared memory, "
            "and return its result. Use this when a query matches a specialist's domain."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "specialist": {
                    "type": "string",
                    "description": "Name of the specialist to delegate to",
                },
                "task": {
                    "type": "string",
                    "description": "The task or question for the specialist",
                },
            },
            "required": ["specialist", "task"],
        }

    async def execute(self, specialist: str, task: str, **kwargs: Any) -> str:
        """Delegate the task to the named specialist and return the result."""
        try:
            return await self._runner.run(
                name=specialist,
                task=task,
                session_key=self._session_key,
            )
        except Exception as e:
            return f"Error delegating to specialist '{specialist}': {e}"
