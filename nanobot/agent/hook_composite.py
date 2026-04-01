"""Composite hook that delegates to multiple AgentHook instances."""

from __future__ import annotations

from nanobot.agent.hook import AgentHook, AgentHookContext


class CompositeHook(AgentHook):
    """Delegates all hook callbacks to an ordered list of child hooks.

    - ``wants_streaming`` returns True if ANY child returns True.
    - ``finalize_content`` chains: each child receives the output of the previous.
    - All other callbacks are fire-and-forget to all children.
    """

    def __init__(self, hooks: list[AgentHook]) -> None:
        self._hooks = hooks

    def wants_streaming(self) -> bool:
        return any(h.wants_streaming() for h in self._hooks)

    async def before_iteration(self, context: AgentHookContext) -> None:
        for h in self._hooks:
            await h.before_iteration(context)

    async def on_stream(self, context: AgentHookContext, delta: str) -> None:
        for h in self._hooks:
            await h.on_stream(context, delta)

    async def on_stream_end(self, context: AgentHookContext, *, resuming: bool) -> None:
        for h in self._hooks:
            await h.on_stream_end(context, resuming=resuming)

    async def before_execute_tools(self, context: AgentHookContext) -> None:
        for h in self._hooks:
            await h.before_execute_tools(context)

    async def after_iteration(self, context: AgentHookContext) -> None:
        for h in self._hooks:
            await h.after_iteration(context)

    def finalize_content(self, context: AgentHookContext, content: str | None) -> str | None:
        for h in self._hooks:
            content = h.finalize_content(context, content)
        return content
