"""Correlation ID infrastructure for request tracing.

Provides ``contextvars``-based correlation IDs that flow through the entire
request processing chain — agent loop, tool execution, memory operations,
and LLM calls — without changing function signatures.

Usage::

    from nanobot.observability.tracing import TraceContext, bind_trace

    # At request entry point:
    TraceContext.set(request_id="abc", session_id="s1", agent_id="code")

    # In any downstream code:
    ctx = TraceContext.get()
    logger.bind(**ctx).info("processing")

    # Or use the bind_trace helper directly:
    bind_trace().info("processing")

See ADR-005 for the observability strategy.
"""

from __future__ import annotations

import contextvars
import re
import uuid
from typing import Any

from loguru import logger

# ---------------------------------------------------------------------------
# Context variables — one per coroutine, inherited by child tasks
# ---------------------------------------------------------------------------

_request_id: contextvars.ContextVar[str] = contextvars.ContextVar("_request_id", default="")
_session_id: contextvars.ContextVar[str] = contextvars.ContextVar("_session_id", default="")
_agent_id: contextvars.ContextVar[str] = contextvars.ContextVar("_agent_id", default="")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


class TraceContext:
    """Context manager and utility for correlation IDs.

    All methods are static so callers don't need an instance::

        TraceContext.set(request_id="abc", session_id="s1")
        ctx = TraceContext.get()
    """

    @staticmethod
    def set(
        *,
        request_id: str | None = None,
        session_id: str | None = None,
        agent_id: str | None = None,
    ) -> None:
        """Set one or more correlation IDs for the current coroutine."""
        if request_id is not None:
            _request_id.set(request_id)
        if session_id is not None:
            _session_id.set(session_id)
        if agent_id is not None:
            _agent_id.set(agent_id)

    @staticmethod
    def get() -> dict[str, str]:
        """Return current correlation IDs as a dict (suitable for ``logger.bind``)."""
        return {
            "request_id": _request_id.get(),
            "session_id": _session_id.get(),
            "agent_id": _agent_id.get(),
        }

    @staticmethod
    def new_request(*, session_id: str = "", agent_id: str = "") -> str:
        """Generate a new request ID and set all correlation IDs.

        Returns the generated request_id.
        """
        rid = uuid.uuid4().hex[:12]
        _request_id.set(rid)
        _session_id.set(session_id)
        _agent_id.set(agent_id)
        return rid


# ---------------------------------------------------------------------------
# PII / credential sanitizer (LAN-131)
# ---------------------------------------------------------------------------

# Patterns ordered from most-specific to least-specific.
_PII_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # JWT (three base64url segments separated by dots — header.payload.sig)
    (re.compile(r"\beyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\b"), "[JWT]"),
    # Bearer / token in Authorization-style headers
    (re.compile(r"(?i)\bBearer\s+[A-Za-z0-9\-_.~+/]+=*"), "Bearer [REDACTED]"),
    # Key=value credential pairs (password, token, secret, api_key, …)
    (
        re.compile(
            r"(?i)(?:password|passwd|pwd|secret|token|api[_\-]?key|apikey|auth"
            r"|access[_\-]?key|private[_\-]?key)\s*[=:]\s*\S+"
        ),
        r"[CREDENTIAL REDACTED]",
    ),
    # Email addresses
    (
        re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"),
        "[EMAIL]",
    ),
    # Standalone "sk-…" style API key tokens (OpenAI, Anthropic, etc.)
    (re.compile(r"\bsk-[A-Za-z0-9\-_]{10,}\b"), "[API_KEY]"),
]


def sanitize_for_trace(text: str) -> str:
    """Redact common PII and credential patterns from a string.

    Intended for message excerpts sent to external tracing systems (Langfuse)
    so that user credentials and personal information are not inadvertently
    transmitted (LAN-131).

    The function is deliberately conservative — it redacts only well-known
    credential shapes rather than attempting heuristic PII detection, to avoid
    false-positive redactions that would make traces unintelligible.
    """
    for pattern, replacement in _PII_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def bind_trace() -> Any:
    """Return ``logger.bind(...)`` pre-filled with current correlation IDs.

    Usage::

        bind_trace().info("tool executed", tool="read_file", duration_ms=42)
    """
    return logger.bind(**TraceContext.get())
