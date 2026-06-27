"""Explicit mailbox tools for subagent coordination."""

from __future__ import annotations

from contextvars import ContextVar
from typing import TYPE_CHECKING, Any

from nanobot.agent.mailbox import MailboxRead, TaskSnapshot
from nanobot.agent.tools.base import Tool, tool_parameters
from nanobot.agent.tools.context import ContextAware, RequestContext
from nanobot.agent.tools.schema import NumberSchema, StringSchema, tool_parameters_schema

if TYPE_CHECKING:
    from nanobot.agent.subagent import SubagentManager


def _normalize_task_id(task_id: str | None) -> str | None:
    if task_id is None:
        return None
    task_id = task_id.strip()
    return task_id or None


def _truncate(text: str, limit: int = 120) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 3] + "..."


class _SubagentMailboxTool(Tool, ContextAware):
    """Shared context plumbing for subagent mailbox tools."""

    def __init__(self, manager: "SubagentManager"):
        self._manager = manager
        self._session_key: ContextVar[str] = ContextVar(
            f"{self.__class__.__name__}_session_key",
            default="cli:direct",
        )

    @classmethod
    def enabled(cls, ctx: Any) -> bool:
        return getattr(ctx, "subagent_manager", None) is not None

    @classmethod
    def create(cls, ctx: Any) -> Tool:
        return cls(manager=ctx.subagent_manager)

    def set_context(self, ctx: RequestContext) -> None:
        self._session_key.set(ctx.session_key or f"{ctx.channel}:{ctx.chat_id}")


@tool_parameters(
    tool_parameters_schema(
        task_id=StringSchema(
            "Optional subagent task id. Omit to list all subagent tasks for this session.",
            nullable=True,
        ),
    )
)
class PollSubagentsTool(_SubagentMailboxTool):
    """Non-blocking task status check."""

    @property
    def name(self) -> str:
        return "poll_subagents"

    @property
    def description(self) -> str:
        return (
            "Check subagent task status without blocking. Use this to see whether a "
            "spawned subagent is still running or has a result ready to consume."
        )

    @property
    def read_only(self) -> bool:
        return True

    async def execute(self, task_id: str | None = None, **_: Any) -> str:
        task_id = _normalize_task_id(task_id)
        session_key = self._session_key.get()
        snapshots = await self._manager.poll(session_key, task_id=task_id)
        if not snapshots:
            if task_id:
                return f"Subagent task {task_id} not found for this session."
            return "No subagent tasks found for this session."
        return self._format_snapshots(snapshots)

    @staticmethod
    def _format_snapshots(snapshots: list[TaskSnapshot]) -> str:
        lines = ["Subagent task status:"]
        for snapshot in snapshots:
            state = snapshot.state
            if snapshot.result_status and snapshot.consumed_at is None:
                state = f"{state}, result ready"
            elif snapshot.consumed_at is not None:
                state = f"{state}, result consumed"
            lines.append(
                f"- id: {snapshot.task_id} | label: {snapshot.label} | "
                f"status: {state} | task: {_truncate(snapshot.task)}"
            )
        return "\n".join(lines)


@tool_parameters(
    tool_parameters_schema(
        task_id=StringSchema(
            "Optional subagent task id. Omit to consume the next ready result.",
            nullable=True,
        ),
        timeout_seconds=NumberSchema(
            description="How long to wait for a result before returning. Defaults to 30 seconds.",
            minimum=0.0,
            maximum=300.0,
        ),
    )
)
class WaitSubagentsTool(_SubagentMailboxTool):
    """Wait for and consume one task result."""

    @property
    def name(self) -> str:
        return "wait_subagents"

    @property
    def description(self) -> str:
        return (
            "Wait for a subagent result and consume it once. Use this after spawn "
            "when you need the worker's result before continuing."
        )

    async def execute(
        self,
        task_id: str | None = None,
        timeout_seconds: float = 30.0,
        **_: Any,
    ) -> str:
        task_id = _normalize_task_id(task_id)
        read = await self._manager.wait_for_result(
            self._session_key.get(),
            task_id=task_id,
            timeout_seconds=timeout_seconds,
        )
        return self._format_read(read, task_id)

    @staticmethod
    def _format_read(read: MailboxRead, requested_task_id: str | None) -> str:
        if read.state == "not_found":
            target = f" {requested_task_id}" if requested_task_id else ""
            return f"Subagent task{target} not found for this session."
        if read.state == "timeout":
            target = f" {read.task.task_id}" if read.task is not None else ""
            return f"Timed out waiting for subagent task{target}."
        if read.state == "consumed":
            target = f" {read.task.task_id}" if read.task is not None else ""
            return f"Subagent result for task{target} was already consumed."
        if read.result is None or read.task is None:
            return "No subagent result is ready."

        status_text = {
            "ok": "completed",
            "error": "failed",
            "cancelled": "cancelled",
        }.get(read.result.status, read.result.status)
        return (
            f"Subagent result for [{read.result.label}] "
            f"(id: {read.result.task_id}, status: {status_text}).\n\n"
            f"Task: {read.result.task}\n\n"
            f"Result:\n{read.result.content}"
        )


@tool_parameters(
    tool_parameters_schema(
        task_id=StringSchema("Subagent task id to cancel"),
        required=["task_id"],
    )
)
class CancelSubagentTool(_SubagentMailboxTool):
    """Cancel one running task."""

    @property
    def name(self) -> str:
        return "cancel_subagent"

    @property
    def description(self) -> str:
        return (
            "Cancel a running subagent task and record a cancelled mailbox state. "
            "Use this only when the delegated task is no longer needed."
        )

    async def execute(self, task_id: str, **_: Any) -> str:
        task_id = _normalize_task_id(task_id)
        if task_id is None:
            return "Error: task_id is required."
        state = await self._manager.cancel_task(task_id, session_key=self._session_key.get())
        if state == "cancelled":
            return f"Cancelled subagent task {task_id}."
        if state == "not_found":
            return f"Subagent task {task_id} not found for this session."
        if state in {"completed", "failed"}:
            return (
                f"Subagent task {task_id} already {state}; "
                "use wait_subagents to consume its result if needed."
            )
        if state == "cancelled":
            return f"Subagent task {task_id} is already cancelled."
        return f"Subagent task {task_id} is {state}."
