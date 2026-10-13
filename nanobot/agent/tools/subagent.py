"""Tool for creating, messaging, cancelling, and inspecting session-owned tasks."""

# pyright: reportIncompatibleMethodOverride=false

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from nanobot.agent.subagent import SubagentControlError
from nanobot.agent.tools.base import Tool, ToolResult, tool_parameters
from nanobot.agent.tools.context import current_request_context, current_request_session_key
from nanobot.agent.tools.schema import (
    BooleanSchema,
    NumberSchema,
    StringSchema,
    tool_parameters_schema,
)
from nanobot.security.workspace_access import current_workspace_scope
from nanobot.session.manager import SessionPolicy

if TYPE_CHECKING:
    from nanobot.agent.subagent import SubagentManager
    from nanobot.agent.tools.context import ToolContext


@tool_parameters(tool_parameters_schema(
    action=StringSchema(
        "create starts a task; send queues a message; cancel requests an idempotent stop; "
        "check returns task status, receipts, and results.",
        enum=("create", "send", "cancel", "check"),
    ),
    task=StringSchema("Required for create: the task for the subagent to complete.", min_length=1),
    label=StringSchema("Optional short label for create (for display)."),
    acceptance_criteria=StringSchema(
        "Optional for create: fixed, observable acceptance criteria for an independent completion review. "
        "The reviewer checks the final response and recorded tool evidence, with at most two review attempts. "
        "Omit to run without independent verification.",
        min_length=1,
        max_length=4000,
    ),
    temperature=NumberSchema(
        description="Optional sampling temperature for create. Defaults to the parent's model runtime.",
        minimum=0.0,
        maximum=2.0,
    ),
    wait=BooleanSchema(
        description=(
            "For create: wait for the result directly when it must inform the current turn. "
            "Defaults to false for background execution with a completion notification. "
            "Ephemeral requests and hosts without a background consumer always wait."
        ),
        default=False,
    ),
    task_id=StringSchema(
        "Full task ID returned by create. Required for send/cancel; optional for check. "
        "Omit for check to list the current session's active and recently finished tasks.",
        min_length=1,
    ),
    message=StringSchema(
        "Required for send: text, at most 8192 UTF-8 bytes. Accepted means queued, not delivered. "
        "Delivery receipts mean injected into the task transcript, not that the task acted on the message.",
        max_length=8192,
    ),
    required=["action"],
))
class SubagentTool(Tool):
    """Manage the current session's private subagent tasks."""

    def __init__(self, manager: SubagentManager):
        self._manager = manager

    @classmethod
    def create(cls, ctx: ToolContext) -> Tool:
        if ctx.subagent_manager is None:
            raise RuntimeError("SubagentTool requires an initialized subagent manager")
        return cls(ctx.subagent_manager)

    @property
    def name(self) -> str:
        return "subagent"

    @property
    def description(self) -> str:
        return (
            "Create, message, cancel, or check your session's private subagent tasks. "
            "Use create for independent work; set wait=true for a blocking consultation. "
            "Use send for follow-up instructions, cancel to stop one task, and check to read "
            "progress, message receipts, and results. Check without task_id lists active and recent tasks; "
            "use a known task_id to read an older result. "
            "Background results arrive automatically; do not repeatedly poll check while waiting. "
            "A partial result or iteration limit does not mean the task completed. "
            "Set acceptance_criteria on create to require an independent completion review; "
            "a finished task without that review is not independently verified. "
            "For deliverables or existing projects, inspect the workspace first "
            "and use a dedicated subdirectory when helpful."
        )

    @property
    def concurrency_safe(self) -> bool:
        return True

    async def execute(
        self, action: str, task_id: str | None = None, message: str | None = None,
        task: str | None = None, label: str | None = None,
        temperature: float | None = None, wait: bool = False,
        acceptance_criteria: str | None = None, **kwargs: Any,
    ) -> str:
        if action == "create":
            if not task or not task.strip():
                return ToolResult.error("Error: create requires a non-empty task")
            return await self._create_task(task, label, temperature, wait, acceptance_criteria)
        if acceptance_criteria is not None:
            return ToolResult.error("Error: acceptance_criteria is only supported for create")
        owner = current_request_session_key()
        try:
            if action == "check":
                if not owner:
                    raise SubagentControlError("task unavailable")
                if task_id is not None:
                    return json.dumps(self._manager.check(task_id, owner).as_dict(), ensure_ascii=False)
                return json.dumps({
                    "tasks": [status.as_dict()
                              for status in self._manager.statuses_for_session(owner, include_history=False).values()],
                }, ensure_ascii=False)
            if action in {"send", "cancel"}:
                if not task_id:
                    return ToolResult.error(f"Error: {action} requires task_id")
                if action == "send":
                    return json.dumps(self._manager.send(task_id, owner, message))
                status = await self._manager.cancel(task_id, owner)
                return json.dumps(status.as_dict(), ensure_ascii=False)
            return ToolResult.error("Error: unknown subagent action")
        except SubagentControlError as exc:
            return ToolResult.error(f"Error: {exc}")

    async def _create_task(
        self, task: str, label: str | None, temperature: float | None, wait: bool,
        acceptance_criteria: str | None = None,
    ) -> str:
        request_ctx = current_request_context()
        if request_ctx is None or request_ctx.runtime is None:
            return ToolResult.error("Error: create requires an active model runtime")
        origin_channel = request_ctx.channel
        origin_chat_id = request_ctx.chat_id
        session_key = request_ctx.session_key or (
            f"{origin_channel}:{origin_chat_id}" if origin_channel and origin_chat_id else None
        )
        if not session_key:
            return ToolResult.error("Error: create requires an active session identity")
        inline = wait or not request_ctx.can_receive_background_results or not request_ctx.persist_session
        method = self._manager.run_inline if inline else self._manager.spawn
        return await method(
            task=task,
            acceptance_criteria=acceptance_criteria,
            runtime=request_ctx.runtime,
            label=label,
            origin_channel=origin_channel,
            origin_chat_id=origin_chat_id,
            session_key=session_key,
            origin_message_id=request_ctx.message_id,
            origin_turn_id=request_ctx.turn_id,
            temperature=temperature,
            workspace_scope=current_workspace_scope(),
            session_policy=SessionPolicy(
                persist=request_ctx.persist_session,
                log_content=request_ctx.log_content,
            ),
        )
