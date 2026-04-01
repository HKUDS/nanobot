"""Tests for CompositeHook."""

from unittest.mock import AsyncMock

import pytest

from nanobot.agent.hook import AgentHook, AgentHookContext
from nanobot.agent.hook_composite import CompositeHook


@pytest.mark.asyncio
async def test_composite_hook_delegates_all_callbacks():
    """All hook callbacks should be forwarded to every wrapped hook."""

    class RecordingHook(AgentHook):
        def __init__(self):
            self.events: list[str] = []

        def wants_streaming(self) -> bool:
            self.events.append("wants_streaming")
            return False

        async def before_iteration(self, context: AgentHookContext) -> None:
            self.events.append("before_iteration")

        async def on_stream(self, context: AgentHookContext, delta: str) -> None:
            self.events.append("on_stream")

        async def on_stream_end(self, context: AgentHookContext, *, resuming: bool) -> None:
            self.events.append("on_stream_end")

        async def before_execute_tools(self, context: AgentHookContext) -> None:
            self.events.append("before_execute_tools")

        async def after_iteration(self, context: AgentHookContext) -> None:
            self.events.append("after_iteration")

        def finalize_content(self, context: AgentHookContext, content: str | None) -> str | None:
            self.events.append("finalize_content")
            return content

    h1 = RecordingHook()
    h2 = RecordingHook()
    composite = CompositeHook([h1, h2])

    ctx = AgentHookContext(iteration=0, messages=[])

    assert composite.wants_streaming() is False
    await composite.before_iteration(ctx)
    await composite.on_stream(ctx, "delta")
    await composite.on_stream_end(ctx, resuming=True)
    await composite.before_execute_tools(ctx)
    await composite.after_iteration(ctx)
    assert composite.finalize_content(ctx, "hello") == "hello"

    for h in (h1, h2):
        assert h.events == [
            "wants_streaming",
            "before_iteration",
            "on_stream",
            "on_stream_end",
            "before_execute_tools",
            "after_iteration",
            "finalize_content",
        ]


@pytest.mark.asyncio
async def test_composite_hook_wants_streaming_true_if_any_child_true():
    class StreamingHook(AgentHook):
        def wants_streaming(self) -> bool:
            return True

    composite = CompositeHook([AgentHook(), StreamingHook()])
    assert composite.wants_streaming() is True


@pytest.mark.asyncio
async def test_composite_finalize_returns_last_non_none():
    """finalize_content should chain: result of h1 feeds into h2."""

    class FirstHook(AgentHook):
        def finalize_content(self, context, content):
            return content.upper() if content else content

    class SecondHook(AgentHook):
        def finalize_content(self, context, content):
            return f"[{content}]" if content else content

    composite = CompositeHook([FirstHook(), SecondHook()])
    ctx = AgentHookContext(iteration=0, messages=[])
    result = composite.finalize_content(ctx, "hello")
    assert result == "[HELLO]"
