"""Langfuse observability integration.

Initializes the Langfuse client (OTEL-based) which auto-instruments litellm
LLM calls. Provides helpers for creating custom spans around tool execution,
routing, verification, and other agent operations.

Gate: all operations are no-ops when ``config.langfuse.enabled`` is False or
when keys are not configured.
"""

from __future__ import annotations

import contextlib
import functools
import time
from typing import TYPE_CHECKING, Any, AsyncIterator, Literal

from loguru import logger

if TYPE_CHECKING:
    from nanobot.config.schema import LangfuseConfig

# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_client: Any | None = None
_enabled: bool = False

# ---------------------------------------------------------------------------
# Health counters — lightweight, lock-free (single-threaded async)
# ---------------------------------------------------------------------------

_traces_created: int = 0
_traces_failed: int = 0
_last_trace_ts: float = 0.0
_HEALTH_LOG_INTERVAL: int = 50  # log a health summary every N traces


def init_langfuse(config: LangfuseConfig) -> None:
    """Initialize the global Langfuse client from config.

    Call once at startup (e.g. in CLI entrypoint or AgentLoop init).
    When enabled, this sets up an OTEL TracerProvider that auto-captures
    all litellm LLM calls — no per-call wiring needed.
    """
    global _client, _enabled  # noqa: PLW0603

    if not config.enabled:
        logger.info("Langfuse observability disabled by config")
        _enabled = False
        return

    if not config.public_key or not config.secret_key:
        logger.warning("Langfuse enabled but missing public_key/secret_key — running in no-op mode")
        _enabled = False
        return

    try:
        import atexit
        import os as _os

        from langfuse import Langfuse

        from nanobot import __version__

        # Set OTEL service name before Langfuse creates the TracerProvider
        _os.environ.setdefault("OTEL_SERVICE_NAME", "nanobot")

        _client = Langfuse(
            public_key=config.public_key,
            secret_key=config.secret_key,
            host=config.host,
            environment=config.environment,
            release=__version__,
            sample_rate=config.sample_rate,
            debug=config.debug,
        )
        _enabled = True

        # Safety net: ensure pending spans are flushed even on ungraceful exit.
        atexit.register(shutdown)

        # Verify credentials early so misconfiguration is visible at startup.
        try:
            if not _client.auth_check():
                logger.warning(
                    "Langfuse auth_check failed — traces may not be exported. "
                    "Check public_key / secret_key / host."
                )
        except Exception:  # crash-barrier: auth check is best-effort
            logger.opt(exception=True).warning("Langfuse auth_check raised")

        logger.info("Langfuse observability initialized (host={})", config.host)

        # Enable litellm OTEL callback so LLM calls emit spans through the
        # global TracerProvider that Langfuse v4 just configured.  The
        # LangfuseSpanProcessor recognises litellm's instrumentation scope
        # and maps the spans to GENERATION observations nested under the
        # active trace_request context.
        try:
            import litellm as _litellm

            if "otel" not in _litellm.success_callback:
                _litellm.success_callback.append("otel")
            if "otel" not in _litellm.failure_callback:
                _litellm.failure_callback.append("otel")
            # Force litellm to create its own litellm_request span rather than
            # writing gen_ai attributes onto the parent span — this prevents
            # the root "request" observation from being reclassified as a
            # GENERATION and avoids duplicated input/output/cost data.
            _os.environ.setdefault("USE_OTEL_LITELLM_REQUEST_SPAN", "true")
            # Suppress the raw_gen_ai_request sub-span that litellm creates
            # under each litellm_request.  Without this, every LLM call
            # produces two GENERATIONs with identical usage/cost, causing
            # Langfuse to double-count costs.
            #
            # We monkey-patch _maybe_log_raw_request instead of setting
            # turn_off_message_logging=True because that flag also suppresses
            # input/output attributes on the primary litellm_request span
            # (both are gated by the same check in set_attributes line ~175).
            from litellm.integrations.opentelemetry import OpenTelemetry as _OtelCls

            if hasattr(_OtelCls, "_maybe_log_raw_request"):
                _OtelCls._maybe_log_raw_request = lambda self, *a, **kw: None  # type: ignore[assignment]
            else:
                logger.warning(
                    "litellm OpenTelemetry._maybe_log_raw_request not found — "
                    "raw request spans may cause duplicate GENERATION costs"
                )
        except Exception:  # crash-barrier: litellm import/config is optional
            logger.opt(exception=True).warning("Could not enable litellm OTEL callback")

        # Suppress benign warnings from litellm/langfuse loggers.
        try:
            import logging

            # litellm warns "Proxy Server is not installed" on first LLM call
            # when the optional proxy package is absent.
            class _ProxyFilter(logging.Filter):
                def filter(self, record: logging.LogRecord) -> bool:
                    return "Proxy Server is not installed" not in record.getMessage()

            logging.getLogger("LiteLLM").addFilter(_ProxyFilter())

            # Langfuse may warn "No active span in current context" briefly
            # before the trace_request context manager is entered.
            class _SpanCtxFilter(logging.Filter):
                def filter(self, record: logging.LogRecord) -> bool:
                    return "No active span in current context" not in record.getMessage()

            logging.getLogger("langfuse").addFilter(_SpanCtxFilter())

            # OTEL SDK warns when litellm's async callback sets attributes on
            # a span that has already been ended.  These are harmless in
            # production (the attributes are simply ignored).
            class _EndedSpanFilter(logging.Filter):
                def filter(self, record: logging.LogRecord) -> bool:
                    msg = record.getMessage()
                    return "ended span" not in msg and "set_status on an ended span" not in msg

            logging.getLogger("opentelemetry.sdk.trace").addFilter(_EndedSpanFilter())
        except Exception as exc:  # crash-barrier: filter setup is optional
            logger.debug("OTel ended-span filter setup failed: {}", exc)

    except Exception:  # crash-barrier: langfuse init should never crash the agent
        logger.opt(exception=True).warning("Failed to initialize Langfuse — disabled")
        _enabled = False
        _client = None


