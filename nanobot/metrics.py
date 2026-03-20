"""Optional Prometheus metrics for nanobot. No-ops when prometheus_client is not installed.

This module lives at the top-level package so it can be imported by any sub-package
(agent, providers, channels, etc.) without violating module boundary rules.
"""

from __future__ import annotations

try:
    from prometheus_client import Counter, Histogram

    llm_calls_total = Counter(
        "nanobot_llm_calls_total", "Total LLM API calls", ["model", "role", "success"]
    )
    llm_latency_seconds = Histogram(
        "nanobot_llm_latency_seconds", "LLM call duration in seconds", ["model", "role"]
    )
    tool_calls_total = Counter(
        "nanobot_tool_calls_total", "Total tool calls", ["tool_name", "success"]
    )
    tool_latency_seconds = Histogram(
        "nanobot_tool_latency_seconds", "Tool call duration in seconds", ["tool_name"]
    )
    # Multi-agent delegation and routing metrics (LAN-129)
    delegation_total = Counter(
        "nanobot_delegation_total",
        "Total delegations dispatched",
        ["from_role", "to_role", "success"],
    )
    delegation_latency_seconds = Histogram(
        "nanobot_delegation_latency_seconds",
        "Delegation execution duration in seconds",
        ["to_role"],
    )
    classification_total = Counter(
        "nanobot_classification_total",
        "Total routing classifications performed",
        ["result_role"],
    )
    classification_fallback_total = Counter(
        "nanobot_classification_fallback_total",
        "Classifications that fell back to default_role (LLM error or low confidence)",
        ["reason"],  # "llm_error" | "low_confidence"
    )
    _METRICS_AVAILABLE = True
except ImportError:
    _METRICS_AVAILABLE = False

    # Define no-op stubs — silent, no exceptions, no logging.
    class _NoOp:  # type: ignore[no-redef]
        def labels(self, **_kw: object) -> _NoOp:
            return self

        def inc(self, *a: object, **kw: object) -> None:
            pass

        def observe(self, *a: object, **kw: object) -> None:
            pass

    llm_calls_total = _NoOp()  # type: ignore[assignment]
    llm_latency_seconds = _NoOp()  # type: ignore[assignment]
    tool_calls_total = _NoOp()  # type: ignore[assignment]
    tool_latency_seconds = _NoOp()  # type: ignore[assignment]
    delegation_total = _NoOp()  # type: ignore[assignment]
    delegation_latency_seconds = _NoOp()  # type: ignore[assignment]
    classification_total = _NoOp()  # type: ignore[assignment]
    classification_fallback_total = _NoOp()  # type: ignore[assignment]

__all__ = [
    "_METRICS_AVAILABLE",
    "llm_calls_total",
    "llm_latency_seconds",
    "tool_calls_total",
    "tool_latency_seconds",
    "delegation_total",
    "delegation_latency_seconds",
    "classification_total",
    "classification_fallback_total",
]
