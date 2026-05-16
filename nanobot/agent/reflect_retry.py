"""Reflect-and-retry hook for tool errors.

Enriches tool error results with attempt history so the model can
self-correct instead of blindly retrying the same call.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from nanobot.agent.hook import AgentHook, ToolCallContext


@dataclass
class ToolCallErrorContext(ToolCallContext):
    """Extended context for error-bearing tool calls."""

    error: str = ""
    attempt: int = 1
    history: list[str] = field(default_factory=list)


class ReflectRetryHook(AgentHook):
    """Enriches tool error results with attempt count and history.

    When a tool returns an error string (starts with ``"Error"``), this
    hook appends structured retry guidance so the model can reason about
    what went wrong instead of repeating the same mistake.

    Design choices:
    * No re-execution — the hook is a pure transform; the model decides
      whether to retry.
    * Deduplication key = ``tool_name + sha256(args)`` so the same call
      with identical arguments counts as the same mistake.
    * On max-retries exhaustion the hint changes to advise a different
      approach entirely.

    Parameters
    ----------
    max_retries:
        Maximum retry attempts **after** the initial failure.  The model
        gets ``max_retries + 1`` total attempts before the hint pivots.
    """

    def __init__(self, max_retries: int = 2) -> None:
        super().__init__(reraise=False)
        self.max_retries = max_retries
        self._attempt_counts: dict[str, int] = {}
        self._error_history: dict[str, list[str]] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def after_tool_call(
        self, tc_ctx: ToolCallContext, result: object
    ) -> object:
        if not self._is_error(result):
            return result

        error_str = str(result)
        key = self._make_key(tc_ctx)

        attempt = self._attempt_counts.get(key, 0) + 1
        self._attempt_counts[key] = attempt
        self._error_history.setdefault(key, []).append(error_str)

        if attempt <= self.max_retries:
            return self._enrich_retry(error_str, attempt, self._error_history[key])
        return self._enrich_exhausted(error_str, attempt, self._error_history[key])

    def reset(self) -> None:
        """Clear all tracking state (useful between agent runs)."""
        self._attempt_counts.clear()
        self._error_history.clear()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _is_error(result: object) -> bool:
        return isinstance(result, str) and result.startswith("Error")

    @staticmethod
    def _make_key(tc_ctx: ToolCallContext) -> str:
        args_blob = hashlib.sha256(
            str(sorted(tc_ctx.arguments.items())).encode()
        ).hexdigest()[:16]
        return f"{tc_ctx.tool_name}:{args_blob}"

    @staticmethod
    def _enrich_retry(
        error: str, attempt: int, history: list[str]
    ) -> str:
        lines = [error, ""]
        lines.append(
            f"[Tool call failed. This is attempt {attempt}/{attempt}. "
            f"Previous attempts:"
        )
        for i, h in enumerate(history, 1):
            lines.append(f"  Attempt {i}: {h}")
        lines.append("]")
        lines.append(
            "[Analyze the errors above and retry with corrected arguments, "
            "or try a different approach.]"
        )
        return "\n".join(lines)

    @staticmethod
    def _enrich_exhausted(
        error: str, attempt: int, history: list[str]
    ) -> str:
        lines = [error, ""]
        lines.append(
            f"[Max retries exceeded ({attempt} attempts). "
            f"Previous attempts:"
        )
        for i, h in enumerate(history, 1):
            lines.append(f"  Attempt {i}: {h}")
        lines.append("]")
        lines.append(
            "[Stop retrying this tool. Try a fundamentally different "
            "approach or ask the user for help.]"
        )
        return "\n".join(lines)
