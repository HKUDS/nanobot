"""Tests for CompositeHook fan-out, error isolation, and integration."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from janniebot.agent.hook import AgentHook, AgentHookContext, CompositeHook


def _ctx() -> AgentHookContext:
    return AgentHookContext(iteration=0, messages=[])


# ---------------------------------------------------------------------------
# Fan-out: every hook is called in order
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_composite_fans_out_before_iteration():
    calls: list[str] = []

    class H(AgentHook):
        async def before_iteration(self, context: AgentHookContext) -> None:
            calls.append(f"A:{context.iteration}")

    class H2(AgentHook):
        async def before_iteration(self, context: AgentHookContext) -> None:
            calls.append(f"B:{context.iteration}")

    hook = CompositeHook([H(), H2()])
    ctx = _ctx()
    await hook.before_iteration(ctx)
    assert calls == ["A:0", "B:0"]


@pytest.mark.asyncio
async def test_composite_fans_out_all_async_methods():
    """Verify all async methods fan out to every hook."""
    events: list[str] = []

    class RecordingHook(AgentHook):
        async def before_iteration(self, context: AgentHookContext) -> None:
            events.append("before_iteration")

        async def on_stream(self, context: AgentHookContext, delta: str) -> None:
            events.append(f"on_stream:{delta}")

        async def on_stream_end(self, context: AgentHookContext, *, resuming: bool) -> None:
            events.append(f"on_stream_end:{resuming}")

        async def before_execute_tools(self, context: AgentHookContext) -> None:
            events.append("before_execute_tools")

        async def after_iteration(self, context: AgentHookContext) -> None:
            events.append("after_iteration")

    hook = CompositeHook([RecordingHook(), RecordingHook()])
    ctx = _ctx()

    await hook.before_iteration(ctx)
    await hook.on_stream(ctx, "hi")
    await hook.on_stream_end(ctx, resuming=True)
    await hook.before_execute_tools(ctx)
    await hook.after_iteration(ctx)

    assert events == [
        "before_iteration", "before_iteration",
        "on_stream:hi", "on_stream:hi",
        "on_stream_end:True", "on_stream_end:True",
        "before_execute_tools", "before_execute_tools",
        "after_iteration", "after_iteration",
    ]


# ---------------------------------------------------------------------------
# Error isolation: one hook raises, others still run
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_composite_error_isolation_before_iteration():
    calls: list[str] = []

    class Bad(AgentHook):
        async def before_iteration(self, context: AgentHookContext) -> None:
            raise RuntimeError("boom")

    class Good(AgentHook):
        async def before_iteration(self, context: AgentHookContext) -> None:
            calls.append("good")

    hook = CompositeHook([Bad(), Good()])
    await hook.before_iteration(_ctx())
    assert calls == ["good"]


@pytest.mark.asyncio
async def test_composite_error_isolation_on_stream():
    calls: list[str] = []

    class Bad(AgentHook):
        async def on_stream(self, context: AgentHookContext, delta: str) -> None:
            raise RuntimeError("stream-boom")

    class Good(AgentHook):
        async def on_stream(self, context: AgentHookContext, delta: str) -> None:
            calls.append(delta)

    hook = CompositeHook([Bad(), Good()])
    await hook.on_stream(_ctx(), "delta")
    assert calls == ["delta"]


@pytest.mark.asyncio
async def test_composite_error_isolation_all_async():
    """Error isolation for on_stream_end, before_execute_tools, after_iteration."""
    calls: list[str] = []

    class Bad(AgentHook):
        async def on_stream_end(self, context, *, resuming):
            raise RuntimeError("err")
        async def before_execute_tools(self, context):
            raise RuntimeError("err")
        async def after_iteration(self, context):
            raise RuntimeError("err")

    class Good(AgentHook):
        async def on_stream_end(self, context, *, resuming):
            calls.append("on_stream_end")
        async def before_execute_tools(self, context):
            calls.append("before_execute_tools")
        async def after_iteration(self, context):
            calls.append("after_iteration")

    hook = CompositeHook([Bad(), Good()])
    ctx = _ctx()
    await hook.on_stream_end(ctx, resuming=False)
    await hook.before_execute_tools(ctx)
    await hook.after_iteration(ctx)
    assert calls == ["on_stream_end", "before_execute_tools", "after_iteration"]


# ---------------------------------------------------------------------------
# finalize_content: pipeline semantics (no error isolation)
# ---------------------------------------------------------------------------


def test_composite_finalize_content_pipeline():
    class Upper(AgentHook):
        def finalize_content(self, context, content):
            return content.upper() if content else content

    class Suffix(AgentHook):
        def finalize_content(self, context, content):
            return (content + "!") if content else content

    hook = CompositeHook([Upper(), Suffix()])
    result = hook.finalize_content(_ctx(), "hello")
    assert result == "HELLO!"


def test_composite_finalize_content_none_passthrough():
    hook = CompositeHook([AgentHook()])
    assert hook.finalize_content(_ctx(), None) is None


def test_composite_finalize_content_ordering():
    """First hook transforms first, result feeds second hook."""
    steps: list[str] = []

    class H1(AgentHook):
        def finalize_content(self, context, content):
            steps.append(f"H1:{content}")
            return content.upper()

    class H2(AgentHook):
        def finalize_content(self, context, content):
            steps.append(f"H2:{content}")
            return content + "!"

    hook = CompositeHook([H1(), H2()])
    result = hook.finalize_content(_ctx(), "hi")
    assert result == "HI!"
    assert steps == ["H1:hi", "H2:HI"]


# ---------------------------------------------------------------------------
# wants_streaming: any-semantics
# ---------------------------------------------------------------------------


def test_composite_wants_streaming_any_true():
    class No(AgentHook):
        def wants_streaming(self):
            return False

    class Yes(AgentHook):
        def wants_streaming(self):
            return True

    hook = CompositeHook([No(), Yes(), No()])
    assert hook.wants_streaming() is True


def test_composite_wants_streaming_all_false():
    hook = CompositeHook([AgentHook(), AgentHook()])
    assert hook.wants_streaming() is False


def test_composite_wants_streaming_empty():
    hook = CompositeHook([])
    assert hook.wants_streaming() is False


# ---------------------------------------------------------------------------
# Empty hooks list: behaves like no-op AgentHook
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_composite_empty_hooks_no_ops():
    hook = CompositeHook([])
    ctx = _ctx()
    await hook.before_iteration(ctx)
    await hook.on_stream(ctx, "delta")
    await hook.on_stream_end(ctx, resuming=False)
    await hook.before_execute_tools(ctx)
    await hook.after_iteration(ctx)
    assert hook.finalize_content(ctx, "test") == "test"


# ---------------------------------------------------------------------------
# Integration: AgentLoop with extra hooks
# ---------------------------------------------------------------------------


def _make_loop(tmp_path, hooks=None):
    from janniebot.agent.loop import AgentLoop
    from janniebot.bus.queue import MessageBus

    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    provider.generation.max_tokens = 4096

    with patch("janniebot.agent.loop.ContextBuilder"), \
         patch("janniebot.agent.loop.SessionManager"), \
         patch("janniebot.agent.loop.SubagentManager") as mock_sub_mgr, \
         patch("janniebot.agent.loop.Consolidator"), \
         patch("janniebot.agent.loop.Dream"):
        mock_sub_mgr.return_value.cancel_by_session = AsyncMock(return_value=0)
        loop = AgentLoop(
            bus=bus, provider=provider, workspace=tmp_path, hooks=hooks,
        )
    return loop


@pytest.mark.asyncio
async def test_agent_loop_extra_hook_receives_calls(tmp_path):
    """Extra hook passed to AgentLoop is called alongside core LoopHook."""
    from janniebot.providers.base import LLMResponse

    events: list[str] = []

    class TrackingHook(AgentHook):
        async def before_iteration(self, context):
            events.append(f"before_iter:{context.iteration}")

        async def after_iteration(self, context):
            events.append(f"after_iter:{context.iteration}")

    loop = _make_loop(tmp_path, hooks=[TrackingHook()])
    loop.provider.chat_with_retry = AsyncMock(
        return_value=LLMResponse(content="done", tool_calls=[], usage={})
    )
    loop.tools.get_definitions = MagicMock(return_value=[])

    content, tools_used, messages = await loop._run_agent_loop(
        [{"role": "user", "content": "hi"}]
    )

    assert content == "done"
    assert "before_iter:0" in events
    assert "after_iter:0" in events


@pytest.mark.asyncio
async def test_agent_loop_extra_hook_error_isolation(tmp_path):
    """A faulty extra hook does not crash the agent loop."""
    from janniebot.providers.base import LLMResponse

    class BadHook(AgentHook):
        async def before_iteration(self, context):
            raise RuntimeError("I am broken")

    loop = _make_loop(tmp_path, hooks=[BadHook()])
    loop.provider.chat_with_retry = AsyncMock(
        return_value=LLMResponse(content="still works", tool_calls=[], usage={})
    )
    loop.tools.get_definitions = MagicMock(return_value=[])

    content, _, _ = await loop._run_agent_loop(
        [{"role": "user", "content": "hi"}]
    )

    assert content == "still works"


@pytest.mark.asyncio
async def test_agent_loop_extra_hooks_do_not_swallow_loop_hook_errors(tmp_path):
    """Extra hooks must not change the core LoopHook failure behavior."""
    from janniebot.providers.base import LLMResponse, ToolCallRequest

    loop = _make_loop(tmp_path, hooks=[AgentHook()])
    loop.provider.chat_with_retry = AsyncMock(return_value=LLMResponse(
        content="working",
        tool_calls=[ToolCallRequest(id="c1", name="list_dir", arguments={"path": "."})],
        usage={},
    ))
    loop.tools.get_definitions = MagicMock(return_value=[])
    loop.tools.execute = AsyncMock(return_value="ok")

    async def bad_progress(*args, **kwargs):
        raise RuntimeError("progress failed")

    with pytest.raises(RuntimeError, match="progress failed"):
        await loop._run_agent_loop([], on_progress=bad_progress)


@pytest.mark.asyncio
async def test_agent_loop_no_hooks_backward_compat(tmp_path):
    """Without hooks param, behavior is identical to before."""
    from janniebot.providers.base import LLMResponse, ToolCallRequest

    loop = _make_loop(tmp_path)
    loop.provider.chat_with_retry = AsyncMock(return_value=LLMResponse(
        content="working",
        tool_calls=[ToolCallRequest(id="c1", name="list_dir", arguments={"path": "."})],
    ))
    loop.tools.get_definitions = MagicMock(return_value=[])
    loop.tools.execute = AsyncMock(return_value="ok")
    loop.max_iterations = 2

    content, tools_used, _ = await loop._run_agent_loop([])
    assert content == (
        "I reached the maximum number of tool call iterations (2) "
        "without completing the task. You can try breaking the task into smaller steps."
    )
    assert tools_used == ["list_dir", "list_dir"]
