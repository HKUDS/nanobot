"""Shared lifecycle hook primitives for agent runs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from loguru import logger

from nanobot.providers.base import LLMResponse, ToolCallRequest


@dataclass(slots=True)
class AgentHookContext:
    """Mutable per-iteration state exposed to runner hooks."""

    iteration: int
    messages: list[dict[str, Any]]
    response: LLMResponse | None = None
    usage: dict[str, int] = field(default_factory=dict)
    tool_calls: list[ToolCallRequest] = field(default_factory=list)
    tool_results: list[Any] = field(default_factory=list)
    tool_events: list[dict[str, str]] = field(default_factory=list)
    streamed_content: bool = False
    final_content: str | None = None
    stop_reason: str | None = None
    error: str | None = None


class AgentHook:
    """Minimal lifecycle surface for shared runner customization."""

    def __init__(self, reraise: bool = False) -> None:
        self._reraise = reraise

    def wants_streaming(self) -> bool:
        return False

    async def before_iteration(self, context: AgentHookContext) -> None:
        pass

    async def on_stream(self, context: AgentHookContext, delta: str) -> None:
        pass

    async def on_stream_end(self, context: AgentHookContext, *, resuming: bool) -> None:
        pass

    async def before_execute_tools(self, context: AgentHookContext) -> None:
        pass

    async def after_iteration(self, context: AgentHookContext) -> None:
        pass

    def finalize_content(self, context: AgentHookContext, content: str | None) -> str | None:
        return content


class CompositeHook(AgentHook):
    """Fan-out hook that delegates to an ordered list of hooks.

    Error isolation: async methods catch and log per-hook exceptions
    so a faulty custom hook cannot crash the agent loop.
    ``finalize_content`` is a pipeline (no isolation — bugs should surface).
    """

    __slots__ = ("_hooks",)

    def __init__(self, hooks: list[AgentHook]) -> None:
        super().__init__()
        self._hooks = list(hooks)

    def wants_streaming(self) -> bool:
        return any(h.wants_streaming() for h in self._hooks)

    async def _for_each_hook_safe(self, method_name: str, *args: Any, **kwargs: Any) -> None:
        for h in self._hooks:
            if getattr(h, "_reraise", False):
                await getattr(h, method_name)(*args, **kwargs)
                continue

            try:
                await getattr(h, method_name)(*args, **kwargs)
            except Exception:
                logger.exception("AgentHook.{} error in {}", method_name, type(h).__name__)

    async def before_iteration(self, context: AgentHookContext) -> None:
        await self._for_each_hook_safe("before_iteration", context)

    async def on_stream(self, context: AgentHookContext, delta: str) -> None:
        await self._for_each_hook_safe("on_stream", context, delta)

    async def on_stream_end(self, context: AgentHookContext, *, resuming: bool) -> None:
        await self._for_each_hook_safe("on_stream_end", context, resuming=resuming)

    async def before_execute_tools(self, context: AgentHookContext) -> None:
        await self._for_each_hook_safe("before_execute_tools", context)

    async def after_iteration(self, context: AgentHookContext) -> None:
        await self._for_each_hook_safe("after_iteration", context)

    def finalize_content(self, context: AgentHookContext, content: str | None) -> str | None:
        for h in self._hooks:
            content = h.finalize_content(context, content)
        return content


class SDKCaptureHook(AgentHook):
    """Record tool names and the final message list for ``RunResult``.

    The runner mutates ``context.messages`` in place across iterations, so the
    snapshot is refreshed on every ``after_iteration`` call; the last call
    reflects the end-of-turn state the SDK caller cares about.
    """

    def __init__(self) -> None:
        super().__init__()
        self.tools_used: list[str] = []
        self.messages: list[dict[str, Any]] = []

    async def after_iteration(self, context: AgentHookContext) -> None:
        for call in context.tool_calls:
            self.tools_used.append(call.name)
        self.messages = list(context.messages)
