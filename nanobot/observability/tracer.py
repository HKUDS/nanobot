"""OpenTelemetry-based tracer for nanobot observability.

Both Langfuse and LangSmith consume OTLP traces natively,
so a single TracerProvider with one exporter per backend is enough.
"""

from __future__ import annotations

import base64
import json
import os
from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:
    from opentelemetry.trace import Span, Tracer

# Maps tracer id → TracerProvider for providers we created (Langfuse-only path).
# LangSmith's global provider is NOT stored here; see shutdown_tracer().
_tracer_providers: dict[int, Any] = {}


def _noop_tracer() -> Tracer:
    """Return a no-op tracer when tracing is disabled."""
    from opentelemetry.trace import NoOpTracer
    return NoOpTracer()


def _build_langfuse_exporter(langfuse_config=None):
    """Build OTLP exporter for Langfuse.

    Reads credentials from config first, falling back to env vars.
    """
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

    public_key = (langfuse_config and langfuse_config.public_key) or os.environ.get("LANGFUSE_PUBLIC_KEY", "")
    secret_key = (langfuse_config and langfuse_config.secret_key) or os.environ.get("LANGFUSE_SECRET_KEY", "")
    base_url = (
        (langfuse_config and langfuse_config.base_url)
        or os.environ.get("LANGFUSE_BASE_URL", "")
        or "https://cloud.langfuse.com"
    )

    if not public_key or not secret_key:
        logger.warning("Langfuse public_key/secret_key not configured, skipping Langfuse exporter")
        return None

    auth = base64.b64encode(f"{public_key}:{secret_key}".encode()).decode()
    endpoint = f"{base_url.rstrip('/')}/api/public/otel/v1/traces"

    return OTLPSpanExporter(
        endpoint=endpoint,
        headers={
            "Authorization": f"Basic {auth}",
            "x-langfuse-ingestion-version": "4",
        },
    )


def _configure_langsmith(langsmith_config=None) -> bool:
    """Configure LangSmith via its native OTel integration.

    Reads credentials from config first, falling back to env vars.
    """
    try:
        from langsmith.integrations.otel import configure
    except ImportError:
        logger.warning(
            "langsmith is required for the LangSmith backend. "
            "Install it with: pip install langsmith"
        )
        return False

    api_key = (langsmith_config and langsmith_config.api_key) or os.environ.get("LANGSMITH_API_KEY", "")
    project = (langsmith_config and langsmith_config.project) or os.environ.get("LANGSMITH_PROJECT", "default")

    if not api_key:
        logger.warning("LangSmith api_key not configured, skipping LangSmith")
        return False

    configure(api_key=api_key, project_name=project)
    return True


def create_tracer(observability_config) -> Tracer:
    """Create an OTel tracer with exporters for the specified backends.

    Args:
        observability_config: ObservabilityConfig with backends list and
            per-backend credentials. Falls back to env vars when config
            fields are empty.

    Returns:
        An OTel Tracer. Returns a NoOpTracer if no backends are configured.
    """
    backends = observability_config.backends
    if not backends:
        return _noop_tracer()

    try:
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError:
        logger.warning(
            "opentelemetry-sdk not installed. Install with: "
            "pip install opentelemetry-sdk opentelemetry-exporter-otlp-proto-http"
        )
        return _noop_tracer()

    has_langsmith = False
    has_langfuse = False
    langfuse_exporter = None

    for name in backends:
        name_lower = name.lower()
        if name_lower == "langfuse":
            langfuse_exporter = _build_langfuse_exporter(observability_config.langfuse)
            if langfuse_exporter is not None:
                has_langfuse = True
                logger.info("Observability: langfuse exporter enabled")
        elif name_lower == "langsmith":
            if _configure_langsmith(observability_config.langsmith):
                has_langsmith = True
                logger.info("Observability: langsmith exporter enabled")
        else:
            logger.warning("Unknown observability backend: {}", name)

    if not has_langfuse and not has_langsmith:
        logger.info("No observability exporters configured, tracing disabled")
        return _noop_tracer()

    # BaggageSpanProcessor copies OTel Baggage entries (session_id, user_id)
    # to attributes on every child span automatically.
    try:
        from opentelemetry.processor.baggage import BaggageSpanProcessor, ALLOW_ALL_BAGGAGE_KEYS
        baggage_processor = BaggageSpanProcessor(ALLOW_ALL_BAGGAGE_KEYS)
    except ImportError:
        baggage_processor = None

    if has_langsmith:
        from opentelemetry import trace as otel_trace
        global_provider = otel_trace.get_tracer_provider()
        if hasattr(global_provider, "add_span_processor"):
            if langfuse_exporter:
                global_provider.add_span_processor(BatchSpanProcessor(langfuse_exporter))
            if baggage_processor:
                global_provider.add_span_processor(baggage_processor)
        tracer = otel_trace.get_tracer("nanobot", "1.0.0")
        # Not stored in _tracer_providers — LangSmith manages the global provider lifecycle.
        return tracer

    # Langfuse only: create our own provider with OTLP exporter
    resource = Resource.create({"service.name": "nanobot"})
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(BatchSpanProcessor(langfuse_exporter))
    if baggage_processor:
        provider.add_span_processor(baggage_processor)

    tracer = provider.get_tracer("nanobot", "1.0.0")
    _tracer_providers[id(tracer)] = provider
    return tracer


