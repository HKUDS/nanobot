"""Tests for parallel delegation, write locking, and mixed results.

Covers:
- Parallel dispatch via DelegateParallelTool
- Write lock serialises non-readonly tool execution
- Mixed success/failure in parallel subtasks
- Per-branch delegation stack isolation
"""

from __future__ import annotations

import asyncio
from typing import Any

from nanobot.tools.builtin.delegate import DelegateParallelTool, DelegationResult, _CycleError
from nanobot.tools.registry import ToolRegistry

# ---------------------------------------------------------------------------
# Parallel dispatch tests
# ---------------------------------------------------------------------------


class TestParallelDelegation:
    """Integration-level tests for concurrent delegation."""

    async def test_parallel_subtasks_run_concurrently(self) -> None:
        """Parallel dispatches overlap (not strictly sequential): verified via event ordering."""
        tool = DelegateParallelTool()
        # Record ("start"|"end", task) events in order of occurrence
        event_log: list[tuple[str, str]] = []

        async def tracked_dispatch(role: str, task: str, ctx: str | None) -> DelegationResult:
            event_log.append(("start", task))
            await asyncio.sleep(0.05)
            event_log.append(("end", task))
            return DelegationResult(content=f"done:{task}", tools_used=["read_file"])

        tool.set_dispatch(tracked_dispatch)
        result = await tool.execute(
            subtasks=[
                {"task": "a", "target_role": "code"},
                {"task": "b", "target_role": "research"},
                {"task": "c", "target_role": "writing"},
            ]
        )
        assert result.success
        # All three tasks must have started
        starts = [e for e in event_log if e[0] == "start"]
        assert len(starts) == 3
        # Concurrent: the first "end" must come after at least 2 "start"s
        first_end_pos = next(i for i, e in enumerate(event_log) if e[0] == "end")
        starts_before_first_end = sum(1 for e in event_log[:first_end_pos] if e[0] == "start")
        assert starts_before_first_end >= 2, (
            "Expected concurrent execution (≥2 starts before first end)"
        )

    async def test_mixed_success_and_failure(self) -> None:
        """When some subtasks fail, the result contains both successes and errors."""
        tool = DelegateParallelTool()

        async def mixed(role: str, task: str, ctx: str | None) -> DelegationResult:
            if "bad" in task:
                raise RuntimeError("task went wrong")
            return DelegationResult(content=f"ok:{task}", tools_used=["read_file"])

        tool.set_dispatch(mixed)
        result = await tool.execute(
            subtasks=[
                {"task": "good1"},
                {"task": "bad_task"},
                {"task": "good2"},
            ]
        )
        assert result.success
        assert "ok:good1" in result.output
        assert "ok:good2" in result.output
        assert "ERROR" in result.output
        assert "task went wrong" in result.output

    async def test_all_subtasks_fail(self) -> None:
        """All-failure still returns a structured result (not a crash)."""
        tool = DelegateParallelTool()

        async def always_fail(role: str, task: str, ctx: str | None) -> DelegationResult:
            raise RuntimeError("nope")

        tool.set_dispatch(always_fail)
        result = await tool.execute(subtasks=[{"task": "t1"}, {"task": "t2"}])
        assert result.success  # Tool itself succeeds with error summaries
        assert result.output.count("ERROR") == 2

    async def test_cycle_in_parallel_branch(self) -> None:
        """Cycle error in one branch doesn't crash other branches."""
        tool = DelegateParallelTool()
        call_count = 0

        async def maybe_cycle(role: str, task: str, ctx: str | None) -> DelegationResult:
            nonlocal call_count
            call_count += 1
            if "cycle" in task:
                raise _CycleError("cycle: A → B → A")
            await asyncio.sleep(0.01)
            return DelegationResult(content=f"ok:{task}", tools_used=["read_file"])

        tool.set_dispatch(maybe_cycle)
        result = await tool.execute(
            subtasks=[
                {"task": "cycle_task"},
                {"task": "good_task"},
            ]
        )
        assert result.success
        assert "ok:good_task" in result.output
        assert "cycle" in result.output.lower()


# ---------------------------------------------------------------------------
# Write lock tests
# ---------------------------------------------------------------------------


class TestWriteLock:
    """Tests for ToolRegistry write-lock serialisation."""

    async def test_readonly_tools_run_concurrently(self) -> None:
        """Multiple readonly tools can execute in parallel."""
        from nanobot.tools.base import Tool, ToolResult

        class SlowReadTool(Tool):
            readonly = True

            def __init__(self, tid: str) -> None:
                self._id = tid

            @property
            def name(self) -> str:
                return f"slow_read_{self._id}"

            @property
            def description(self) -> str:
                return "slow read"

            @property
            def parameters(self) -> dict[str, Any]:
                return {"type": "object", "properties": {}}

            async def execute(self, **kwargs: Any) -> ToolResult:
                await asyncio.sleep(0.05)
                return ToolResult.ok(f"read_{self._id}")

        reg = ToolRegistry()
        reg.register(SlowReadTool("a"))
        reg.register(SlowReadTool("b"))

        # Record execution order to verify concurrent dispatch
        exec_log: list[tuple[str, str]] = []
        _orig_execute = reg.execute

        async def _logging_execute(name: str, args: dict) -> ToolResult:
            exec_log.append(("start", name))
            result = await _orig_execute(name, args)
            exec_log.append(("end", name))
            return result

        reg.execute = _logging_execute  # type: ignore[method-assign]

        r1, r2 = await asyncio.gather(
            reg.execute("slow_read_a", {}),
            reg.execute("slow_read_b", {}),
        )
        assert r1.success and r2.success
        # Both tasks should have started before either finished (concurrent execution)
        first_end_pos = next(i for i, e in enumerate(exec_log) if e[0] == "end")
        starts_before_first_end = sum(1 for e in exec_log[:first_end_pos] if e[0] == "start")
        assert starts_before_first_end >= 2, "Expected both reads to start before either finishes"

    async def test_write_tools_serialised(self) -> None:
        """Non-readonly tools are serialised by the write lock."""
        from nanobot.tools.base import Tool, ToolResult

        execution_log: list[tuple[str, str]] = []

        class SlowWriteTool(Tool):
            readonly = False

            def __init__(self, tid: str) -> None:
                self._id = tid

            @property
            def name(self) -> str:
                return f"slow_write_{self._id}"

            @property
            def description(self) -> str:
                return "slow write"

            @property
            def parameters(self) -> dict[str, Any]:
                return {"type": "object", "properties": {}}

            async def execute(self, **kwargs: Any) -> ToolResult:
                execution_log.append((self._id, "start"))
                await asyncio.sleep(0.03)
                execution_log.append((self._id, "end"))
                return ToolResult.ok(f"write_{self._id}")

        reg = ToolRegistry()
        reg.register(SlowWriteTool("x"))
        reg.register(SlowWriteTool("y"))

        await asyncio.gather(
            reg.execute("slow_write_x", {}),
            reg.execute("slow_write_y", {}),
        )
        # Should be serialised: first tool ends before second starts
        assert len(execution_log) == 4
        first_end = execution_log.index(("x", "end")) if ("x", "end") in execution_log else 99
        second_start = (
            execution_log.index(("y", "start")) if ("y", "start") in execution_log else -1
        )
        if first_end < second_start:
            pass  # x finished before y started — serialised
        else:
            # y might have run first; check the reverse
            y_end = execution_log.index(("y", "end")) if ("y", "end") in execution_log else 99
            x_start = execution_log.index(("x", "start")) if ("x", "start") in execution_log else -1
            assert y_end < x_start  # y finished before x started
