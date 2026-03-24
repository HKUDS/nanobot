"""Tests for routing trace recording and in-memory trace access.

Covers:
- In-memory routing trace entries for classify / delegate / cycle block
- Trace entry structure and fields
- Per-role invocation tracking via trace
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from conftest import FakeProvider

from nanobot.config.schema import AgentConfig
from nanobot.coordination.coordinator import Coordinator, build_default_registry
from nanobot.providers.base import LLMProvider
from nanobot.tools.builtin.delegate import _CycleError

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


def _make_loop(tmp_path: Path, provider: LLMProvider | None = None):
    """Create an AgentLoop with coordinator wired up."""
    from nanobot.agent.agent_factory import build_agent
    from nanobot.bus.queue import MessageBus

    prov = provider or FakeProvider(["result"] * 20)
    bus = MessageBus()
    loop = build_agent(bus=bus, provider=prov, config=_make_agent_config(tmp_path))

    registry = build_default_registry("general")
    loop._coordinator = Coordinator(provider=prov, registry=registry, default_role="general")
    loop._dispatcher.coordinator = loop._coordinator
    loop._dispatcher.wire_delegate_tools(available_roles_fn=loop._capabilities.role_names)

    return loop


# ---------------------------------------------------------------------------
# Metric key helpers were here — removed with MetricsCollector (now in Langfuse)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# In-memory trace recording
# ---------------------------------------------------------------------------


class TestRoutingTraceRecording:
    async def test_route_records_trace_entry(self, tmp_path: Path) -> None:
        loop = _make_loop(tmp_path)
        loop._dispatcher.record_route_trace("route", role="code", confidence=0.9, latency_ms=42.5)
        loop._dispatcher.record_route_trace(
            "route", role="research", confidence=0.8, latency_ms=30.0
        )

        trace = loop._dispatcher.get_routing_trace()
        assert len(trace) == 2
        assert trace[0]["event"] == "route"
        assert trace[0]["role"] == "code"
        assert trace[0]["confidence"] == 0.9
        assert trace[1]["role"] == "research"

    async def test_delegate_records_trace_entry(self, tmp_path: Path) -> None:
        loop = _make_loop(tmp_path)
        loop._dispatcher.record_route_trace("delegate", role="research", from_role="code", depth=1)

        trace = loop._dispatcher.get_routing_trace()
        assert len(trace) == 1
        assert trace[0]["event"] == "delegate"
        assert trace[0]["from_role"] == "code"
        assert trace[0]["depth"] == 1

    async def test_cycle_blocked_records_trace_entry(self, tmp_path: Path) -> None:
        loop = _make_loop(tmp_path)
        loop._dispatcher.record_route_trace(
            "delegate_cycle_blocked", role="code", from_role="code", success=False
        )

        trace = loop._dispatcher.get_routing_trace()
        assert len(trace) == 1
        assert trace[0]["event"] == "delegate_cycle_blocked"
        assert trace[0]["success"] is False

    async def test_delegate_complete_records_latency(self, tmp_path: Path) -> None:
        loop = _make_loop(tmp_path)
        loop._dispatcher.record_route_trace("delegate_complete", role="code", latency_ms=150.0)
        loop._dispatcher.record_route_trace("delegate_complete", role="code", latency_ms=200.0)

        trace = loop._dispatcher.get_routing_trace()
        assert len(trace) == 2
        assert trace[0]["latency_ms"] == 150.0
        assert trace[1]["latency_ms"] == 200.0

    async def test_trace_entry_has_timestamp(self, tmp_path: Path) -> None:
        loop = _make_loop(tmp_path)
        loop._dispatcher.record_route_trace("route", role="code")

        trace = loop._dispatcher.get_routing_trace()
        assert "timestamp" in trace[0]
        assert len(trace[0]["timestamp"]) > 0


# ---------------------------------------------------------------------------
# Per-role counters via trace
# ---------------------------------------------------------------------------


class TestPerRoleTracking:
    async def test_role_invocations_tracked_via_trace(self, tmp_path: Path) -> None:
        loop = _make_loop(tmp_path)

        loop._dispatcher.record_route_trace("route", role="code")
        loop._dispatcher.record_route_trace("route", role="code")
        loop._dispatcher.record_route_trace("route", role="research")

        trace = loop._dispatcher.get_routing_trace()
        code_routes = [t for t in trace if t["event"] == "route" and t["role"] == "code"]
        research_routes = [t for t in trace if t["event"] == "route" and t["role"] == "research"]
        assert len(code_routes) == 2
        assert len(research_routes) == 1


# ---------------------------------------------------------------------------
# Dispatch integration records trace
# ---------------------------------------------------------------------------


class TestDispatchRecordsTrace:
    async def test_dispatch_records_delegate_and_complete(self, tmp_path: Path) -> None:
        """dispatcher.dispatch records delegate + delegate_complete events."""
        loop = _make_loop(tmp_path, FakeProvider(["delegation result"]))

        await loop._dispatcher.dispatch("code", "write some code", None)

        trace = loop._dispatcher.get_routing_trace()
        complete_events = [t for t in trace if t["event"] == "delegate_complete"]
        assert len(complete_events) == 1
        assert complete_events[0]["success"] is True

    async def test_cycle_block_records_trace(self, tmp_path: Path) -> None:
        """Cycle detection records delegate_cycle_blocked in trace."""
        from nanobot.coordination.delegation import _delegation_ancestry

        loop = _make_loop(tmp_path)

        token = _delegation_ancestry.set(("code",))
        try:
            with pytest.raises(_CycleError):
                await loop._dispatcher.dispatch("code", "cause cycle", None)
        finally:
            _delegation_ancestry.reset(token)

        trace = loop._dispatcher.get_routing_trace()
        blocked = [t for t in trace if t["event"] == "delegate_cycle_blocked"]
        assert len(blocked) == 1
