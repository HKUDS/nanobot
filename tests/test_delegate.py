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
from pathlib import Path
from typing import Any

import pytest
from conftest import FakeProvider

from nanobot.agent.coordinator import Coordinator, build_default_registry
from nanobot.agent.tools.delegate import (
    DelegateParallelTool,
    DelegateTool,
    DelegationResult,
    _CycleError,
)
from nanobot.config.schema import AgentConfig
from nanobot.providers.base import LLMResponse

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Delegation dispatch integration (via AgentLoop)
# ---------------------------------------------------------------------------


class TestDelegationDispatch:
    async def test_cycle_detection(self, tmp_path: Path) -> None:
        """Delegating to a role already in the ancestry raises _CycleError."""
        from nanobot.agent.loop import AgentLoop, _delegation_ancestry
        from nanobot.bus.queue import MessageBus

        provider = FakeProvider(['{"role": "code"}', "result"])
        bus = MessageBus()
        loop = AgentLoop(bus, provider, _make_agent_config(tmp_path))

        # Set up coordinator
        registry = build_default_registry("general")
        loop._coordinator = Coordinator(
            provider=provider, registry=registry, default_role="general"
        )
        loop._dispatcher.coordinator = loop._coordinator
        loop._wire_delegate_tools()

        # Simulate being inside a "code" delegation via ContextVar
        token = _delegation_ancestry.set(("code",))
        try:
            with pytest.raises(_CycleError, match="cycle"):
                await loop._dispatch_delegation("code", "do more code", None)
        finally:
            _delegation_ancestry.reset(token)

    async def test_deep_chain_allowed(self, tmp_path: Path) -> None:
        """A → B → C is allowed (no cycle)."""
        from nanobot.agent.loop import AgentLoop, _delegation_ancestry
        from nanobot.bus.queue import MessageBus

        # Provider returns responses for: classify → research, then agent response
        provider = FakeProvider(['{"role": "research"}', "research result"])
        bus = MessageBus()
        loop = AgentLoop(bus, provider, _make_agent_config(tmp_path))

        registry = build_default_registry("general")
        loop._coordinator = Coordinator(
            provider=provider, registry=registry, default_role="general"
        )
        loop._dispatcher.coordinator = loop._coordinator
        loop._wire_delegate_tools()

        # Currently inside "code" role via ContextVar
        token = _delegation_ancestry.set(("code",))
        try:
            # Delegating to "research" should work (no cycle)
            result = await loop._dispatch_delegation("research", "find info", None)
            assert result  # Got a result
            # Ancestry restored after delegation completes
            assert _delegation_ancestry.get() == ("code",)
        finally:
            _delegation_ancestry.reset(token)

    async def test_direct_role_bypasses_classifier(self, tmp_path: Path) -> None:
        """When target_role is specified and exists, classifier is not called."""
        from nanobot.agent.loop import AgentLoop
        from nanobot.bus.queue import MessageBus

        call_count = 0

        class CountingProvider(FakeProvider):
            async def chat(self, **kwargs: Any) -> LLMResponse:
                nonlocal call_count
                call_count += 1
                return LLMResponse(content="delegated result")

        provider = CountingProvider()
        bus = MessageBus()
        loop = AgentLoop(bus, provider, _make_agent_config(tmp_path))

        registry = build_default_registry("general")
        loop._coordinator = Coordinator(
            provider=provider, registry=registry, default_role="general"
        )
        loop._dispatcher.coordinator = loop._coordinator
        loop._wire_delegate_tools()

        call_count = 0
        result = await loop._dispatch_delegation("code", "write code", None)
        # Direct role: no classifier call.  Expect 2 calls: 1 for the agent
        # execution + 1 for the tool-use retry (since no tools were used).
        assert call_count == 2
        assert result

    async def test_routing_trace_recorded(self, tmp_path: Path) -> None:
        """Delegation events are recorded in the routing trace."""
        from nanobot.agent.loop import AgentLoop
        from nanobot.bus.queue import MessageBus

        provider = FakeProvider(["delegated result"])
        bus = MessageBus()
        loop = AgentLoop(bus, provider, _make_agent_config(tmp_path))

        registry = build_default_registry("general")
        loop._coordinator = Coordinator(
            provider=provider, registry=registry, default_role="general"
        )
        loop._dispatcher.coordinator = loop._coordinator
        loop._wire_delegate_tools()

        await loop._dispatch_delegation("code", "write tests", None)

        trace = loop.get_routing_trace()
        assert len(trace) >= 2
        assert trace[0]["event"] == "delegate"
        assert trace[0]["role"] == "code"
        assert trace[1]["event"] == "delegate_complete"
        assert trace[1]["success"] is True

    async def test_parallel_same_role_at_depth_zero(self, tmp_path: Path) -> None:
        """At depth 0 (empty ancestry), delegating to the same role twice is allowed."""
        from nanobot.agent.loop import AgentLoop, _delegation_ancestry
        from nanobot.bus.queue import MessageBus

        provider = FakeProvider(["result"])
        bus = MessageBus()
        loop = AgentLoop(bus, provider, _make_agent_config(tmp_path))

        registry = build_default_registry("general")
        loop._coordinator = Coordinator(
            provider=provider, registry=registry, default_role="general"
        )
        loop._dispatcher.coordinator = loop._coordinator
        loop._wire_delegate_tools()

        # Ancestry is empty (depth 0) — same-role delegation should succeed
        assert _delegation_ancestry.get() == ()
        result = await loop._dispatch_delegation("code", "task A", None)
        assert result
        assert _delegation_ancestry.get() == ()  # Restored after completion

    async def test_max_delegation_depth_respected(self, tmp_path: Path) -> None:
        """max_delegation_depth from config caps self.max_delegations on the dispatcher."""
        from nanobot.agent.loop import AgentLoop
        from nanobot.bus.queue import MessageBus

        provider = FakeProvider(["result"])
        bus = MessageBus()
        config = _make_agent_config(tmp_path, max_delegation_depth=3)
        loop = AgentLoop(bus, provider, config)

        assert loop._dispatcher.max_delegations == 3
