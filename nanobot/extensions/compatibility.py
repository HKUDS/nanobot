"""Adapters that project Pi/OpenClaw registrations into native nanobot APIs."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any
from uuid import uuid4

from nanobot.agent.hook import (
    AgentHook,
    AgentHookContext,
    AgentRunHookContext,
)
from nanobot.agent.tools.base import Tool
from nanobot.bus.events import OutboundMessage
from nanobot.command.router import CommandContext, CommandRouter
from nanobot.extensions.node_host import NodeSidecar
from nanobot.extensions.protocol import NodeLoadResult, NodeRegistration

_EVENT_MAP = {
    "pi": {
        "before_run": "agent_start",
        "after_run": "agent_end",
        "before_execute_tool": "tool_call",
        "after_execute_tool": "tool_result",
    },
    "openclaw": {
        "before_run": "before_agent_run",
        "after_run": "agent_end",
        "before_execute_tool": "before_tool_call",
        "after_execute_tool": "after_tool_call",
    },
}


class RemoteTool(Tool):
    """Native Tool facade whose implementation remains inside a sidecar."""

    def __init__(self, host: NodeSidecar, registration: NodeRegistration) -> None:
        self._host = host
        self._registration = registration

    @property
    def name(self) -> str:
        return self._registration.name

    @property
    def description(self) -> str:
        return self._registration.description

    @property
    def parameters(self) -> dict[str, Any]:
        return self._registration.schema or {"type": "object", "properties": {}}

    @property
    def read_only(self) -> bool:
        return bool((self._registration.metadata or {}).get("readOnly"))

    async def execute(self, **kwargs: Any) -> Any:
        result = await self._host.request(
            "extension.call",
            {
                "kind": "tool",
                "name": self.name,
                "callId": uuid4().hex,
                "input": kwargs,
            },
        )
        return result.get("text", "")


class RemoteHook(AgentHook):
    """Observation-only lifecycle bridge for compatible extension events."""

    def __init__(self, host: NodeSidecar, runtime: str, events: set[str]) -> None:
        super().__init__()
        self._host = host
        self._events = events
        self._mapping = _EVENT_MAP[runtime]

    async def _emit(self, lifecycle: str, context: object, **extra: Any) -> None:
        event = self._mapping[lifecycle]
        if event not in self._events:
            return
        payload = _jsonable(context)
        if isinstance(payload, dict):
            payload.update(extra)
        await self._host.request(
            "extension.event",
            {"name": event, "event": payload},
        )

    async def before_run(self, context: AgentRunHookContext) -> None:
        await self._emit("before_run", context)

    async def after_run(self, context: AgentRunHookContext) -> None:
        await self._emit("after_run", context)

    async def before_execute_tool(
        self,
        context: AgentHookContext,
        tool_call: Any,
        tool: Any,
        params: Any,
    ) -> None:
        await self._emit(
            "before_execute_tool",
            context,
            toolCall=_jsonable(tool_call),
            tool=getattr(tool, "name", ""),
            input=_jsonable(params),
        )

    async def after_execute_tool(
        self,
        context: AgentHookContext,
        tool_call: Any,
        tool: Any,
        params: Any,
        result: Any,
    ) -> None:
        await self._emit(
            "after_execute_tool",
            context,
            toolCall=_jsonable(tool_call),
            tool=getattr(tool, "name", ""),
            input=_jsonable(params),
            result=_jsonable(result),
        )


class CompatibleExtension:
    """Loaded Pi/OpenClaw extension and its native projections."""

    def __init__(
        self,
        *,
        host: NodeSidecar,
        runtime: str,
        owner: str,
        result: NodeLoadResult,
    ) -> None:
        self.host = host
        self.runtime = runtime
        self.owner = owner
        self.result = result

    @property
    def tools(self) -> tuple[RemoteTool, ...]:
        return tuple(
            RemoteTool(self.host, item)
            for item in self.result.registrations
            if item.kind == "tool"
        )

    @property
    def hook(self) -> RemoteHook | None:
        events = {
            item.name
            for item in self.result.registrations
            if item.kind == "hook"
        }
        return RemoteHook(self.host, self.runtime, events) if events else None

    def register_commands(self, router: CommandRouter) -> None:
        for item in self.result.registrations:
            if item.kind != "command":
                continue

            async def handler(ctx: CommandContext, name: str = item.name) -> OutboundMessage | None:
                result = await self.host.request(
                    "extension.call",
                    {
                        "kind": "command",
                        "name": name,
                        "input": {
                            "args": ctx.args,
                            "raw": ctx.raw,
                            "channel": ctx.msg.channel,
                            "chatId": ctx.msg.chat_id,
                            "senderId": ctx.msg.sender_id,
                            "sessionKey": ctx.key,
                        },
                    },
                )
                text = str(result.get("text") or "")
                if not text:
                    return None
                return OutboundMessage(
                    channel=ctx.msg.channel,
                    chat_id=ctx.msg.chat_id,
                    content=text,
                )

            command = f"/{item.name}"
            router.exact(command, handler, owner=self.owner)
            router.prefix(f"{command} ", handler, owner=self.owner)

    async def close(self) -> None:
        await self.host.close()


def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, BaseException):
        return {"type": type(value).__name__, "message": str(value)}
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)
