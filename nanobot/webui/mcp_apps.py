"""Ephemeral MCP App sessions and explicit tool approvals for the WebUI."""

from __future__ import annotations

import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, cast
from uuid import uuid4

from nanobot.agent.hook import AgentHook, AgentHookContext, AgentTurnHookContext
from nanobot.agent.tools.base import ToolResult
from nanobot.agent.tools.mcp import MCPToolWrapper
from nanobot.agent.tools.mcp_apps import MCPAppSession, MCPAppToolCall
from nanobot.agent.tools.mcp_result import snapshot_mcp_json
from nanobot.bus.outbound_events import ProgressEvent
from nanobot.providers.base import ToolCallRequest

_TTL = 900.0
_MAX_APPS = 32


@dataclass
class _App:
    session_key: str
    app: MCPAppSession
    result: dict[str, Any]
    arguments: dict[str, Any]
    expires: float
    approvals: dict[str, tuple[str, dict[str, Any]]] = field(default_factory=dict)


async def _approved(_request: MCPAppToolCall) -> bool:
    # Only the confirmation operation may call the bridge with this policy.
    return True


class WebUIMCPApps:
    """Bounded gateway-local handles; never persist HTML or approval receipts."""

    def __init__(self) -> None:
        self.enabled = False
        self._apps: OrderedDict[str, _App] = OrderedDict()

    def _expire(self) -> None:
        now = time.monotonic()
        for key, item in list(self._apps.items()):
            if item.expires < now:
                self._apps.pop(key).app.close()

    def hook(self, context: AgentTurnHookContext) -> AgentHook | None:
        if not self.enabled or context.channel != "websocket" or not context.session_key:
            return None
        owner = self
        turn_context = context

        class CaptureApp(AgentHook):
            async def after_execute_tool(
                self, context: AgentHookContext, tool_call: ToolCallRequest,
                tool: Any, params: Any, result: Any,
            ) -> None:
                if not isinstance(tool, MCPToolWrapper) or not isinstance(result, ToolResult):
                    return
                data = (result.data or {}).get("mcp")
                if not isinstance(data, dict):
                    return
                data = cast(dict[str, Any], data)
                meta: object = data.get("tool_meta")
                if not isinstance(meta, dict):
                    return
                ui: object = cast(dict[str, Any], meta).get("ui")
                if not isinstance(ui, dict) or not cast(dict[str, Any], ui).get("resourceUri"):
                    return
                owner._expire()
                while len(owner._apps) >= _MAX_APPS:
                    owner._apps.popitem(last=False)[1].app.close()
                app = tool.open_app(authorize=_approved)
                key = uuid4().hex
                owner._apps[key] = _App(
                    session_key=turn_context.session_key or "",
                    app=app,
                    result={key: value for key, value in data.items() if key in {
                        "content", "structuredContent", "_meta", "isError",
                    }},
                    arguments=snapshot_mcp_json(params, 64 * 1024),
                    expires=time.monotonic() + _TTL,
                )
                await turn_context.events.emit(ProgressEvent(tool_events=[{
                    "phase": "error" if result.is_error else "end",
                    "call_id": tool_call.id, "name": tool_call.name,
                    "arguments": params,
                    "embeds": [{"type": "mcp_app", "app_id": key,
                                "server_name": data["server_name"], "tool_name": data["tool_name"]}],
                }]))

            async def on_execute_tool_error(
                self, context: AgentHookContext, tool_call: ToolCallRequest,
                tool: Any, params: Any, error: Any,
            ) -> None:
                await self.after_execute_tool(context, tool_call, tool, params, error)

        return CaptureApp()

    async def action(self, operation: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.enabled:
            raise PermissionError("MCP Apps are disabled on this host")
        self._expire()
        app_id, session_key = payload.get("app_id"), payload.get("session_key")
        if not isinstance(app_id, str) or not isinstance(session_key, str):
            raise ValueError("An app and session are required")
        item = self._apps.get(app_id)
        if item is None or item.session_key != session_key:
            raise LookupError("This app is unavailable or expired; run the tool again")
        if operation == "open":
            resource = await item.app.read_resource()
            return {"uri": resource.uri, "html": resource.html, "meta": resource.meta,
                    "result": item.result, "arguments": item.arguments}
        if operation == "prepare":
            name, arguments = payload.get("name"), payload.get("arguments", {})
            if not isinstance(name, str) or not name or len(name) > 256 or not isinstance(arguments, dict):
                raise ValueError("Invalid app tool call")
            if len(item.approvals) >= 8:
                raise ValueError("Too many app calls are awaiting approval")
            receipt = uuid4().hex
            params = item.app.prepare_tool_call(name, cast(object, arguments)).arguments
            item.approvals[receipt] = (name, params)
            return {"approval_id": receipt, "name": name, "arguments": params}
        if operation == "confirm":
            receipt = payload.get("approval_id")
            pending = item.approvals.pop(receipt, None) if isinstance(receipt, str) else None
            if pending is None:
                raise PermissionError("The app approval is unavailable or already used")
            if payload.get("approved") is not True:
                return {"isError": True, "content": [{"type": "text", "text": "The user declined this action."}]}
            name, params = pending
            result = await item.app.call_tool(name, params)
            return result.model_dump(by_alias=True, exclude_none=True)
        raise ValueError("Unknown MCP App operation")