def shutdown_tracer(tracer: Tracer) -> None:
    """Flush and shut down the tracer provider."""
    provider = _tracer_providers.pop(id(tracer), None)
    if provider is not None and hasattr(provider, "shutdown"):
        try:
            provider.shutdown()
            logger.info("Observability: tracer shut down")
        except Exception as exc:
            logger.warning("Observability: tracer shutdown failed: {}", exc)


# ---------------------------------------------------------------------------
# Span helpers — thin wrappers for setting standard OTel + vendor attributes
# ---------------------------------------------------------------------------

def set_trace_attributes(
    span: Span,
    *,
    session_id: str | None = None,
    user_id: str | None = None,
    input: str | None = None,
):
    """Set trace-level attributes on the span and as OTel Baggage.

    BaggageSpanProcessor propagates baggage entries to all child spans.
    Returns a list of context tokens to detach when the trace ends.
    """
    from opentelemetry import baggage, context

    span.set_attribute("langsmith.span.kind", "chain")
    span.set_attribute("langfuse.observation.type", "span")

    tokens = []

    if session_id:
        span.set_attribute("langfuse.session.id", session_id)
        span.set_attribute("session.id", session_id)
        span.set_attribute("langsmith.metadata.session_id", session_id)
        ctx = baggage.set_baggage("langfuse.session.id", session_id)
        tokens.append(context.attach(ctx))
    if user_id:
        span.set_attribute("langfuse.user.id", user_id)
        span.set_attribute("langsmith.metadata.user_id", user_id)
        span.set_attribute("user.id", user_id)
        ctx = baggage.set_baggage("langfuse.user.id", user_id)
        tokens.append(context.attach(ctx))
    if input:
        span.set_attribute("langfuse.trace.input", input)
        span.set_attribute("langfuse.observation.input", input)
        span.set_attribute("input.value", input)

    return tokens


def detach_trace_context(tokens: list) -> None:
    """Detach baggage context tokens created by set_trace_attributes."""
    from opentelemetry import context
    for token in reversed(tokens):
        try:
            context.detach(token)
        except Exception:
            pass


def set_llm_request_attributes(
    span: Span,
    *,
    model: str,
    messages: list[dict[str, Any]],
    tools_count: int = 0,
) -> None:
    """Set LLM generation request attributes."""
    span.set_attribute("gen_ai.request.model", model)
    span.set_attribute("gen_ai.system", "nanobot")
    span.set_attribute("langsmith.span.kind", "llm")
    span.set_attribute("langfuse.observation.type", "generation")

    try:
        # Langfuse: reads input from this attribute (highest priority)
        raw = json.dumps(messages, ensure_ascii=False, default=str)
        span.set_attribute("langfuse.observation.input", raw[:32000])
        # LangSmith: reads input from gen_ai.prompt.N attributes
        for i, msg in enumerate(messages):
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if isinstance(content, list):
                content = json.dumps(content, ensure_ascii=False, default=str)
            span.set_attribute(f"gen_ai.prompt.{i}.content", str(content)[:32000])
            span.set_attribute(f"gen_ai.prompt.{i}.role", str(role))
    except Exception as exc:
        logger.debug("Failed to set LLM request attributes: {}", exc)


def set_llm_response_attributes(
    span: Span,
    *,
    model: str = "",
    content: str | None,
    usage: dict[str, int],
    finish_reason: str = "stop",
) -> None:
    """Set LLM generation response attributes."""
    if model:
        span.set_attribute("gen_ai.response.model", model)

    if content:
        try:
            # Langfuse: reads output from this attribute
            span.set_attribute(
                "langfuse.observation.output",
                json.dumps(content, ensure_ascii=False),
            )
            # LangSmith: reads output from gen_ai.completion attributes
            span.set_attribute("gen_ai.completion.0.content", str(content)[:32000])
            span.set_attribute("gen_ai.completion.0.role", "assistant")
            span.set_attribute("gen_ai.completion.0.finish_reason", finish_reason)
        except Exception as exc:
            logger.debug("Failed to set LLM response attributes: {}", exc)

    # Token usage — standard GenAI convention (both backends)
    input_tokens = usage.get("prompt_tokens", 0)
    output_tokens = usage.get("completion_tokens", 0)
    total_tokens = usage.get("total_tokens", input_tokens + output_tokens)

    span.set_attribute("gen_ai.usage.input_tokens", input_tokens)
    span.set_attribute("gen_ai.usage.output_tokens", output_tokens)
    span.set_attribute("gen_ai.usage.total_tokens", total_tokens)


def set_tool_attributes(
    span: Span,
    *,
    name: str,
    arguments: dict[str, Any] | None = None,
) -> None:
    """Set tool span attributes."""
    span.set_attribute("gen_ai.tool.name", name)
    span.set_attribute("langsmith.span.kind", "tool")
    span.set_attribute("langfuse.observation.type", "span")

    if arguments:
        try:
            args_json = json.dumps(arguments, ensure_ascii=False, default=str)
            # Langfuse: reads input from this attribute
            span.set_attribute("langfuse.observation.input", args_json)
            # LangSmith: reads input from input.value (OpenInference convention)
            span.set_attribute("input.value", args_json)
        except Exception as exc:
            logger.debug("Failed to set tool attributes: {}", exc)


def set_tool_result(span: Span, *, result: str) -> None:
    """Set tool output after execution."""
    try:
        truncated = result[:32000]
        # Langfuse: reads output from this attribute
        span.set_attribute("langfuse.observation.output", json.dumps(truncated))
        # LangSmith: reads output from output.value (OpenInference)
        span.set_attribute("output.value", truncated)
    except Exception as exc:
        logger.debug("Failed to set tool result: {}", exc)
