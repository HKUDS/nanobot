"""Tests for AgentHook → HookCenter adapter (U4)."""

from __future__ import annotations

from typing import Any

import pytest

from nanobot.agent.hook import AgentHook, AgentHookContext, CompositeHook
from nanobot.hooks.adapters import adapt_agent_hook, adapt_agent_hook_list
from nanobot.hooks.center import HookCenter
from nanobot.hooks.event_types import (
    AfterIteration,
    BeforeExecuteTools,
    BeforeIteration,
    OnStream,
    OnStreamEnd,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _bi_ev(iteration=0, messages=None):
    if messages is None:
        messages = []
    return BeforeIteration(iteration=iteration, messages=messages)


def _os_ev(delta="x", iteration=0):
    return OnStream(delta=delta, iteration=iteration)


def _ose_ev(resuming=True, iteration=0):
    return OnStreamEnd(resuming=resuming, iteration=iteration)


def _bet_ev(iteration=0, tool_calls=None, response=None):
    if tool_calls is None:
        tool_calls = []
    return BeforeExecuteTools(iteration=iteration, tool_calls=tool_calls, response=response)


def _ai_ev(iteration=0, **kw):
    defaults: dict[str, Any] = {
        "final_content": "ok",
        "stop_reason": "completed",
        "usage": {},
        "tool_calls": [],
        "tool_events": [],
        "tool_results": [],
        "error": None,
    }
    defaults.update(kw)
    return AfterIteration(iteration=iteration, **defaults)


# ---------------------------------------------------------------------------
# Happy path: overridden methods are adapted and called
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_before_iteration_adapted_and_called():
    center = HookCenter()
    session = center.create_session()
    calls: list[int] = []

    class H(AgentHook):
        async def before_iteration(self, ctx: AgentHookContext) -> None:
            calls.append(ctx.iteration)

    hook = H()
    adapt_agent_hook(hook, session, center)

    await center.emit(_bi_ev(iteration=3), session)

    assert calls == [3]


@pytest.mark.asyncio
async def test_on_stream_adapted_and_called():
    center = HookCenter()
    session = center.create_session()
    deltas: list[str] = []

    class H(AgentHook):
        async def on_stream(self, ctx: AgentHookContext, delta: str) -> None:
            deltas.append(delta)

    hook = H()
    adapt_agent_hook(hook, session, center)

    await center.emit(_bi_ev(), session)

    await center.emit(_os_ev(delta="hello"), session)
    await center.emit(_os_ev(delta=" world"), session)

    assert deltas == ["hello", " world"]


@pytest.mark.asyncio
async def test_on_stream_end_adapted_and_called():
    center = HookCenter()
    session = center.create_session()
    recv: list[bool] = []

    class H(AgentHook):
        async def on_stream_end(self, ctx: AgentHookContext, *, resuming: bool) -> None:
            recv.append(resuming)

    hook = H()
    adapt_agent_hook(hook, session, center)

    await center.emit(_bi_ev(), session)  # seed context
    await center.emit(_ose_ev(resuming=True), session)
    await center.emit(_ose_ev(resuming=False), session)

    assert recv == [True, False]


@pytest.mark.asyncio
async def test_before_execute_tools_adapted_and_called():
    center = HookCenter()
    session = center.create_session()
    saw_tool_calls: list[list[Any]] = []

    class H(AgentHook):
        async def before_execute_tools(self, ctx: AgentHookContext) -> None:
            saw_tool_calls.append(list(ctx.tool_calls))

    hook = H()
    adapt_agent_hook(hook, session, center)

    await center.emit(_bi_ev(), session)  # seed context
    fake_tc = [object()]
    await center.emit(_bet_ev(tool_calls=fake_tc), session)

    assert len(saw_tool_calls) == 1
    assert saw_tool_calls[0] == fake_tc


@pytest.mark.asyncio
async def test_after_iteration_adapted_and_called():
    center = HookCenter()
    session = center.create_session()
    seen: list[AgentHookContext] = []

    class H(AgentHook):
        async def after_iteration(self, ctx: AgentHookContext) -> None:
            seen.append(ctx)

    hook = H()
    adapt_agent_hook(hook, session, center)

    await center.emit(_bi_ev(), session)  # seed
    await center.emit(
        _ai_ev(
            iteration=5,
            final_content="done",
            stop_reason="completed",
            error=None,
        ),
        session,
    )

    assert len(seen) == 1
    assert seen[0].iteration == 5
    assert seen[0].final_content == "done"
    assert seen[0].stop_reason == "completed"


def test_finalize_content_adapted_and_called():
    center = HookCenter()
    session = center.create_session()

    class H(AgentHook):
        def finalize_content(self, ctx: AgentHookContext, content: str | None) -> str | None:
            return (content or "") + "_adapted"

    hook = H()
    adapt_agent_hook(hook, session, center)

    result = center.finalize_content("hello", session)

    assert result == "hello_adapted"


def test_finalize_content_pipeline_ordering():
    center = HookCenter()
    session = center.create_session()

    class Upper(AgentHook):
        def finalize_content(self, ctx, content):
            return content.upper() if content else content

    class Suffix(AgentHook):
        def finalize_content(self, ctx, content):
            return (content + "!") if content else content

    adapt_agent_hook(Upper(), session, center)
    adapt_agent_hook(Suffix(), session, center)

    result = center.finalize_content("hello", session)
    assert result == "HELLO!"


def test_wants_streaming_true_adapted():
    center = HookCenter()
    session = center.create_session()

    class H(AgentHook):
        def wants_streaming(self) -> bool:
            return True

    adapt_agent_hook(H(), session, center)

    assert center.wants_streaming(session) is True


def test_wants_streaming_false_not_set():
    center = HookCenter()
    session = center.create_session()

    adapt_agent_hook(AgentHook(), session, center)

    assert center.wants_streaming(session) is False


# ---------------------------------------------------------------------------
# Edge: only overridden methods are registered
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_only_overridden_methods_are_registered():
    center = HookCenter()
    session = center.create_session()
    calls: list[str] = []

    class PartialHook(AgentHook):
        async def before_iteration(self, ctx):
            calls.append("bi")

        # on_stream, on_stream_end, before_execute_tools NOT overridden
        # after_iteration NOT overridden

    hook = PartialHook()
    adapt_agent_hook(hook, session, center)

    await center.emit(_bi_ev(), session)
    # These events have no registered handlers (just the base no-op)
    await center.emit(_os_ev(), session)
    await center.emit(_ose_ev(), session)

    assert calls == ["bi"]


# ---------------------------------------------------------------------------
# Edge: _reraise propagation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reraise_true_from_hook_attribute():
    center = HookCenter()
    session = center.create_session()

    class H(AgentHook):
        def __init__(self):
            self._reraise = True

        async def before_iteration(self, ctx):
            raise RuntimeError("reraise-me")

    hook = H()
    adapt_agent_hook(hook, session, center)

    with pytest.raises(RuntimeError, match="reraise-me"):
        await center.emit(_bi_ev(), session)


@pytest.mark.asyncio
async def test_reraise_explicit_overrides():
    center = HookCenter()
    session = center.create_session()

    class H(AgentHook):
        def __init__(self):
            self._reraise = True

        async def before_iteration(self, ctx):
            raise RuntimeError("bad")

    hook = H()
    adapt_agent_hook(hook, session, center, reraise=False)

    await center.emit(_bi_ev(), session)  # should not raise


@pytest.mark.asyncio
async def test_reraise_false_catches():
    center = HookCenter()
    session = center.create_session()

    class H(AgentHook):
        async def before_iteration(self, ctx):
            raise RuntimeError("caught")

    adapt_agent_hook(H(), session, center)

    await center.emit(_bi_ev(), session)  # no exception


# ---------------------------------------------------------------------------
# Edge: context without prior before_iteration (lazy init)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_on_stream_works_without_prior_context():
    center = HookCenter()
    session = center.create_session()
    deltas: list[str] = []

    class H(AgentHook):
        async def on_stream(self, ctx, delta):
            deltas.append(delta)

    adapt_agent_hook(H(), session, center)

    await center.emit(_os_ev(delta="direct"), session)

    assert deltas == ["direct"]


# ---------------------------------------------------------------------------
# Integration: adapt_agent_hook_list
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_adapt_agent_hook_list_fan_out():
    center = HookCenter()
    session = center.create_session()
    calls: list[str] = []

    class H1(AgentHook):
        async def before_iteration(self, ctx):
            calls.append("h1")

    class H2(AgentHook):
        async def before_iteration(self, ctx):
            calls.append("h2")

    adapt_agent_hook_list([H1(), H2()], session, center)

    await center.emit(_bi_ev(), session)

    assert calls == ["h1", "h2"]


@pytest.mark.asyncio
async def test_adapt_agent_hook_list_flattens_composite():
    center = HookCenter()
    session = center.create_session()
    calls: list[str] = []

    class Inner1(AgentHook):
        async def before_iteration(self, ctx):
            calls.append("inner1")

    class Inner2(AgentHook):
        async def before_iteration(self, ctx):
            calls.append("inner2")

    composite = CompositeHook([Inner1(), CompositeHook([Inner2()])])

    adapt_agent_hook_list([composite], session, center)

    await center.emit(_bi_ev(), session)

    assert calls == ["inner1", "inner2"]


@pytest.mark.asyncio
async def test_adapt_agent_hook_list_no_double_adapt():
    """CompositeHook itself is NOT adapted — only its leaves."""
    center = HookCenter()
    session = center.create_session()
    calls: list[str] = []

    class Leaf(AgentHook):
        async def before_iteration(self, ctx):
            calls.append("leaf")

    composite = CompositeHook([Leaf()])
    adapt_agent_hook_list([composite], session, center)

    await center.emit(_bi_ev(), session)

    # If CompositeHook were adapted directly AND its leaves,
    # we'd get duplicate calls. We expect exactly one.
    assert calls == ["leaf"]


# ---------------------------------------------------------------------------
# Integration: RecordingHook pattern from test_hook_composite.py
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recording_hook_through_adapter():
    """RecordingHook (same pattern as test_hook_composite.py) works through adapter."""
    center = HookCenter()
    session = center.create_session()
    events: list[str] = []

    class RecordingHook(AgentHook):
        async def before_iteration(self, ctx):
            events.append("before_iteration")

        async def on_stream(self, ctx, delta):
            events.append(f"on_stream:{delta}")

        async def on_stream_end(self, ctx, *, resuming):
            events.append(f"on_stream_end:{resuming}")

        async def before_execute_tools(self, ctx):
            events.append("before_execute_tools")

        async def after_iteration(self, ctx):
            events.append("after_iteration")

    hook = RecordingHook()
    adapt_agent_hook(hook, session, center)

    await center.emit(_bi_ev(), session)
    await center.emit(_os_ev(delta="hi"), session)
    await center.emit(_ose_ev(resuming=True), session)
    await center.emit(_bet_ev(), session)
    await center.emit(_ai_ev(), session)

    assert events == [
        "before_iteration",
        "on_stream:hi",
        "on_stream_end:True",
        "before_execute_tools",
        "after_iteration",
    ]


# ---------------------------------------------------------------------------
# Context accumulation across iteration lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_context_accumulates_across_events():
    """Context built in BeforeIteration is visible to subsequent events."""
    center = HookCenter()
    session = center.create_session()
    seen_messages: list[list[dict]] = []

    class H(AgentHook):
        async def before_iteration(self, ctx):
            pass  # just creates context

        async def on_stream(self, ctx, delta):
            seen_messages.append(list(ctx.messages))

    adapt_agent_hook(H(), session, center)

    test_msgs = [{"role": "user", "content": "hello"}]
    await center.emit(_bi_ev(messages=test_msgs), session)
    await center.emit(_os_ev(delta="a"), session)

    assert seen_messages == [test_msgs]


@pytest.mark.asyncio
async def test_before_execute_tools_receives_accumulated_context():
    """before_execute_tools sees the context built from before_iteration + streaming."""
    center = HookCenter()
    session = center.create_session()
    captured_iter: list[int] = []
    captured_messages: list[list[dict]] = []

    class H(AgentHook):
        async def before_iteration(self, ctx):
            pass  # seeds the context cell

        async def before_execute_tools(self, ctx):
            captured_iter.append(ctx.iteration)
            captured_messages.append(list(ctx.messages))

    adapt_agent_hook(H(), session, center)

    test_msgs = [{"role": "user", "content": "test"}]
    await center.emit(_bi_ev(iteration=7, messages=test_msgs), session)
    await center.emit(_bet_ev(iteration=7), session)

    assert captured_iter == [7]
    assert captured_messages == [test_msgs]


# ---------------------------------------------------------------------------
# finalize_content with None content
# ---------------------------------------------------------------------------


def test_finalize_content_none_passthrough():
    center = HookCenter()
    session = center.create_session()

    class H(AgentHook):
        def finalize_content(self, ctx, content):
            return content

    adapt_agent_hook(H(), session, center)

    result = center.finalize_content(None, session)
    assert result is None


def test_finalize_content_error_caught_by_center():
    center = HookCenter()
    session = center.create_session()

    class Bad(AgentHook):
        def finalize_content(self, ctx, content):
            raise RuntimeError("bad finalize")

    class Good(AgentHook):
        def finalize_content(self, ctx, content):
            return (content or "") + "_good"

    adapt_agent_hook(Bad(), session, center)
    adapt_agent_hook(Good(), session, center)

    result = center.finalize_content("test", session)
    assert result == "test_good"


# ---------------------------------------------------------------------------
# adapt_agent_hook_list mixed: some with overridden, some without
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_adapt_list_mixed_overrides():
    center = HookCenter()
    session = center.create_session()
    calls: list[str] = []

    class Overriding(AgentHook):
        async def before_iteration(self, ctx):
            calls.append("overridden")

    adapt_agent_hook_list([Overriding(), AgentHook()], session, center)

    await center.emit(_bi_ev(), session)

    # Only the overriding hook should trigger
    assert calls == ["overridden"]


# ---------------------------------------------------------------------------
# on_stream_end: resuming keyword is passed correctly
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_on_stream_end_resuming_keyword():
    center = HookCenter()
    session = center.create_session()
    resuming_values: list[bool] = []

    class H(AgentHook):
        async def on_stream_end(self, ctx, *, resuming):
            resuming_values.append(resuming)

    adapt_agent_hook(H(), session, center)

    await center.emit(_bi_ev(), session)
    await center.emit(_ose_ev(resuming=True), session)
    await center.emit(_ose_ev(resuming=False), session)
    await center.emit(_ose_ev(resuming=False), session)

    assert resuming_values == [True, False, False]
