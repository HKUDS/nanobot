"""Failure classification and tool-call loop detection for the agent loop.

``FailureClass`` categorises every tool error so the replanning prompt can give
the LLM targeted guidance (retry, fix params, or give up).  ``ToolCallTracker``
uses this classification to break infinite identical-failure loops before they
exhaust the token budget.  ``_build_failure_prompt`` renders the tracker state
into a structured REFLECT-phase prompt.
"""

from __future__ import annotations

import hashlib
import json
from enum import Enum
from typing import Any, ClassVar

from nanobot.tools.base import ToolResult


class FailureClass(str, Enum):
    """Classification of a tool call failure for structured replanning.

    Used by ``ToolCallTracker`` to decide whether a failed tool should be
    removed immediately (permanent) or kept with reduced priority (transient).
    """

    PERMANENT_CONFIG = "permanent_config"  # missing API key, binary not installed
    PERMANENT_AUTH = "permanent_auth"  # invalid credentials
    TRANSIENT_TIMEOUT = "transient_timeout"  # network timeout, rate limit
    TRANSIENT_ERROR = "transient_error"  # server 500, temporary failure
    LOGICAL_ERROR = "logical_error"  # wrong arguments, bad input
    UNKNOWN = "unknown"

    @property
    def is_permanent(self) -> bool:
        """True when the failure cannot be resolved by retrying or fixing arguments.

        Permanent failures (``PERMANENT_CONFIG``, ``PERMANENT_AUTH``) cause
        the tool to be immediately added to the disabled set for the current
        turn without waiting for the ``REMOVE_THRESHOLD`` count.
        """
        return self in (FailureClass.PERMANENT_CONFIG, FailureClass.PERMANENT_AUTH)

    @property
    def guidance(self) -> str:
        """Short remediation hint appended to each failure line in the REFLECT prompt.

        Returning a class-local string here eliminates the ``elif`` chain in
        ``_build_failure_prompt`` and keeps guidance co-located with the class.
        """
        if self.is_permanent:
            return "permanently disabled for this session"
        if self == FailureClass.TRANSIENT_TIMEOUT:
            return "consider retrying with a shorter operation or different parameters"
        if self == FailureClass.LOGICAL_ERROR:
            return "fix the parameters before retrying"
        return ""


