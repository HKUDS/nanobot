"""Tests for routing metrics counters, trace persistence, and CLI commands.

Covers:
- Metric counter increments on classify / delegate / cycle block
- Latency recording (sum + max)
- Per-role invocation and tool-call counters
- Trace JSONL file persistence
- CLI routing trace / metrics commands
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from nanobot.agent.coordinator import Coordinator, build_default_registry
from nanobot.agent.metrics import (
    DELEGATION_LATENCY_MAX_MS,
    DELEGATION_LATENCY_SUM_MS,
    ROUTING_CLASSIFICATIONS,
    ROUTING_CLASSIFY_LATENCY_MAX_MS,
    ROUTING_CLASSIFY_LATENCY_SUM_MS,
    ROUTING_CYCLES_BLOCKED,
    ROUTING_DELEGATIONS,
    MetricsCollector,
    role_invocations_key,
    role_tool_calls_key,
)
from nanobot.agent.tools.delegate import _CycleError
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


def _make_loop(tmp_path: Path, provider: LLMProvider | None = None):
    """Create an AgentLoop with coordinator and routing metrics wired up."""
    from nanobot.agent.loop import AgentLoop
    from nanobot.bus.queue import MessageBus

    prov = provider or FakeProvider(["result"] * 20)
    bus = MessageBus()
    loop = AgentLoop(bus, prov, _make_agent_config(tmp_path))

    registry = build_default_registry("general")
    loop._coordinator = Coordinator(
        provider=prov, registry=registry, default_role="general"
    )
    loop._wire_delegate_tools()

    # Set up routing metrics (normally done in run())
    loop._routing_metrics = MetricsCollector(
        tmp_path / "memory" / "routing_metrics.json",
        flush_interval_s=300.0,
    )
    loop._trace_path = tmp_path / "memory" / "routing_trace.jsonl"
    return loop


# ---------------------------------------------------------------------------
# Metric key helpers
# ---------------------------------------------------------------------------


class TestMetricKeyHelpers:
    def test_role_invocations_key(self) -> None:
        assert role_invocations_key("code") == "role_invocations:code"

    def test_role_tool_calls_key(self) -> None:
        assert role_tool_calls_key("research") == "role_tool_calls:research"


# ---------------------------------------------------------------------------
# Counter increments
# ---------------------------------------------------------------------------


class TestRoutingMetricCounters:
    async def test_route_increments_classification_counter(self, tmp_path: Path) -> None:
        loop = _make_loop(tmp_path)
        assert loop._routing_metrics is not None

        loop._record_route_trace("route", role="code", confidence=0.9, latency_ms=42.5)
        assert loop._routing_metrics.get(ROUTING_CLASSIFICATIONS) == 1

        loop._record_route_trace("route", role="research", confidence=0.8, latency_ms=30.0)
        assert loop._routing_metrics.get(ROUTING_CLASSIFICATIONS) == 2

    async def test_delegate_increments_delegation_counter(self, tmp_path: Path) -> None:
        loop = _make_loop(tmp_path)
        assert loop._routing_metrics is not None

        loop._record_route_trace("delegate", role="research", from_role="code", depth=1)
        assert loop._routing_metrics.get(ROUTING_DELEGATIONS) == 1

    async def test_cycle_blocked_increments_counter(self, tmp_path: Path) -> None:
        loop = _make_loop(tmp_path)
        assert loop._routing_metrics is not None

        loop._record_route_trace(
            "delegate_cycle_blocked", role="code", from_role="code", success=False
        )
        assert loop._routing_metrics.get(ROUTING_CYCLES_BLOCKED) == 1

    async def test_delegate_complete_records_latency(self, tmp_path: Path) -> None:
        loop = _make_loop(tmp_path)
        assert loop._routing_metrics is not None

        loop._record_route_trace("delegate_complete", role="code", latency_ms=150.0)
        loop._record_route_trace("delegate_complete", role="code", latency_ms=200.0)
        assert loop._routing_metrics.get(DELEGATION_LATENCY_SUM_MS) == 350
        assert loop._routing_metrics.get(DELEGATION_LATENCY_MAX_MS) == 200.0


# ---------------------------------------------------------------------------
# Latency recording
# ---------------------------------------------------------------------------


class TestLatencyMetrics:
    async def test_classify_latency_sum_and_max(self, tmp_path: Path) -> None:
        loop = _make_loop(tmp_path)
        assert loop._routing_metrics is not None

        loop._record_route_trace("route", role="code", latency_ms=50.0)
        loop._record_route_trace("route", role="research", latency_ms=80.0)

        assert loop._routing_metrics.get(ROUTING_CLASSIFY_LATENCY_SUM_MS) == 130
        assert loop._routing_metrics.get(ROUTING_CLASSIFY_LATENCY_MAX_MS) == 80.0

    async def test_delegation_latency_sum_and_max(self, tmp_path: Path) -> None:
        loop = _make_loop(tmp_path)
        assert loop._routing_metrics is not None

        loop._record_route_trace("delegate_complete", role="code", latency_ms=100.0)
        loop._record_route_trace("delegate_complete", role="research", latency_ms=250.0)
        loop._record_route_trace("delegate_complete", role="writing", latency_ms=75.0)

        assert loop._routing_metrics.get(DELEGATION_LATENCY_SUM_MS) == 425
        assert loop._routing_metrics.get(DELEGATION_LATENCY_MAX_MS) == 250.0


# ---------------------------------------------------------------------------
# Per-role counters
# ---------------------------------------------------------------------------


class TestPerRoleCounters:
    async def test_role_invocations_tracked_per_role(self, tmp_path: Path) -> None:
        loop = _make_loop(tmp_path)
        assert loop._routing_metrics is not None

        loop._record_route_trace("route", role="code")
        loop._record_route_trace("route", role="code")
        loop._record_route_trace("route", role="research")

        assert loop._routing_metrics.get(role_invocations_key("code")) == 2
        assert loop._routing_metrics.get(role_invocations_key("research")) == 1
        assert loop._routing_metrics.get(role_invocations_key("writing")) == 0


# ---------------------------------------------------------------------------
# Trace JSONL persistence
# ---------------------------------------------------------------------------


class TestTracePersistence:
    async def test_trace_written_to_jsonl(self, tmp_path: Path) -> None:
        loop = _make_loop(tmp_path)
        trace_path = loop._trace_path

        loop._record_route_trace("route", role="code", confidence=0.95, latency_ms=40.0)
        loop._record_route_trace("delegate", role="research", from_role="code")

        assert trace_path.exists()
        lines = trace_path.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 2

        entry0 = json.loads(lines[0])
        assert entry0["event"] == "route"
        assert entry0["role"] == "code"
        assert entry0["confidence"] == 0.95

        entry1 = json.loads(lines[1])
        assert entry1["event"] == "delegate"
        assert entry1["from_role"] == "code"

    async def test_trace_appends_not_overwrites(self, tmp_path: Path) -> None:
        loop = _make_loop(tmp_path)

        loop._record_route_trace("route", role="code")
        loop._record_route_trace("route", role="research")
        loop._record_route_trace("route", role="writing")

        lines = loop._trace_path.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 3

    async def test_trace_survives_io_error(self, tmp_path: Path) -> None:
        """If trace file path is broken, recording still works (in-memory)."""
        loop = _make_loop(tmp_path)
        loop._trace_path = Path("/nonexistent/dir/trace.jsonl")

        # Should not raise
        loop._record_route_trace("route", role="code")
        assert len(loop._routing_trace) == 1


# ---------------------------------------------------------------------------
# Dispatch integration records metrics
# ---------------------------------------------------------------------------


class TestDispatchRecordsMetrics:
    async def test_dispatch_records_delegate_and_complete(self, tmp_path: Path) -> None:
        """_dispatch_delegation records delegate + delegate_complete events."""
        loop = _make_loop(tmp_path, FakeProvider(["delegation result"]))
        assert loop._routing_metrics is not None

        await loop._dispatch_delegation("code", "write some code", None)

        assert loop._routing_metrics.get(ROUTING_DELEGATIONS) == 1
        # Latency sum may be 0 for very fast fake providers; just check
        # that the delegate_complete trace was recorded
        trace = loop.get_routing_trace()
        complete_events = [t for t in trace if t["event"] == "delegate_complete"]
        assert len(complete_events) == 1
        assert complete_events[0]["success"] is True

    async def test_cycle_block_records_metric(self, tmp_path: Path) -> None:
        """Cycle detection records routing_cycles_blocked."""
        from nanobot.agent.loop import _delegation_ancestry

        loop = _make_loop(tmp_path)
        assert loop._routing_metrics is not None

        token = _delegation_ancestry.set(("code",))
        try:
            with pytest.raises(_CycleError):
                await loop._dispatch_delegation("code", "cause cycle", None)
        finally:
            _delegation_ancestry.reset(token)

        assert loop._routing_metrics.get(ROUTING_CYCLES_BLOCKED) == 1


# ---------------------------------------------------------------------------
# MetricsCollector flush
# ---------------------------------------------------------------------------


class TestMetricsFlush:
    async def test_flush_persists_to_json(self, tmp_path: Path) -> None:
        path = tmp_path / "metrics.json"
        mc = MetricsCollector(path)
        mc.record(ROUTING_CLASSIFICATIONS, 5)
        mc.record(ROUTING_DELEGATIONS, 2)
        await mc.flush()

        data = json.loads(path.read_text(encoding="utf-8"))
        assert data[ROUTING_CLASSIFICATIONS] == 5
        assert data[ROUTING_DELEGATIONS] == 2

    async def test_snapshot_returns_all_counters(self, tmp_path: Path) -> None:
        path = tmp_path / "metrics.json"
        mc = MetricsCollector(path)
        mc.record("a", 1)
        mc.record("b", 3)
        snap = mc.snapshot()
        assert snap["a"] == 1
        assert snap["b"] == 3
