"""Delegation tools for multi-agent peer-to-peer task routing.

``DelegateTool`` lets any agent hand off a sub-task to another specialist
agent via the coordinator.  The coordinator re-routes the task to the
appropriate role, which executes a bounded tool-loop and writes its result
to the session scratchpad.

``DelegateParallelTool`` fans out multiple sub-tasks concurrently.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from nanobot.agent.tools.base import Tool, ToolResult

# Type alias for the dispatch callback wired by AgentLoop
DispatchFn = Callable[[str, str, str | None], Awaitable[str]]


class DelegateTool(Tool):
    """Delegate a sub-task to a specialist agent via the coordinator."""

    readonly = False

    def __init__(self) -> None:
        self._dispatch: DispatchFn | None = None

    def set_dispatch(self, fn: DispatchFn) -> None:
        """Wire the dispatch callback (called by AgentLoop during setup)."""
        self._dispatch = fn

    @property
    def name(self) -> str:
        return "delegate"

    @property
    def description(self) -> str:
        return (
            "Delegate a sub-task to a specialist agent. The coordinator routes "
            "the task to the best role and the result is written to the scratchpad."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "target_role": {
                    "type": "string",
                    "description": (
                        "The specialist role to delegate to (e.g. 'research', 'code'). "
                        "If unsure, leave empty and the coordinator will classify."
                    ),
                },
                "task": {
                    "type": "string",
                    "description": "Clear description of the sub-task to perform.",
                },
                "context": {
                    "type": "string",
                    "description": "Optional extra context or constraints for the sub-task.",
                },
            },
            "required": ["task"],
        }

    async def execute(  # type: ignore[override]
        self,
        *,
        task: str,
        target_role: str = "",
        context: str = "",
        **_: Any,
    ) -> ToolResult:
        if not self._dispatch:
            return ToolResult.fail("Delegation not available", error_type="config")

        try:
            result = await self._dispatch(target_role, task, context or None)
            return ToolResult.ok(result)
        except _CycleError as exc:
            return ToolResult.fail(str(exc), error_type="cycle")
        except Exception as exc:
            return ToolResult.fail(f"Delegation failed: {exc}", error_type="delegation")


class DelegateParallelTool(Tool):
    """Fan out multiple sub-tasks to specialist agents concurrently."""

    readonly = False

    def __init__(self) -> None:
        self._dispatch: DispatchFn | None = None

    def set_dispatch(self, fn: DispatchFn) -> None:
        self._dispatch = fn

    @property
    def name(self) -> str:
        return "delegate_parallel"

    @property
    def description(self) -> str:
        return (
            "Delegate multiple sub-tasks concurrently to specialist agents. "
            "Each sub-task is routed independently and results are written to the scratchpad."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "subtasks": {
                    "type": "array",
                    "description": "List of sub-tasks (max 5).",
                    "items": {
                        "type": "object",
                        "properties": {
                            "target_role": {
                                "type": "string",
                                "description": "Specialist role (optional).",
                            },
                            "task": {
                                "type": "string",
                                "description": "Sub-task description.",
                            },
                            "context": {
                                "type": "string",
                                "description": "Optional extra context or constraints.",
                            },
                        },
                        "required": ["task"],
                    },
                    "maxItems": 5,
                },
            },
            "required": ["subtasks"],
        }

    async def execute(self, *, subtasks: list[dict[str, str]], **_: Any) -> ToolResult:  # type: ignore[override]
        import asyncio

        if not self._dispatch:
            return ToolResult.fail("Delegation not available", error_type="config")

        if len(subtasks) > 5:
            return ToolResult.fail(
                "Maximum 5 parallel subtasks allowed", error_type="validation"
            )
        if not subtasks:
            return ToolResult.fail("At least one subtask required", error_type="validation")

        async def _run_one(st: dict[str, str]) -> str:
            role = st.get("target_role", "")
            task = st.get("task", "")
            ctx = st.get("context") or None
            return await self._dispatch(role, task, ctx)  # type: ignore[misc]

        results = await asyncio.gather(
            *[_run_one(st) for st in subtasks],
            return_exceptions=True,
        )

        parts: list[str] = []
        for i, (st, res) in enumerate(zip(subtasks, results), 1):
            task_label = st.get("task", "?")[:60]
            if isinstance(res, Exception):
                parts.append(f"[{i}] {task_label} → ERROR: {res}")
            else:
                parts.append(f"[{i}] {task_label} → {res}")

        return ToolResult.ok("\n".join(parts))


class _CycleError(Exception):
    """Raised when a delegation cycle is detected."""