def get_langfuse() -> Any | None:
    """Return the global Langfuse client, or None if disabled."""
    return _client


def is_enabled() -> bool:
    """Return True if langfuse is active and ready."""
    return _enabled


def shutdown() -> None:
    """Flush and shut down the Langfuse client."""
    global _client, _enabled  # noqa: PLW0603

    if _client is not None:
        try:
            _client.flush()
            _client.shutdown()
        except Exception:  # crash-barrier: shutdown should not raise
            logger.opt(exception=True).warning("Error shutting down Langfuse")
        _client = None
    _enabled = False


def reset_trace_context() -> None:
    """Detach any stale OTEL span context left from a previous iteration.

    Call this before ``trace_request()`` in long-running loops to prevent
    context leaks where a failed ``__exit__`` leaves an ended span as
    the "current" observation, causing all subsequent traces to become
    orphaned children that Langfuse silently discards.
    """
    if not _enabled or _client is None:
        return
    try:
        from opentelemetry import context as otel_context
        from opentelemetry import trace as otel_trace

        current_span = otel_trace.get_current_span()
        # INVALID_SPAN is the sentinel for "no active span"
        if current_span is not otel_trace.INVALID_SPAN and not current_span.is_recording():
            # There's a stale/ended span lingering in the context — detach it
            logger.warning(
                "Detaching stale OTEL span '{}' before new trace",
                current_span.name if hasattr(current_span, "name") else "unknown",
            )
            otel_context.attach(otel_context.Context())
    except Exception:  # crash-barrier: context reset is best-effort
        logger.opt(exception=True).warning("Failed to reset OTEL trace context")


def tracing_health() -> dict[str, Any]:
    """Return a snapshot of tracing health counters."""
    return {
        "enabled": _enabled,
        "client_alive": _client is not None,
        "traces_created": _traces_created,
        "traces_failed": _traces_failed,
        "last_trace_age_s": (
            round(time.monotonic() - _last_trace_ts, 1) if _last_trace_ts > 0 else None
        ),
    }


# ---------------------------------------------------------------------------
# Decorator re-export for convenience
# ---------------------------------------------------------------------------


_ObsType = Literal[
    "generation",
    "embedding",
    "span",
    "agent",
    "tool",
    "chain",
    "retriever",
    "evaluator",
    "guardrail",
]


def observe(
    *,
    name: str | None = None,
    as_type: _ObsType | None = None,
    capture_input: bool | None = None,
    capture_output: bool | None = None,
) -> Any:
    """Wrap langfuse ``@observe`` decorator, falling back to a no-op when disabled.

    Usage::

        @observe(name="classify", as_type="span")
        async def classify_intent(...):
            ...
    """
    if _enabled:
        from langfuse import observe as lf_observe

        return lf_observe(
            name=name,
            as_type=as_type,
            capture_input=capture_input,
            capture_output=capture_output,
        )

    # No-op passthrough when disabled
    def _noop(func: Any) -> Any:
        @functools.wraps(func)
        async def _async_wrapper(*args: Any, **kwargs: Any) -> Any:
            return await func(*args, **kwargs)

        @functools.wraps(func)
        def _sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            return func(*args, **kwargs)

        import asyncio

        return _async_wrapper if asyncio.iscoroutinefunction(func) else _sync_wrapper

    return _noop


# ---------------------------------------------------------------------------
# Span helpers for manual instrumentation
# ---------------------------------------------------------------------------


