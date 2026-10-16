"""Tests for the per-invocation tool context (tool_call_id + invocation_key)."""

from __future__ import annotations

import asyncio

import pytest

from nanobot.agent.hook import AgentHook, AgentHookContext
from nanobot.agent.tools.base import Tool
from nanobot.agent.tools.context import (
    RequestContext,
    ToolInvocationContext,
    current_tool_invocation_context,
    request_context,
    tool_invocation_context,
    tool_invocation_key,
)
from nanobot.agent.tools.execution import execute_tool_calls
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.providers.base import ToolCallRequest


class _CapturingTool(Tool):
    """Records the invocation context visible while it executes."""

    def __init__(self, name: str, *, delay: float = 0.0, read_only: bool = True):
        self._name = name
        self._delay = delay
        self._read_only = read_only
        self.seen: list[ToolInvocationContext | None] = []

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._name

    @property
    def parameters(self) -> dict:
        return {"type": "object", "properties": {}, "required": []}

    @property
    def read_only(self) -> bool:
        return self._read_only

    async def execute(self, **kwargs):
        self.seen.append(current_tool_invocation_context())
        await asyncio.sleep(self._delay)
        # Still bound after yielding to the event loop.
        self.seen.append(current_tool_invocation_context())
        return self._name


async def _run(tools: ToolRegistry, calls: list[ToolCallRequest], *, concurrent: bool) -> None:
    await execute_tool_calls(
        tools,
        calls,
        concurrent=concurrent,
        external_lookup_counts={},
        workspace_violation_counts={},
        hook=AgentHook(),
        context=AgentHookContext(iteration=0, messages=[]),
    )


def test_invocation_key_is_stable_and_scoped() -> None:
    key = tool_invocation_key("telegram:42", "call_1")
    assert key == tool_invocation_key("telegram:42", "call_1")
    assert len(key) == 64
    # Different call, different session: different keys.
    assert key != tool_invocation_key("telegram:42", "call_2")
    assert key != tool_invocation_key("telegram:43", "call_1")
    # No session (ephemeral / SDK use) means no key, never a guess.
    assert tool_invocation_key(None, "call_1") is None
    assert tool_invocation_key("", "call_1") is None


def test_invocation_context_binds_and_restores() -> None:
    assert current_tool_invocation_context() is None
    outer = ToolInvocationContext(tool_call_id="outer")
    with tool_invocation_context(outer):
        assert current_tool_invocation_context() is outer
        with tool_invocation_context(ToolInvocationContext(tool_call_id="inner")):
            assert current_tool_invocation_context().tool_call_id == "inner"
        assert current_tool_invocation_context() is outer
    assert current_tool_invocation_context() is None


@pytest.mark.asyncio
async def test_single_tool_call_sees_its_own_identity() -> None:
    tools = ToolRegistry()
    tool = _CapturingTool("probe")
    tools.register(tool)
    request = RequestContext(channel="test", chat_id="1", session_key="test:1")

    with request_context(request):
        await _run(tools, [ToolCallRequest(id="call_a", name="probe", arguments={})], concurrent=False)

    assert [ctx.tool_call_id for ctx in tool.seen] == ["call_a", "call_a"]
    assert tool.seen[0].invocation_key == tool_invocation_key("test:1", "call_a")
    assert tool.seen[0] == tool.seen[1]
    # Nothing leaks past the execution.
    assert current_tool_invocation_context() is None


@pytest.mark.asyncio
async def test_parallel_tool_calls_see_their_own_identities() -> None:
    tools = ToolRegistry()
    slow = _CapturingTool("slow", delay=0.03)
    fast = _CapturingTool("fast", delay=0.0)
    tools.register(slow)
    tools.register(fast)
    request = RequestContext(channel="test", chat_id="1", session_key="test:1")

    with request_context(request):
        await _run(
            tools,
            [
                ToolCallRequest(id="call_slow", name="slow", arguments={}),
                ToolCallRequest(id="call_fast", name="fast", arguments={}),
            ],
            concurrent=True,
        )

    # Each tool saw only its own id, before and after yielding to the loop,
    # even though both ran concurrently in the same request.
    assert [ctx.tool_call_id for ctx in slow.seen] == ["call_slow", "call_slow"]
    assert [ctx.tool_call_id for ctx in fast.seen] == ["call_fast", "call_fast"]
    assert slow.seen[0].invocation_key != fast.seen[0].invocation_key
    assert current_tool_invocation_context() is None


@pytest.mark.asyncio
async def test_invocation_key_is_none_without_a_session() -> None:
    tools = ToolRegistry()
    tool = _CapturingTool("probe")
    tools.register(tool)

    await _run(tools, [ToolCallRequest(id="call_a", name="probe", arguments={})], concurrent=False)

    assert tool.seen[0].tool_call_id == "call_a"
    assert tool.seen[0].invocation_key is None
