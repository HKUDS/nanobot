"""Prometheus metrics for nanobot agent — re-exports from nanobot.metrics.

The canonical definitions live in ``nanobot.metrics`` so they can be shared
across all sub-packages (agent, providers, channels) without violating module
boundary rules.  This shim exists for convenience: agent-internal code can
import from ``nanobot.agent.metrics`` and get the same objects.
"""

from __future__ import annotations

from nanobot.metrics import (
    _METRICS_AVAILABLE,
    llm_calls_total,
    llm_latency_seconds,
    tool_calls_total,
    tool_latency_seconds,
)

__all__ = [
    "_METRICS_AVAILABLE",
    "llm_calls_total",
    "llm_latency_seconds",
    "tool_calls_total",
    "tool_latency_seconds",
]
