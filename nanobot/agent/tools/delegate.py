"""Delegation tools for multi-agent peer-to-peer task routing.

``DelegateTool`` lets any agent hand off a sub-task to another specialist
agent via the coordinator.  The coordinator re-routes the task to the
appropriate role, which executes a bounded tool-loop and writes its result
to the session scratchpad.

``DelegateParallelTool`` fans out multiple sub-tasks concurrently.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from nanobot.agent.failure import _CycleError
from nanobot.agent.tools.base import Tool, ToolResult


@dataclass(slots=True)
class DelegationResult:
    """Structured result from a delegated sub-task."""

    content: str
    tools_used: list[str]

    @property
    def grounded(self) -> bool:
        """True if the specialist used at least one tool (evidence-backed)."""
        return len(self.tools_used) > 0


# Type alias for the dispatch callback wired by AgentLoop
DispatchFn = Callable[[str, str, str | None], Awaitable[DelegationResult]]

# Keywords that signal an investigation-type task where tool use is expected
_INVESTIGATION_RE = re.compile(
    r"\b(search|find|look\s*up|check|verify|investigate|retrieve|fetch|query|inspect)\b",
    re.IGNORECASE,
)


# Type alias for a callback that returns available delegation role names
AvailableRolesFn = Callable[[], list[str]]


class DelegateTool(Tool):
    """Delegate a sub-task to a specialist agent via the coordinator."""

    readonly = False

    def __init__(self) -> None:
        self._dispatch: DispatchFn | None = None
        self._available_roles_fn: AvailableRolesFn | None = None

    def set_dispatch(self, fn: DispatchFn) -> None:
        """Wire the dispatch callback (called by AgentLoop during setup)."""
        self._dispatch = fn

    def set_available_roles_fn(self, fn: AvailableRolesFn) -> None:
        """Wire a callback that returns the current list of valid role names."""
        self._available_roles_fn = fn

    def check_available(self) -> tuple[bool, str | None]:
        if not self._dispatch:
            return False, "Delegation not configured"
        return True, None

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

        # Validate target_role against known roles
        target_role = target_role.strip()
        if target_role and self._available_roles_fn:
            available = self._available_roles_fn()
            if available and target_role not in available:
                return ToolResult.fail(
                    f"Unknown delegation role '{target_role}'. "
                    f"Available roles: {', '.join(available)}",
                    error_type="unknown_role",
                )

        try:
            dr = await self._dispatch(target_role, task, context or None)
            return self._format_result(dr, task)
        except _CycleError as exc:
            return ToolResult.fail(str(exc), error_type="cycle")
        except Exception as exc:  # crash-barrier: delegation dispatch callback
            return ToolResult.fail(f"Delegation failed: {exc}", error_type="delegation")

    @staticmethod
    def _format_result(dr: DelegationResult, task: str) -> ToolResult:
        """Build a ToolResult with attestation metadata."""
        tools_note = f"[tools_used={len(dr.tools_used)}, grounded={dr.grounded}]"
        if dr.grounded:
            return ToolResult.ok(f"{tools_note}\n{dr.content}")
        # Ungrounded result — warn if the task looks investigative
        if _INVESTIGATION_RE.search(task):
            return ToolResult.ok(
                f"{tools_note}\n"
                "⚠️ This result was generated without tool use and may not be "
                f"verified.\n{dr.content}"
            )
        return ToolResult.ok(f"{tools_note}\n{dr.content}")


class DelegateParallelTool(Tool):
    """Fan out multiple sub-tasks to specialist agents concurrently."""

    readonly = False

    def __init__(self) -> None:
        self._dispatch: DispatchFn | None = None
        self._available_roles_fn: AvailableRolesFn | None = None

    def set_dispatch(self, fn: DispatchFn) -> None:
        self._dispatch = fn

    def set_available_roles_fn(self, fn: AvailableRolesFn) -> None:
        """Wire a callback that returns the current list of valid role names."""
        self._available_roles_fn = fn

    def check_available(self) -> tuple[bool, str | None]:
        if not self._dispatch:
            return False, "Delegation not configured"
        return True, None

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
        if not self._dispatch:
            return ToolResult.fail("Delegation not available", error_type="config")

        if len(subtasks) > 5:
            return ToolResult.fail("Maximum 5 parallel subtasks allowed", error_type="validation")
        if not subtasks:
            return ToolResult.fail("At least one subtask required", error_type="validation")

        # Validate all target_role values upfront
        if self._available_roles_fn:
            available = self._available_roles_fn()
            if available:
                invalid: list[tuple[int, str]] = []
                for i, st in enumerate(subtasks, 1):
                    role = st.get("target_role", "").strip()
                    if role and role not in available:
                        invalid.append((i, role))
                if invalid:
                    lines = [f"Subtask [{i}]: unknown role '{r}'" for i, r in invalid]
                    lines.append(f"Available roles: {', '.join(available)}")
                    return ToolResult.fail("\n".join(lines), error_type="unknown_role")

        async def _run_one(st: dict[str, str]) -> DelegationResult:
            role = st.get("target_role", "").strip()
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
            elif isinstance(res, DelegationResult):
                tag = "✓" if res.grounded else "⚠ ungrounded"
                parts.append(f"[{i}] ({tag}) {task_label} → {res.content}")
            else:
                parts.append(f"[{i}] {task_label} → {res}")

        return ToolResult.ok("\n".join(parts))


__all__ = [
    "DelegateTool",
    "DelegateParallelTool",
    "DelegationResult",
    "_CycleError",
]
