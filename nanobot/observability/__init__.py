"""Observability layer — OpenTelemetry-based tracing for LLM calls and tools."""

from nanobot.observability.tracer import (
    create_tracer,
    detach_trace_context,
    set_llm_request_attributes,
    set_llm_response_attributes,
    set_trace_attributes,
    shutdown_tracer,
)

__all__ = [
    "create_tracer",
    "shutdown_tracer",
    "set_trace_attributes",
    "set_llm_request_attributes",
    "set_llm_response_attributes",
    "detach_trace_context",
]
