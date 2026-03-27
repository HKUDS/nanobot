"""Tests for DelegateTool and delegation dispatch.

Covers:
- Delegate tool execute with mocked dispatch
- Cycle detection
- Target role routing (direct + classify fallback)
- DelegateParallelTool
- Error handling
"""

from __future__ import annotations

import asyncio

from nanobot.tools.builtin.delegate import (
    DelegateParallelTool,
    DelegateTool,
    DelegationResult,
    _CycleError,
)

# ---------------------------------------------------------------------------
# DelegateTool unit tests
# ---------------------------------------------------------------------------


class TestDelegateTool:
    async def test_no_dispatch_returns_error(self) -> None:
        tool = DelegateTool()
        result = await tool.execute(task="do something")
        assert not result.success
        assert "not available" in result.output.lower()

    async def test_dispatch_called(self) -> None:
        tool = DelegateTool()
        calls: list[tuple] = []

        async def fake_dispatch(role: str, task: str, ctx: str | None) -> DelegationResult:
            calls.append((role, task, ctx))
            return DelegationResult(content="result from delegate", tools_used=["read_file"])

        tool.set_dispatch(fake_dispatch)
        result = await tool.execute(task="find info", target_role="research")
        assert result.success
        assert "result from delegate" in result.output
        assert calls[0] == ("research", "find info", None)

    async def test_dispatch_with_context(self) -> None:
        tool = DelegateTool()

        async def fake_dispatch(role: str, task: str, ctx: str | None) -> DelegationResult:
            return DelegationResult(content=f"role={role} ctx={ctx}", tools_used=["exec"])

        tool.set_dispatch(fake_dispatch)
        result = await tool.execute(task="analyze", context="extra info")
        assert result.success
        assert "extra info" in result.output

    async def test_cycle_error_caught(self) -> None:
        tool = DelegateTool()

        async def cycle_dispatch(role: str, task: str, ctx: str | None) -> DelegationResult:
            raise _CycleError("Delegation cycle detected: A → B → A")

        tool.set_dispatch(cycle_dispatch)
        result = await tool.execute(task="something")
        assert not result.success
        assert "cycle" in result.output.lower()

    async def test_general_error_caught(self) -> None:
        tool = DelegateTool()

        async def error_dispatch(role: str, task: str, ctx: str | None) -> DelegationResult:
            raise RuntimeError("boom")

        tool.set_dispatch(error_dispatch)
        result = await tool.execute(task="something")
        assert not result.success
        assert "boom" in result.output


# ---------------------------------------------------------------------------
# DelegateParallelTool unit tests
# ---------------------------------------------------------------------------


class TestDelegateParallelTool:
    async def test_no_dispatch_returns_error(self) -> None:
        tool = DelegateParallelTool()
        result = await tool.execute(subtasks=[{"task": "x"}])
        assert not result.success

    async def test_too_many_subtasks(self) -> None:
        tool = DelegateParallelTool()

        async def noop(r: str, t: str, c: str | None) -> DelegationResult:
            return DelegationResult(content="ok", tools_used=[])

        tool.set_dispatch(noop)
        result = await tool.execute(subtasks=[{"task": f"t{i}"} for i in range(6)])
        assert not result.success
        assert "5" in result.output

    async def test_empty_subtasks(self) -> None:
        tool = DelegateParallelTool()

        async def noop(r: str, t: str, c: str | None) -> DelegationResult:
            return DelegationResult(content="ok", tools_used=[])

        tool.set_dispatch(noop)
        result = await tool.execute(subtasks=[])
        assert not result.success

    async def test_parallel_execution(self) -> None:
        tool = DelegateParallelTool()
        execution_order: list[str] = []

        async def tracked_dispatch(role: str, task: str, ctx: str | None) -> DelegationResult:
            execution_order.append(task)
            await asyncio.sleep(0.01)
            return DelegationResult(content=f"done:{task}", tools_used=["exec"])

        tool.set_dispatch(tracked_dispatch)
        result = await tool.execute(
            subtasks=[
                {"task": "task1", "target_role": "code"},
                {"task": "task2", "target_role": "research"},
            ]
        )
        assert result.success
        assert "task1" in result.output
        assert "task2" in result.output

    async def test_partial_failure(self) -> None:
        tool = DelegateParallelTool()

        async def mixed_dispatch(role: str, task: str, ctx: str | None) -> DelegationResult:
            if "fail" in task:
                raise RuntimeError("intentional failure")
            return DelegationResult(content=f"ok:{task}", tools_used=["exec"])

        tool.set_dispatch(mixed_dispatch)
        result = await tool.execute(
            subtasks=[
                {"task": "good_task"},
                {"task": "fail_task"},
            ]
        )
        assert result.success  # Overall returns OK with error details
        assert "ok:good_task" in result.output
        assert "ERROR" in result.output