def update_current_span(
    *,
    input: Any | None = None,
    output: Any | None = None,
    metadata: dict[str, Any] | None = None,
    name: str | None = None,
    level: str | None = None,
) -> None:
    """Update the currently active langfuse span with additional data."""
    if not _enabled or _client is None:
        return
    try:
        kwargs: dict[str, Any] = {}
        if input is not None:
            kwargs["input"] = input
        if output is not None:
            kwargs["output"] = output
        if metadata is not None:
            kwargs["metadata"] = metadata
        if name is not None:
            kwargs["name"] = name
        if level is not None:
            kwargs["level"] = level
        if kwargs:
            _client.update_current_span(**kwargs)
    except Exception:  # crash-barrier: observability must never break agent flow
        logger.opt(exception=True).warning("Failed to update langfuse span")


def score_current_trace(
    *,
    name: str,
    value: float | str,
    comment: str | None = None,
) -> None:
    """Attach a score to the currently active langfuse trace."""
    if not _enabled or _client is None:
        return
    try:
        kwargs: dict[str, Any] = {"name": name, "value": value}
        if comment is not None:
            kwargs["comment"] = comment
        _client.score_current_trace(**kwargs)
    except Exception:  # crash-barrier: scoring must never break agent flow
        logger.opt(exception=True).warning("Failed to score langfuse trace")


def flush() -> None:
    """Flush pending langfuse events (call before process exit)."""
    if _client is not None:
        try:
            _client.flush()
        except Exception:  # crash-barrier: flush should not raise
            logger.opt(exception=True).warning("Langfuse flush failed")


# ---------------------------------------------------------------------------
# Request-level trace context manager
# ---------------------------------------------------------------------------


@contextlib.asynccontextmanager
async def trace_request(
    *,
    name: str = "request",
    input: Any | None = None,
    metadata: dict[str, Any] | None = None,
    session_id: str | None = None,
    user_id: str | None = None,
    tags: list[str] | None = None,
) -> AsyncIterator[Any]:
    """Create a top-level langfuse observation wrapping an entire request.

    All LLM calls made within the ``async with`` block are captured as child
    spans.  Falls through as a no-op when langfuse is disabled.

    Yields the observation object (or ``None`` when disabled).
    """
    if not _enabled or _client is None:
        yield None
        return

    global _traces_created, _traces_failed, _last_trace_ts  # noqa: PLW0603

    try:
        from langfuse import propagate_attributes as _propagate

        with _client.start_as_current_observation(
            name=name,
            as_type="span",
            input=input,
            metadata=metadata,
        ) as obs:
            # propagate_attributes must be called INSIDE start_as_current_observation
            # so the root span is already "current" — this sets userId/sessionId
            # on the root AND propagates them to all child spans.
            with (
                _propagate(
                    session_id=session_id,
                    user_id=user_id,
                    trace_name=name,
                    tags=tags or [],
                )
                if (session_id or user_id)
                else contextlib.nullcontext()
            ):
                yield obs
        _traces_created += 1
        _last_trace_ts = time.monotonic()
        if _traces_created % _HEALTH_LOG_INTERVAL == 0:
            logger.info(
                "Langfuse health: {} traces created, {} failed",
                _traces_created,
                _traces_failed,
            )
    except Exception:  # crash-barrier: tracing must never break the agent
        _traces_failed += 1
        logger.opt(exception=True).warning("Langfuse trace_request failed")
        yield None


@contextlib.asynccontextmanager
async def tool_span(
    *,
    name: str,
    input: Any | None = None,
    metadata: dict[str, Any] | None = None,
) -> AsyncIterator[Any]:
    """Create a langfuse span for a tool execution.

    Yields the observation object (or ``None`` when disabled).
    The caller should call ``obs.update(output=...)`` before exiting.
    """
    if not _enabled or _client is None:
        yield None
        return

    try:
        with _client.start_as_current_observation(
            name=f"tool:{name}",
            as_type="tool",
            input=input,
            metadata=metadata,
        ) as obs:
            yield obs
    except Exception:  # crash-barrier: tracing must never break the agent
        logger.opt(exception=True).warning("Langfuse tool_span failed")
        yield None


@contextlib.asynccontextmanager
async def span(
    *,
    name: str,
    input: Any | None = None,
    metadata: dict[str, Any] | None = None,
) -> AsyncIterator[Any]:
    """Create a generic langfuse child span.

    Use for wrapping arbitrary operations (classification, verification,
    compression, delegation) within a request trace.
    """
    if not _enabled or _client is None:
        yield None
        return

    try:
        with _client.start_as_current_observation(
            name=name,
            as_type="span",
            input=input,
            metadata=metadata,
        ) as obs:
            yield obs
    except Exception:  # crash-barrier: tracing must never break the agent
        logger.opt(exception=True).warning("Langfuse span failed")
        yield None
