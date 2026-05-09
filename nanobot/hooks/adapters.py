"""AgentHook to HookCenter compatibility adapter.

Wraps legacy AgentHook subclasses as typed-event handlers registered
onto the per-dispatch HookSession.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nanobot.agent.hook import AgentHook, AgentHookContext, CompositeHook
from nanobot.hooks.event_types import (
    AfterIteration,
    BeforeExecuteTools,
    BeforeIteration,
    FinalizeContent,
    OnStream,
    OnStreamEnd,
)
from nanobot.hooks.protocols import HookResult

if TYPE_CHECKING:
    from nanobot.hooks.center import HookCenter, HookSession


def _is_overridden(agent_hook: AgentHook, method_name: str) -> bool:
    inst_method = getattr(agent_hook, method_name, None)
    if inst_method is None:
        return False
    base_method = AgentHook.__dict__.get(method_name)
    if base_method is None:
        return False
    inst_func = getattr(inst_method, "__func__", inst_method)
    return inst_func is not base_method


def adapt_agent_hook(
    agent_hook: AgentHook,
    session: "HookSession",
    center: "HookCenter",
    *,
    reraise: bool | None = None,
) -> None:
    """Wrap a legacy AgentHook instance as typed-event handlers on *session*.

    Each non-default (overridden) method is converted to a handler
    registered via ``center.register_internal``.  The *reraise* flag
    controls error propagation: when ``None`` (the default), the
    adapter reads ``agent_hook._reraise`` and falls back to ``False``.
    """
    if reraise is None:
        reraise = getattr(agent_hook, "_reraise", False)

    ctx_cell: dict[str, AgentHookContext | None] = {"ctx": None}

    # ── before_iteration ──────────────────────────────────────────
    if _is_overridden(agent_hook, "before_iteration"):

        async def _bi_wrapper(event: BeforeIteration) -> HookResult:
            ctx = getattr(session, "context", None)
            if ctx is None:
                ctx = AgentHookContext(iteration=event.iteration, messages=event.messages)
            ctx_cell["ctx"] = ctx
            await agent_hook.before_iteration(ctx)
            return None

        center.register_internal(
            session, BeforeIteration, _bi_wrapper, reraise=reraise, mode="observe"
        )

    # ── on_stream ─────────────────────────────────────────────────
    if _is_overridden(agent_hook, "on_stream"):

        async def _os_wrapper(event: OnStream) -> HookResult:
            ctx = ctx_cell["ctx"]
            if ctx is None:
                ctx = getattr(session, "context", None)
                if ctx is None:
                    ctx = AgentHookContext(iteration=event.iteration, messages=[])
                ctx_cell["ctx"] = ctx
            await agent_hook.on_stream(ctx, event.delta)
            return None

        center.register_internal(
            session, OnStream, _os_wrapper, reraise=reraise, mode="observe", stream=False
        )

    # ── on_stream_end ─────────────────────────────────────────────
    if _is_overridden(agent_hook, "on_stream_end"):

        async def _ose_wrapper(event: OnStreamEnd) -> HookResult:
            ctx = ctx_cell["ctx"]
            if ctx is None:
                ctx = getattr(session, "context", None)
                if ctx is None:
                    ctx = AgentHookContext(iteration=event.iteration, messages=[])
                ctx_cell["ctx"] = ctx
            await agent_hook.on_stream_end(ctx, resuming=event.resuming)
            return None

        center.register_internal(
            session, OnStreamEnd, _ose_wrapper, reraise=reraise, mode="observe", stream=False
        )

    # ── before_execute_tools ──────────────────────────────────────
    if _is_overridden(agent_hook, "before_execute_tools"):

        async def _bet_wrapper(event: BeforeExecuteTools) -> HookResult:
            ctx = ctx_cell["ctx"]
            if ctx is None:
                ctx = getattr(session, "context", None)
                if ctx is None:
                    ctx = AgentHookContext(iteration=event.iteration, messages=[])
                ctx_cell["ctx"] = ctx
            ctx.tool_calls = list(event.tool_calls)
            ctx.response = event.response
            await agent_hook.before_execute_tools(ctx)
            return None

        center.register_internal(
            session, BeforeExecuteTools, _bet_wrapper, reraise=reraise, mode="observe"
        )

    # ── after_iteration ───────────────────────────────────────────
    if _is_overridden(agent_hook, "after_iteration"):

        async def _ai_wrapper(event: AfterIteration) -> HookResult:
            ctx = ctx_cell["ctx"]
            if ctx is None:
                ctx = getattr(session, "context", None)
                if ctx is None:
                    ctx = AgentHookContext(iteration=event.iteration, messages=[])
            ctx.final_content = event.final_content
            ctx.stop_reason = event.stop_reason
            ctx.usage = dict(event.usage)
            ctx.tool_calls = list(event.tool_calls)
            ctx.tool_events = list(event.tool_events)
            ctx.tool_results = list(event.tool_results)
            ctx.error = event.error
            await agent_hook.after_iteration(ctx)
            return None

        center.register_internal(
            session, AfterIteration, _ai_wrapper, reraise=reraise, mode="observe"
        )

    # ── finalize_content ──────────────────────────────────────────
    if _is_overridden(agent_hook, "finalize_content"):

        def _fc_wrapper(content: str | None) -> str | None:
            ctx = ctx_cell["ctx"]
            if ctx is None:
                ctx = getattr(session, "context", None)
                if ctx is None:
                    ctx = AgentHookContext(iteration=0, messages=[])
            return agent_hook.finalize_content(ctx, content)

        center.register_internal(
            session, FinalizeContent, _fc_wrapper, reraise=reraise, mode="transform"
        )

    # ── wants_streaming ───────────────────────────────────────────
    if agent_hook.wants_streaming():

        async def _ws_sentinel(_event: Any) -> None:
            return None

        session.wants_streaming_handlers.add(_ws_sentinel)


def adapt_agent_hook_list(
    hooks: list[AgentHook],
    session: "HookSession",
    center: "HookCenter",
) -> None:
    """Adapt a list of hooks, flattening CompositeHook instances.

    CompositeHook instances are recursively expanded into their
    ``_hooks`` children so the adapter wires each leaf directly
    rather than producing a double-layer fan-out.
    """

    def _flatten(hook_list: list[AgentHook]):
        for h in hook_list:
            if isinstance(h, CompositeHook):
                yield from _flatten(h._hooks)
            else:
                yield h

    for leaf in _flatten(hooks):
        adapt_agent_hook(leaf, session, center)
