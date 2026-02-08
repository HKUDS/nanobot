"""Window task progress tool for showing task cards in the Window iOS app."""

import uuid
from typing import Any, Callable, Awaitable

from nanobot.agent.tools.base import Tool


class WindowTaskTool(Tool):
    """Tool to show task progress cards in the Window iOS app.

    The LLM calls this to:
    - create a visible task card with named steps
    - mark individual steps as completed/in-progress
    """

    def __init__(self):
        self._emit: Callable[[dict[str, Any]], Awaitable[None]] | None = None
        self._active_task_id: str | None = None
        self._active_steps: list[dict[str, str]] = []

    # -- wiring -----------------------------------------------------------

    def set_emit(self, emit: Callable[[dict[str, Any]], Awaitable[None]]) -> None:
        """Set async callback that sends a dict payload to the Window WS client."""
        self._emit = emit

    def get_active_task_id(self) -> str | None:
        return self._active_task_id

    def reset(self) -> None:
        self._active_task_id = None
        self._active_steps = []

    # -- Tool interface ----------------------------------------------------

    @property
    def name(self) -> str:
        return "window_task"

    @property
    def description(self) -> str:
        return (
            "Show a task progress card to the user in the Window app. "
            "Use this ONLY when performing a multi-step task (e.g. deploying, "
            "analysing, building, researching). Do NOT use it for simple "
            "conversational replies.\n\n"
            "Actions:\n"
            "  create_task  - Create a new task card with a title and a list of step names.\n"
            "  update_step  - Mark a step as completed or in_progress.\n"
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["create_task", "update_step"],
                    "description": "The action to perform.",
                },
                "title": {
                    "type": "string",
                    "description": "Task title (for create_task). Example: 'Deploying application'.",
                },
                "steps": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of step names (for create_task). Example: ['Pull code', 'Run tests', 'Deploy'].",
                },
                "step_index": {
                    "type": "integer",
                    "description": "Zero-based index of the step to update (for update_step).",
                },
                "status": {
                    "type": "string",
                    "enum": ["in_progress", "completed"],
                    "description": "New status for the step (for update_step).",
                },
            },
            "required": ["action"],
        }

    async def execute(self, action: str, **kwargs: Any) -> str:
        if action == "create_task":
            return await self._create_task(
                title=kwargs.get("title", "Working on it"),
                steps=kwargs.get("steps", []),
            )
        elif action == "update_step":
            return await self._update_step(
                step_index=kwargs.get("step_index", 0),
                status=kwargs.get("status", "completed"),
            )
        else:
            return f"Error: unknown action '{action}'"

    # -- internal ----------------------------------------------------------

    async def _create_task(self, title: str, steps: list[str]) -> str:
        if not self._emit:
            return "Task card not available (not connected via Window app)"

        task_id = f"task_{uuid.uuid4().hex[:12]}"
        self._active_task_id = task_id
        self._active_steps = [{"name": s, "status": "pending"} for s in steps]

        await self._emit(
            {
                "type": "task.created",
                "task_id": task_id,
                "title": f"Processing: {title}",
                "visibility": "show",
                "show_progress": True,
                "status": "in_progress",
                "progress": 0.0,
                "steps": list(self._active_steps),
            }
        )
        return f"Task card shown to user with {len(steps)} steps."

    async def _update_step(self, step_index: int, status: str) -> str:
        if not self._emit or not self._active_task_id:
            return "No active task card"

        if step_index < 0 or step_index >= len(self._active_steps):
            return f"Invalid step index {step_index} (have {len(self._active_steps)} steps)"

        self._active_steps[step_index]["status"] = status

        # Calculate progress
        completed = sum(1 for s in self._active_steps if s["status"] == "completed")
        total = len(self._active_steps)
        progress = completed / total if total > 0 else 0.0

        await self._emit(
            {
                "type": "task.updated",
                "task_id": self._active_task_id,
                "progress": progress,
                "steps": list(self._active_steps),
            }
        )
        return f"Step {step_index} marked as {status}. Progress: {completed}/{total}."
