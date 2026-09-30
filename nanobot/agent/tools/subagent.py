"""Session-owned subagent task controls."""

# pyright: reportIncompatibleMethodOverride=false

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nanobot.agent.tools.base import Tool, tool_parameters
from nanobot.agent.tools.context import current_request_session_key
from nanobot.agent.tools.schema import StringSchema, tool_parameters_schema

if TYPE_CHECKING:
    from nanobot.agent.subagent import SubagentManager
    from nanobot.agent.tools.context import ToolContext


@tool_parameters(tool_parameters_schema(
    action=StringSchema(
        "send queues a message; cancel requests an idempotent stop and returns the current state.",
        enum=("send", "cancel"),
    ),
    task_id=StringSchema("Full task ID returned by spawn, owned by the current session."),
    message=StringSchema(
        "Text for send only, at most 8192 UTF-8 bytes. Accepted means queued, not delivered. "
        "Delivery receipts mean injected into the task transcript, not that the task acted on the message.",
        max_length=8192,
    ),
    required=["action", "task_id"],
))
class SubagentTool(Tool):
    """Send messages to or cancel a session's private tasks."""

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
        return "Send a message to or cancel a private subagent task. Use my to inspect tasks and receipts."

    @property
    def concurrency_safe(self) -> bool:
        return True

    async def execute(self, action: str, task_id: str, message: str | None = None,
                      **kwargs: Any) -> str:
        return await self._manager.control(task_id, current_request_session_key(), action, message)
