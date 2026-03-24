"""Tests for TraceContext correlation ID propagation."""

from __future__ import annotations

import asyncio

from nanobot.observability.tracing import TraceContext, bind_trace
from nanobot.providers.base import ToolCallRequest
from nanobot.tools.base import Tool, ToolResult
from nanobot.tools.executor import ToolExecutor
from nanobot.tools.registry import ToolRegistry

# -- helpers ---------------------------------------------------------------


class _CaptureTool(Tool):
    """Tool that captures the TraceContext visible during execution."""

    readonly = True

    def __init__(self, captured: list[dict[str, str]]) -> None:
        self._captured = captured

    @property
    def name(self) -> str:
        return "capture"

    @property
    def description(self) -> str:
        return "captures trace ctx"

    @property
    def parameters(self) -> dict:
        return {"type": "object", "properties": {}}

    async def execute(self, **_kwargs: object) -> ToolResult:
        self._captured.append(TraceContext.get())
        return ToolResult.ok("ok")


class _WriteCaptureTool(_CaptureTool):
    readonly = False

    @property
    def name(self) -> str:
        return "write_capture"


# -- unit tests ------------------------------------------------------------


def test_new_request_generates_unique_ids() -> None:
    rid1 = TraceContext.new_request(session_id="s1", agent_id="a1")
    rid2 = TraceContext.new_request(session_id="s1", agent_id="a1")
    assert rid1 != rid2
    assert len(rid1) == 12


def test_set_and_get_roundtrip() -> None:
    TraceContext.set(request_id="r1", session_id="s2", agent_id="a3")
    ctx = TraceContext.get()
    assert ctx == {"request_id": "r1", "session_id": "s2", "agent_id": "a3"}


def test_partial_set_preserves_others() -> None:
    TraceContext.set(request_id="r0", session_id="s0", agent_id="a0")
    TraceContext.set(session_id="s_new")
    ctx = TraceContext.get()
    assert ctx["session_id"] == "s_new"
    assert ctx["request_id"] == "r0"
    assert ctx["agent_id"] == "a0"


def test_bind_trace_carries_ids() -> None:
    TraceContext.set(request_id="rx", session_id="sx", agent_id="ax")
    bound = bind_trace()
    # loguru bound loggers expose _core with extra; just verify no crash
    assert bound is not None


# -- integration: IDs flow through tool execution --------------------------


async def test_trace_flows_through_readonly_batch() -> None:
    captured: list[dict[str, str]] = []
    reg = ToolRegistry()
    reg.register(_CaptureTool(captured))
    executor = ToolExecutor(reg)

    TraceContext.new_request(session_id="sess-1", agent_id="agent-1")
    expected = TraceContext.get()

    calls = [ToolCallRequest(id="c1", name="capture", arguments={})]
    await executor.execute_batch(calls)

    assert len(captured) == 1
    assert captured[0] == expected


async def test_trace_flows_through_write_tool() -> None:
    captured: list[dict[str, str]] = []
    reg = ToolRegistry()
    reg.register(_WriteCaptureTool(captured))
    executor = ToolExecutor(reg)

    TraceContext.new_request(session_id="sess-w", agent_id="agent-w")
    expected = TraceContext.get()

    calls = [ToolCallRequest(id="w1", name="write_capture", arguments={})]
    await executor.execute_batch(calls)

    assert len(captured) == 1
    assert captured[0] == expected


async def test_trace_flows_through_mixed_batch() -> None:
    """Verify IDs survive a mixed readonly+write batch ordering."""
    captured: list[dict[str, str]] = []
    reg = ToolRegistry()
    reg.register(_CaptureTool(captured))
    reg.register(_WriteCaptureTool(captured))
    executor = ToolExecutor(reg)

    TraceContext.new_request(session_id="sess-m", agent_id="agent-m")
    expected = TraceContext.get()

    calls = [
        ToolCallRequest(id="r1", name="capture", arguments={}),
        ToolCallRequest(id="r2", name="capture", arguments={}),
        ToolCallRequest(id="w1", name="write_capture", arguments={}),
        ToolCallRequest(id="r3", name="capture", arguments={}),
    ]
    await executor.execute_batch(calls)

    assert len(captured) == 4
    for ctx in captured:
        assert ctx == expected


async def test_child_task_inherits_trace() -> None:
    """Correlation IDs are inherited by child asyncio tasks."""
    TraceContext.new_request(session_id="sess-child", agent_id="agent-child")
    parent_ctx = TraceContext.get()

    child_ctx: dict[str, str] = {}

    async def _child() -> None:
        child_ctx.update(TraceContext.get())

    await asyncio.create_task(_child())
    assert child_ctx == parent_ctx
