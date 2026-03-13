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
from typing import TYPE_CHECKING, Any, AsyncIterator, Literal

from loguru import logger

if TYPE_CHECKING:
    from nanobot.config.schema import LangfuseConfig

# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_client: Any | None = None
_enabled: bool = False


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
        from langfuse import Langfuse

        _client = Langfuse(
            public_key=config.public_key,
            secret_key=config.secret_key,
            host=config.host,
        )
        _enabled = True
        logger.info("Langfuse observability initialized (host={})", config.host)

        # Langfuse v4 auto-instruments litellm via its OTEL TracerProvider —
        # do NOT also register litellm's own "otel" callback, as that creates
        # duplicate traces (litellm_request + raw_gen_ai_request).

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
        except Exception:  # crash-barrier: filter setup is optional
            pass

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
            logger.opt(exception=True).debug("Error shutting down Langfuse")
        _client = None
    _enabled = False


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
        logger.opt(exception=True).debug("Failed to update langfuse span")


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
        logger.opt(exception=True).debug("Failed to score langfuse trace")


def flush() -> None:
    """Flush pending langfuse events (call before process exit)."""
    if _client is not None:
        try:
            _client.flush()
        except Exception:  # crash-barrier: flush should not raise
            pass


# ---------------------------------------------------------------------------
# Request-level trace context manager
# ---------------------------------------------------------------------------


@contextlib.asynccontextmanager
async def trace_request(
    *,
    name: str = "request",
    input: Any | None = None,
    metadata: dict[str, Any] | None = None,
) -> AsyncIterator[Any]:
    """Create a top-level langfuse observation wrapping an entire request.

    All LLM calls made within the ``async with`` block are captured as child
    spans.  Falls through as a no-op when langfuse is disabled.

    Yields the observation object (or ``None`` when disabled).
    """
    if not _enabled or _client is None:
        yield None
        return

    try:
        async with _client.start_as_current_observation(
            name=name,
            as_type="span",
            input=input,
            metadata=metadata,
        ) as obs:
            yield obs
    except Exception:  # crash-barrier: tracing must never break the agent
        logger.opt(exception=True).debug("Langfuse trace_request failed")
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
        async with _client.start_as_current_observation(
            name=f"tool:{name}",
            as_type="tool",
            input=input,
            metadata=metadata,
        ) as obs:
            yield obs
    except Exception:  # crash-barrier: tracing must never break the agent
        logger.opt(exception=True).debug("Langfuse tool_span failed")
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
        async with _client.start_as_current_observation(
            name=name,
            as_type="span",
            input=input,
            metadata=metadata,
        ) as obs:
            yield obs
    except Exception:  # crash-barrier: tracing must never break the agent
        logger.opt(exception=True).debug("Langfuse span failed")
        yield None
