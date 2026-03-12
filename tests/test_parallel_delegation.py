"""Tests for parallel delegation, write locking, and mixed results.

Covers:
- Parallel dispatch via DelegateParallelTool
- Write lock serialises non-readonly tool execution
- Mixed success/failure in parallel subtasks
- Per-branch delegation stack isolation
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from nanobot.agent.coordinator import Coordinator, build_default_registry
from nanobot.agent.tools.delegate import DelegateParallelTool, _CycleError
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.config.schema import AgentConfig
from nanobot.providers.base import LLMProvider, LLMResponse

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class FakeProvider(LLMProvider):
    def __init__(self, responses: list[str] | None = None) -> None:
        super().__init__()
        self._responses = responses or ['{"role": "general"}']
        self._idx = 0

    def get_default_model(self) -> str:
        return "fake-model"

    async def chat(self, **kwargs: Any) -> LLMResponse:
        text = self._responses[min(self._idx, len(self._responses) - 1)]
        self._idx += 1
        return LLMResponse(content=text)


def _make_agent_config(tmp_path: Path, **overrides: Any) -> AgentConfig:
    defaults: dict[str, Any] = dict(
        workspace=str(tmp_path),
        model="test-model",
        memory_window=10,
        max_iterations=5,
        planning_enabled=False,
        verification_mode="off",
    )
    defaults.update(overrides)
    return AgentConfig(**defaults)


# ---------------------------------------------------------------------------
# Parallel dispatch tests
# ---------------------------------------------------------------------------


class TestParallelDelegation:
    """Integration-level tests for concurrent delegation."""

    async def test_parallel_subtasks_run_concurrently(self) -> None:
        """Parallel dispatches overlap in time (not strictly sequential)."""
        tool = DelegateParallelTool()
        start_times: list[float] = []
        end_times: list[float] = []

        async def tracked_dispatch(role: str, task: str, ctx: str | None) -> str:
            import time

            start_times.append(time.monotonic())
            await asyncio.sleep(0.05)
            end_times.append(time.monotonic())
            return f"done:{task}"

        tool.set_dispatch(tracked_dispatch)
        result = await tool.execute(
            subtasks=[
                {"task": "a", "target_role": "code"},
                {"task": "b", "target_role": "research"},
                {"task": "c", "target_role": "writing"},
            ]
        )
        assert result.success
        # All three started before the first finished (concurrent)
        assert len(start_times) == 3
        assert max(start_times) < min(end_times)

    async def test_mixed_success_and_failure(self) -> None:
        """When some subtasks fail, the result contains both successes and errors."""
        tool = DelegateParallelTool()

        async def mixed(role: str, task: str, ctx: str | None) -> str:
            if "bad" in task:
                raise RuntimeError("task went wrong")
            return f"ok:{task}"

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

        async def always_fail(role: str, task: str, ctx: str | None) -> str:
            raise RuntimeError("nope")

        tool.set_dispatch(always_fail)
        result = await tool.execute(subtasks=[{"task": "t1"}, {"task": "t2"}])
        assert result.success  # Tool itself succeeds with error summaries
        assert result.output.count("ERROR") == 2

    async def test_cycle_in_parallel_branch(self) -> None:
        """Cycle error in one branch doesn't crash other branches."""
        tool = DelegateParallelTool()
        call_count = 0

        async def maybe_cycle(role: str, task: str, ctx: str | None) -> str:
            nonlocal call_count
            call_count += 1
            if "cycle" in task:
                raise _CycleError("cycle: A → B → A")
            await asyncio.sleep(0.01)
            return f"ok:{task}"

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

    async def test_per_branch_stack_isolation(self, tmp_path: Path) -> None:
        """Each parallel branch gets independent delegation stack tracking."""
        from nanobot.agent.loop import AgentLoop
        from nanobot.bus.queue import MessageBus

        provider = FakeProvider(["result"] * 10)
        bus = MessageBus()
        loop = AgentLoop(bus, provider, _make_agent_config(tmp_path))

        registry = build_default_registry("general")
        loop._coordinator = Coordinator(
            provider=provider, registry=registry, default_role="general"
        )
        loop._dispatcher.coordinator = loop._coordinator
        loop._wire_delegate_tools()

        # Delegate to code and research in parallel — neither is in the stack
        loop._delegation_stack = []
        tool = loop.tools.get("delegate_parallel")
        assert tool is not None
        result = await tool.execute(
            subtasks=[
                {"task": "write code", "target_role": "code"},
                {"task": "find info", "target_role": "research"},
            ]
        )
        assert result.success
        # Stack should be empty after both parallel branches finish
        assert loop._delegation_stack == []


# ---------------------------------------------------------------------------
# Write lock tests
# ---------------------------------------------------------------------------


class TestWriteLock:
    """Tests for ToolRegistry write-lock serialisation."""

    async def test_readonly_tools_run_concurrently(self) -> None:
        """Multiple readonly tools can execute in parallel."""
        from nanobot.agent.tools.base import Tool, ToolResult

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

        import time

        t0 = time.monotonic()
        r1, r2 = await asyncio.gather(
            reg.execute("slow_read_a", {}),
            reg.execute("slow_read_b", {}),
        )
        elapsed = time.monotonic() - t0
        assert r1.success and r2.success
        # Should be < 0.1s total (concurrent), not ~0.1s (sequential)
        assert elapsed < 0.08

    async def test_write_tools_serialised(self) -> None:
        """Non-readonly tools are serialised by the write lock."""
        from nanobot.agent.tools.base import Tool, ToolResult

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
