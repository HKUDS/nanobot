"""Current-session local trigger management for event-driven agent turns."""

from __future__ import annotations

from typing import Any

from nanobot.agent.tools.base import Tool, ToolResult, tool_parameters
from nanobot.agent.tools.context import current_request_context
from nanobot.agent.tools.schema import StringSchema, tool_parameters_schema
from nanobot.session.keys import UNIFIED_SESSION_KEY
from nanobot.triggers.local_store import LocalTriggerStore
from nanobot.triggers.local_types import LocalTrigger

_LOCAL_TRIGGER_PARAMETERS = tool_parameters_schema(
    action=StringSchema(
        "Action to perform",
        enum=["create", "list", "enable", "disable", "remove"],
    ),
    name=StringSchema(
        "REQUIRED when action='create'. Short human-readable trigger name."
    ),
    trigger_id=StringSchema(
        "REQUIRED for enable, disable, or remove. Obtain it from create or list."
    ),
    required=["action"],
    description=(
        "Create and manage external-event entry points bound to the current chat session. "
        "create requires name; enable, disable, and remove require trigger_id."
    ),
)


@tool_parameters(_LOCAL_TRIGGER_PARAMETERS)
class LocalTriggerTool(Tool):
    """Manage local triggers without making the user run a chat command first."""

    def __init__(self, store: LocalTriggerStore):
        self._store = store

    @classmethod
    def enabled(cls, ctx: Any) -> bool:
        return ctx.local_trigger_store is not None

    @classmethod
    def create(cls, ctx: Any) -> Tool:
        return cls(store=ctx.local_trigger_store)

    @property
    def name(self) -> str:
        return "local_trigger"

    @property
    def description(self) -> str:
        return (
            "Create, list, enable, disable, or remove local triggers bound to the current "
            "conversation. A local trigger gives an external script or service a `nanobot "
            "trigger ...` command that queues an agent turn here. It does not poll, schedule, "
            "or expose a public webhook; combine it with an external event source or lightweight "
            "watcher. Operations are limited to the current conversation."
        )

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        errors = super().validate_params(params)
        action = params.get("action")
        if action == "create" and not str(params.get("name") or "").strip():
            errors.append("name is required when action='create'")
        if action in {"enable", "disable", "remove"} and not str(
            params.get("trigger_id") or ""
        ).strip():
            errors.append(f"trigger_id is required when action='{action}'")
        return errors

    @staticmethod
    def _request_route() -> tuple[str, str, str, dict[str, Any]]:
        ctx = current_request_context()
        if ctx is None:
            return "", "", "", {}
        raw_key = f"{ctx.channel}:{ctx.chat_id}" if ctx.channel and ctx.chat_id else ""
        session_key = raw_key if ctx.session_key == UNIFIED_SESSION_KEY else (ctx.session_key or "")
        return session_key, ctx.channel or "", ctx.chat_id or "", dict(ctx.metadata or {})

    @staticmethod
    def _command(trigger_id: str) -> str:
        return f'nanobot trigger {trigger_id} "message"'

    def _for_current_session(self, trigger_id: str, session_key: str) -> LocalTrigger | None:
        trigger = self._store.get(trigger_id.strip())
        if trigger is None or trigger.session_key != session_key:
            return None
        return trigger

    def _create(
        self,
        name: str,
        session_key: str,
        channel: str,
        chat_id: str,
        metadata: dict[str, Any],
    ) -> str:
        trigger = self._store.create(
            name=name,
            channel=channel,
            chat_id=chat_id,
            session_key=session_key,
            sender_id="trigger",
            origin_metadata=metadata,
        )
        return (
            f"Created local trigger '{trigger.name}' (id: {trigger.id}).\n"
            "External delivery command:\n"
            f"{self._command(trigger.id)}\n"
            "Run it with the same nanobot workspace/config as the gateway. The command queues "
            "an agent turn in this conversation; it does not poll or schedule the event source."
        )

    def _list(self, session_key: str) -> str:
        triggers = self._store.list_for_session(session_key, include_disabled=True)
        if not triggers:
            return "No local triggers are bound to this conversation."
        lines = ["Local triggers for this conversation:"]
        for trigger in triggers:
            state = "enabled" if trigger.enabled else "disabled"
            lines.extend(
                [
                    f"- {trigger.name} (id: {trigger.id}, {state})",
                    f"  Command: {self._command(trigger.id)}",
                ]
            )
        return "\n".join(lines)

    async def execute(
        self,
        action: str,
        name: str | None = None,
        trigger_id: str | None = None,
        **kwargs: Any,
    ) -> str:
        session_key, channel, chat_id, metadata = self._request_route()
        if not session_key or not channel or not chat_id:
            return ToolResult.error(
                "Error: local triggers must be managed from an active chat session"
            )

        if action == "create":
            return self._create(name or "", session_key, channel, chat_id, metadata)
        if action == "list":
            return self._list(session_key)

        trigger = self._for_current_session(trigger_id or "", session_key)
        if trigger is None:
            return ToolResult.error(
                f"Error: local trigger not found in this conversation: {trigger_id or ''}"
            )
        if action == "enable":
            self._store.enable(trigger.id, enabled=True)
            return f"Enabled local trigger '{trigger.name}' (id: {trigger.id})."
        if action == "disable":
            self._store.enable(trigger.id, enabled=False)
            return f"Disabled local trigger '{trigger.name}' (id: {trigger.id})."
        if action == "remove":
            self._store.delete(trigger.id)
            return f"Removed local trigger '{trigger.name}' (id: {trigger.id})."
        return ToolResult.error(f"Error: unknown action: {action}")
