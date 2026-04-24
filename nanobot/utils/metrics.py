"""Per-turn latency metrics for voice/text pipelines (issue #3257).

Opt-in via ``gateway.metrics_enabled``. When disabled, ``flush()`` is a no-op
and the only per-turn cost is creating the ``TurnMetrics`` object and setting
a ContextVar — both negligible.

Design choices worth knowing for future readers:

* **TTFT is only observable when the provider streams deltas.** Non-streaming
  responses return the full completion atomically, so ``llm_ttft`` is reported
  as ``None`` for those turns. The field is always present in the payload so
  consumers (jq, Datadog, etc.) don't have to handle optionally-missing keys.
* **``stage_timer`` / ``tool_timer`` are no-ops without an active turn.** This
  lets the same instrumentation run from tests, cli paths, or any call-site
  that doesn't go through ``AgentLoop._dispatch`` without guarding every use.
* **The structured payload is emitted via ``logger.bind(metric="turn")``.**
  We don't install our own sink. Operators who want the metric stream in its
  own file/tool can add a filtered sink on ``record["extra"]["metric"]``.
"""

from __future__ import annotations

import json
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Iterator

from loguru import logger

_current: ContextVar["TurnMetrics | None"] = ContextVar("turn_metrics", default=None)


@dataclass
class ToolTiming:
    name: str
    duration_ms: int


@dataclass
class TurnMetrics:
    """Mutable per-turn metrics record. Not thread-safe (single asyncio task per turn)."""

    turn_id: str
    channel: str
    enabled: bool
    stages: dict[str, int] = field(default_factory=dict)
    tool_timings: list[ToolTiming] = field(default_factory=list)
    llm_ttft: int | None = None
    _llm_started_ns: int | None = None
    _activated_at_ns: int = field(default_factory=time.perf_counter_ns)

    @classmethod
    def current(cls) -> "TurnMetrics | None":
        return _current.get()

    def record_stage(self, name: str, duration_ms: int) -> None:
        self.stages[name] = duration_ms

    def record_tool(self, name: str, duration_ms: int) -> None:
        self.tool_timings.append(ToolTiming(name=name, duration_ms=duration_ms))

    def flush(self) -> None:
        if not self.enabled:
            return
        total_ms = (time.perf_counter_ns() - self._activated_at_ns) // 1_000_000
        payload: dict[str, Any] = {
            "turn_id": self.turn_id,
            "channel": self.channel,
            "timings_ms": {
                **self.stages,
                "llm_ttft": self.llm_ttft,
                "tool_calls": [
                    {"name": t.name, "duration_ms": t.duration_ms}
                    for t in self.tool_timings
                ],
                "total": total_ms,
            },
        }
        logger.bind(metric="turn").info(json.dumps(payload))


def activate(channel: str, enabled: bool) -> tuple[TurnMetrics, Any]:
    """Create a TurnMetrics and install it on the current context."""
    metrics = TurnMetrics(
        turn_id=uuid.uuid4().hex[:12],
        channel=channel,
        enabled=enabled,
    )
    token = _current.set(metrics)
    return metrics, token


def deactivate(token: Any) -> None:
    """Reset the current TurnMetrics to what it was before activate()."""
    _current.reset(token)


@contextmanager
def stage_timer(name: str) -> Iterator[None]:
    """Measure a stage and record its duration on the active turn metrics.

    No-op if no turn metrics is active (e.g. CLI-only paths).
    """
    m = TurnMetrics.current()
    if m is None:
        yield
        return
    start = time.perf_counter_ns()
    try:
        yield
    finally:
        m.record_stage(name, (time.perf_counter_ns() - start) // 1_000_000)


@contextmanager
def tool_timer(name: str) -> Iterator[None]:
    """Measure one tool invocation and append it to the active turn metrics."""
    m = TurnMetrics.current()
    if m is None:
        yield
        return
    start = time.perf_counter_ns()
    try:
        yield
    finally:
        m.record_tool(name, (time.perf_counter_ns() - start) // 1_000_000)


@contextmanager
def llm_timer() -> Iterator[None]:
    """Measure the whole LLM agent-loop and anchor the TTFT origin.

    ``mark_first_token()`` within this block records ``llm_ttft`` relative to
    the block start; outside of it, ``mark_first_token()`` is a no-op.
    """
    m = TurnMetrics.current()
    if m is None:
        yield
        return
    start = time.perf_counter_ns()
    m._llm_started_ns = start
    try:
        yield
    finally:
        m.record_stage("llm_total", (time.perf_counter_ns() - start) // 1_000_000)
        m._llm_started_ns = None


def mark_first_token() -> None:
    """Record ``llm_ttft`` the first time this is called inside ``llm_timer()``.

    Safe to call on every stream delta — subsequent calls are ignored.
    """
    m = TurnMetrics.current()
    if m is None or m.llm_ttft is not None or m._llm_started_ns is None:
        return
    m.llm_ttft = (time.perf_counter_ns() - m._llm_started_ns) // 1_000_000
