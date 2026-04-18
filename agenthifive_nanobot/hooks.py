"""AgentHook that auto-tracks approval-required MCP responses.

When mcp_agenthifive_execute or mcp_agenthifive_download returns approvalRequired=true, this hook
captures the original tool call arguments and registers the pending
approval with the adapter's poller for automatic replay.

Session routing context (channel, chat_id, sender_id) is set by the
adapter before each message is processed and read by this hook.
"""

from __future__ import annotations

import contextvars
import json
import logging
from typing import TYPE_CHECKING, Any

from nanobot.agent.hook import AgentHook, AgentHookContext

if TYPE_CHECKING:
    from .adapter import AgentHiFiveAdapter

logger = logging.getLogger(__name__)
_pending_execute_args_var: contextvars.ContextVar[dict[str, dict[str, Any]] | None] = (
    contextvars.ContextVar(
        "agenthifive_pending_execute_args",
        default=None,
    )
)

# Tool names for AgentHiFive MCP tools
AH5_EXECUTE_TOOL = "mcp_agenthifive_execute"
AH5_DOWNLOAD_TOOL = "mcp_agenthifive_download"


class AgentHiFiveHook(AgentHook):
    """Intercepts AgentHiFive MCP results to auto-track approvals."""

    def __init__(self, adapter: AgentHiFiveAdapter):
        self._adapter = adapter

    async def before_execute_tools(self, context: AgentHookContext) -> None:
        """Capture AgentHiFive MCP call arguments before execution."""
        pending_execute_args: dict[str, dict[str, Any]] = {}
        for tc in context.tool_calls:
            if tc.name in {AH5_EXECUTE_TOOL, AH5_DOWNLOAD_TOOL}:
                pending_execute_args[tc.id] = dict(tc.arguments)
                pending_execute_args[tc.id]["_tool_name"] = tc.name
                logger.debug("Captured AH5 %s args for tool_call %s", tc.name, tc.id)
        _pending_execute_args_var.set(pending_execute_args or None)

    async def after_iteration(self, context: AgentHookContext) -> None:
        """Check tool results for approval-required responses and auto-track them."""
        pending_execute_args = _pending_execute_args_var.get()
        if not pending_execute_args:
            return

        try:
            # Match tool calls to results (parallel lists)
            for tc, result in zip(context.tool_calls, context.tool_results):
                if tc.id not in pending_execute_args:
                    continue

                # Parse the result to check for approvalRequired
                approval_data = _parse_approval_response(result)
                if not approval_data:
                    continue

                approval_id = approval_data.get("approvalRequestId")
                if not approval_id:
                    continue

                args = pending_execute_args[tc.id]
                original_payload = {"model": "B"}
                download_filename = None
                if args.get("_tool_name") == AH5_DOWNLOAD_TOOL:
                    original_payload["method"] = "GET"
                    original_payload["download"] = True
                    download_filename = args.get("filename")
                    for key in ("connectionId", "service", "url", "headers"):
                        if key in args:
                            original_payload[key] = args[key]
                else:
                    for key in (
                        "connectionId",
                        "service",
                        "method",
                        "url",
                        "body",
                        "query",
                        "headers",
                    ):
                        if key in args:
                            original_payload[key] = args[key]

                # Read task-local routing metadata captured for this session.
                session_ctx = self._adapter.get_session_context()

                logger.info(
                    "Auto-tracking approval %s for %s %s (channel=%s, chat=%s)",
                    approval_id,
                    args.get("method", "?"),
                    args.get("url", "?"),
                    session_ctx.get("channel"),
                    session_ctx.get("chat_id"),
                )

                self._adapter.track_approval(
                    approval_request_id=approval_id,
                    original_payload=original_payload,
                    download_filename=download_filename if isinstance(download_filename, str) else None,
                    session_key=session_ctx.get("session_key"),
                    channel=session_ctx.get("channel"),
                    chat_id=session_ctx.get("chat_id"),
                    sender_id=session_ctx.get("sender_id"),
                )
        finally:
            _pending_execute_args_var.set(None)


def _parse_approval_response(result: Any) -> dict[str, Any] | None:
    """Try to extract an approval-required response from a tool result.

    Tool results can be strings (JSON-encoded) or dicts depending on
    the MCP wrapper and nanobot's normalization.
    """
    if isinstance(result, dict):
        if result.get("approvalRequired"):
            return result
        return None

    if isinstance(result, str):
        # MCP tool results come as JSON strings via the MCP protocol
        try:
            data = json.loads(result)
        except (json.JSONDecodeError, TypeError):
            return None

        if isinstance(data, dict) and data.get("approvalRequired"):
            return data

        # Sometimes nested as a list of content blocks from MCP
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and item.get("type") == "text":
                    try:
                        inner = json.loads(item.get("text", ""))
                        if isinstance(inner, dict) and inner.get("approvalRequired"):
                            return inner
                    except (json.JSONDecodeError, TypeError):
                        continue

    return None