class ToolCallTracker:
    """Detect and break infinite tool call loops — both failures and repeated successes.

    Tracks ``(tool_name, args_hash)`` → count for failures and successes separately.

    **Failure escalation:**
      - 2nd identical failure  → inject "stop retrying" prompt
      - 3rd identical failure  → add to ``disabled_tools`` for the rest of the turn
      - >8 total failures      → force the agent to produce a final answer

    **Repeated-success detection:**
      - 3rd identical success  → inject "stop repeating" prompt + disable the tool

    This prevents loops where a side-effect tool (e.g. ``message``) succeeds
    with identical arguments every iteration without advancing the agent's goal.

    Permanent failures (``FailureClass.is_permanent``) are added to
    ``disabled_tools`` immediately on the first occurrence via
    ``_permanent_failures``, regardless of count.

    ``record_failure()`` returns ``(count, FailureClass)`` — callers must
    unpack both values.  ``record_success()`` returns the repeated-success
    count for that signature.  The tool registry is **never mutated**;
    suppression is enforced by filtering ``tools_def`` at definition-generation
    time.

    **Scope**: A ``ToolCallTracker`` instance is scoped to a single agent
    turn, not an entire session.  ``AgentLoop`` creates a fresh tracker at
    the start of each ``_run_agent_loop`` invocation, so ``GLOBAL_BUDGET``
    limits failures within one turn.  The tracker is never carried across
    turns.
    """

    WARN_THRESHOLD: ClassVar[int] = 2
    REMOVE_THRESHOLD: ClassVar[int] = 3
    REPEAT_SUCCESS_THRESHOLD: ClassVar[int] = 3
    # Maximum total failures allowed per agent turn.  When
    # ``total_failures >= GLOBAL_BUDGET`` the agent is forced to produce a
    # final answer.  This budget is per-turn (not per-session) because the
    # tracker is instantiated fresh at the start of each turn.
    GLOBAL_BUDGET: ClassVar[int] = 8

    def __init__(self) -> None:
        self._counts: dict[str, int] = {}  # key → failure count
        self._success_counts: dict[str, int] = {}  # key → repeated-success count
        self._total_failures: int = 0
        self._permanent_failures: set[str] = set()  # tool names permanently removed

    @staticmethod
    def _key(name: str, args: dict[str, Any]) -> str:
        # blake2b is significantly faster than sha256 for short inputs; 8-byte digest
        # gives 64-bit collision resistance which is ample for a per-turn dedup key.
        h = hashlib.blake2b(
            json.dumps(args, sort_keys=True, default=str).encode(), digest_size=8
        ).hexdigest()
        return f"{name}:{h}"

    @staticmethod
    def classify_failure(name: str, result: ToolResult) -> FailureClass:
        """Classify a tool failure to guide replanning decisions.

        Classification priority (first match wins):

        1. ``result.metadata["error_type"]`` — explicit structured signal:
           - ``"validation"`` → ``LOGICAL_ERROR``
           - ``"not_found"`` / ``"permission"`` / ``"unknown_role"`` → ``PERMANENT_CONFIG``
           - ``"timeout"`` → ``TRANSIENT_TIMEOUT``
        2. Keyword scan of ``result.error`` / ``result.output`` message:
           - API-key / not-configured / not-installed → ``PERMANENT_CONFIG``
           - Binary/command/module not found → ``PERMANENT_CONFIG``
           - Unauthorized / invalid-key / forbidden → ``PERMANENT_AUTH``
           - Timeout / rate-limit / 429 → ``TRANSIENT_TIMEOUT``
           - 500 / server-error / 503 → ``TRANSIENT_ERROR``
        3. Fall-through → ``UNKNOWN``

        Note: "file not found" (OS ENOENT) is intentionally ``UNKNOWN``, not
        ``PERMANENT_CONFIG`` — the LLM should retry with the correct path.
        """
        error_type = result.metadata.get("error_type", "unknown") if result.metadata else "unknown"
        error_msg = (result.error or result.output or "").lower()

        if error_type == "validation":
            return FailureClass.LOGICAL_ERROR
        if error_type in ("not_found", "permission", "unknown_role"):
            return FailureClass.PERMANENT_CONFIG
        if error_type == "timeout":
            return FailureClass.TRANSIENT_TIMEOUT

        # Keyword-based fallback when error_type is generic.
        # "no such" / "not found" only indicate a permanent config failure when the
        # missing thing is a binary/command/module — NOT when a file path is wrong
        # (which is a logical error the LLM should correct).
        if any(k in error_msg for k in ("api key", "not configured", "not installed")):
            return FailureClass.PERMANENT_CONFIG
        _cmd_ctx = ("command", "binary", "executable", "module", "program")
        if ("no such" in error_msg or "not found" in error_msg) and any(
            c in error_msg for c in _cmd_ctx
        ):
            return FailureClass.PERMANENT_CONFIG
        if any(
            k in error_msg for k in ("invalid key", "unauthorized", "authentication", "forbidden")
        ):
            return FailureClass.PERMANENT_AUTH
        if any(k in error_msg for k in ("timeout", "timed out", "rate limit", "429", "too many")):
            return FailureClass.TRANSIENT_TIMEOUT
        if any(k in error_msg for k in ("500", "server error", "service unavailable", "503")):
            return FailureClass.TRANSIENT_ERROR
        return FailureClass.UNKNOWN

    def record_failure(
        self, name: str, args: dict[str, Any], result: ToolResult | None = None
    ) -> tuple[int, FailureClass]:
        """Record a tool failure; returns (count, failure_class) for this signature."""
        k = self._key(name, args)
        self._counts[k] = self._counts.get(k, 0) + 1
        self._success_counts.pop(k, None)  # reset success streak on failure
        self._total_failures += 1
        fc = self.classify_failure(name, result) if result is not None else FailureClass.UNKNOWN
        if fc.is_permanent:
            self._permanent_failures.add(name)
        return self._counts[k], fc

    def record_success(self, name: str, args: dict[str, Any]) -> int:
        """Record a successful tool call and return the repeated-success count.

        Clears any failure count for this signature (a success after failures
        means the issue was resolved).  Increments the repeated-success count
        so callers can detect loops where a tool succeeds with identical
        arguments without advancing the agent's goal.
        """
        k = self._key(name, args)
        self._counts.pop(k, None)
        self._success_counts[k] = self._success_counts.get(k, 0) + 1
        return self._success_counts[k]

    @property
    def permanent_failures(self) -> frozenset[str]:
        """Tool names that failed permanently this turn (removed from candidate set)."""
        return frozenset(self._permanent_failures)

    @property
    def total_failures(self) -> int:
        return self._total_failures

    @property
    def budget_exhausted(self) -> bool:
        return self._total_failures >= self.GLOBAL_BUDGET


class _CycleError(Exception):
    """Raised when a delegation cycle or depth/budget limit is reached."""


def _build_failure_prompt(
    failed_tools: list[tuple[str, FailureClass]],
    permanent_failures: frozenset[str],
    available_tools: list[str],
) -> str:
    """Build a structured REFLECT-phase prompt from live ``ToolCallTracker`` state.

    Generates classification-aware guidance for each failed tool:
    - Permanent failures are flagged as disabled for this session.
    - Timeouts suggest retrying with a shorter operation or different parameters.
    - Logical errors instruct the model to fix arguments before retrying.

    ``permanent_failures`` should be pre-filtered at the call site to avoid
    re-allocating the filtered list inside this function on every failure.
    ``available_tools`` is the list of non-permanent tools still usable.
    """
    lines: list[str] = ["One or more tool calls failed:"]
    for name, fc in failed_tools:
        hint = fc.guidance
        suffix = f" — {hint}" if hint else ""
        lines.append(f"- `{name}`: {fc.value}{suffix}")

    if permanent_failures:
        lines.append(
            f"\nPermanently removed (do NOT call these again): "
            f"{', '.join(sorted(permanent_failures))}"
        )

    if available_tools:
        lines.append(f"\nAvailable alternatives: {', '.join(available_tools)}")

    lines.append(
        "\nAnalyze what went wrong, choose an alternative tool or approach from the "
        "available tools above, and proceed. If no alternative exists, explain why "
        "the task cannot be completed."
    )
    return "\n".join(lines)


__all__ = [
    "FailureClass",
    "ToolCallTracker",
    "_CycleError",
    "_build_failure_prompt",
]
