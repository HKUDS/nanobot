"""Loop detection hook — catches agents repeating identical tool-call patterns.

Tracks consecutive identical tool-call *signatures* across iterations.  At
``warn_at`` repeats the agent receives an in-context nudge; at ``halt_at``
repeats a stronger message is injected that steers the model toward a final
text response (ending the tool-call loop naturally).

No modifications to the runner are required — the hook works entirely
through the existing ``before_execute_tools`` and ``after_iteration`` hook
points.

Usage::

    from nanobot.agent.loop_detect import LoopDetectHook
    hook = LoopDetectHook(warn_at=3, halt_at=5)
    # Pass to AgentRunner or add to a CompositeHook.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from loguru import logger

from nanobot.agent.hook import AgentHook, AgentHookContext
from nanobot.providers.base import ToolCallRequest


# ── Signature helpers ─────────────────────────────────────────────────

def _canonical_signature(calls: list[ToolCallRequest]) -> str:
    """Deterministic fingerprint for a batch of tool calls.

    Sorts by tool name, strips volatile metadata, and hashes the
    normalised JSON.
    """
    if not calls:
        return "__empty__"

    buckets: dict[str, list[dict[str, Any]]] = {}
    for tc in calls:
        clean_args = {
            k: v for k, v in tc.arguments.items()
            if k not in ("tool_call_id",)
        }
        buckets.setdefault(tc.name, []).append(clean_args)

    payload: list[tuple[str, list[dict[str, Any]]]] = sorted(buckets.items())
    for idx, (name, args_list) in enumerate(payload):
        payload[idx] = (name, sorted(args_list, key=lambda a: json.dumps(a, sort_keys=True)))

    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


# ── Messages ──────────────────────────────────────────────────────────

_WARN_MESSAGE = (
    "⚠️ Loop detected — you have made the same set of tool calls "
    "{count} times in a row with no progress. "
    "Stop repeating these calls and try a fundamentally different approach."
)

_HALT_MESSAGE = (
    "🛑 Loop halt — the same tool calls have been repeated {count} times. "
    "The current strategy is NOT working. "
    "Do NOT call any more tools. Respond directly to the user with what "
    "you have so far, or ask them for guidance."
)


# ── Hook ──────────────────────────────────────────────────────────────

class LoopDetectHook(AgentHook):
    """Inject recovery guidance when the agent repeats identical tool calls.

    Parameters
    ----------
    warn_at:
        Consecutive identical signatures before a warning is injected.
        Default ``3``.
    halt_at:
        Consecutive identical signatures before a halt message is injected
        that explicitly tells the model to stop calling tools.
        Default ``5``.  Must be greater than *warn_at*.
    """

    __slots__ = ("_warn_at", "_halt_at", "_last_sig", "_count", "_halted")

    def __init__(self, *, warn_at: int = 3, halt_at: int = 5) -> None:
        super().__init__()
        if halt_at <= warn_at:
            raise ValueError(f"halt_at ({halt_at}) must be > warn_at ({warn_at})")
        self._warn_at = warn_at
        self._halt_at = halt_at
        self._last_sig: str | None = None
        self._count: int = 0
        self._halted: bool = False

    # ── Hook points ───────────────────────────────────────────────

    async def before_execute_tools(self, context: AgentHookContext) -> None:
        sig = _canonical_signature(context.tool_calls)
        if sig == self._last_sig:
            self._count += 1
        else:
            self._last_sig = sig
            self._count = 1

        if self._count == self._warn_at:
            logger.warning(
                "LoopDetect: consecutive repeats={} for session",
                self._count,
            )
            self._inject(context, _WARN_MESSAGE.format(count=self._count))

        elif self._count >= self._halt_at and not self._halted:
            logger.warning(
                "LoopDetect: consecutive repeats={}, injecting HALT",
                self._count,
            )
            self._inject(context, _HALT_MESSAGE.format(count=self._count))
            self._halted = True

    async def after_iteration(self, context: AgentHookContext) -> None:
        # Reset on successful progress (iteration ended with tool results
        # being appended, meaning the next iteration will proceed normally).
        # We only keep the halt flag set once triggered.
        if self._halted:
            return

    # ── Internal ──────────────────────────────────────────────────

    @staticmethod
    def _inject(context: AgentHookContext, text: str) -> None:
        """Append a user-level nudge to the message list."""
        context.messages.append({
            "role": "user",
            "content": f"[Loop Detection] {text}",
        })
