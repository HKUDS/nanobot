"""Thread goal tools: sustained objectives on the main agent (Codex-style).

``long_task`` registers an objective on the session (JSON-serializable metadata).
Work proceeds in ordinary agent turns (same runner, compaction as configured).
When everything requested is truly done, call ``complete_goal`` so bookkeeping clears.

There is **no** sub-agent orchestrator and **no** special WebSocket ``agent_ui`` stream.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import TYPE_CHECKING, Any

from nanobot.agent.tools.base import Tool, tool_parameters
from nanobot.agent.tools.context import ContextAware, RequestContext
from nanobot.agent.tools.schema import StringSchema, tool_parameters_schema

if TYPE_CHECKING:
    from nanobot.session.manager import SessionManager


THREAD_GOAL_KEY = "thread_goal"


def _parse_goal(blob: Any) -> dict[str, Any] | None:
    if blob is None:
        return None
    if isinstance(blob, dict):
        return blob
    if isinstance(blob, str):
        try:
            parsed = json.loads(blob)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


def _iso_now() -> str:
    return datetime.now().isoformat()


class _GoalToolsMixin(ContextAware):
    """Shared routing context + Session lookup."""

    def __init__(self, sessions: SessionManager) -> None:
        self._sessions = sessions
        self._request_ctx: RequestContext | None = None

    def set_context(self, ctx: RequestContext) -> None:
        self._request_ctx = ctx

    def _session(self):
        if self._request_ctx is None:
            return None
        key = self._request_ctx.session_key
        if not key:
            return None
        return self._sessions.get_or_create(key)


@tool_parameters(
    tool_parameters_schema(
        goal=StringSchema(
            "Full objective for sustained execution on this chat thread. "
            "Be explicit about deliverables, formats, and constraints.",
            max_length=12_000,
        ),
        ui_summary=StringSchema(
            "Optional one-line label for session lists / logs (≤120 chars).",
            max_length=120,
            nullable=True,
        ),
        required=["goal"],
    )
)
class LongTaskTool(Tool, _GoalToolsMixin):
    """Begin or replace focus on a long-running objective stored on the session."""

    @classmethod
    def create(cls, ctx: Any) -> Tool:
        sess = getattr(ctx, "sessions", None)
        assert sess is not None  # guarded by enabled()
        return cls(sessions=sess)

    @classmethod
    def enabled(cls, ctx: Any) -> bool:
        return getattr(ctx, "sessions", None) is not None

    @property
    def name(self) -> str:
        return "long_task"

    @property
    def description(self) -> str:
        return (
            "Declare a sustained objective for this conversation. "
            "Execution stays on the main agent across turns (use normal tools). "
            "When—and only when—the objective is fully satisfied, call complete_goal. "
            "Do not call complete_goal for partial progress or because you are tired. "
            "If an objective is already active, finish or complete_goal before starting another."
        )

    async def execute(self, goal: str, ui_summary: str | None = None, **kwargs: Any) -> str:
        sess = self._session()
        if sess is None:
            return (
                "Error: long_task requires an active chat session (missing routing context)."
            )
        prior = _parse_goal(sess.metadata.get(THREAD_GOAL_KEY))
        if isinstance(prior, dict) and prior.get("status") == "active":
            return (
                "Error: a thread goal is already active. "
                "Use complete_goal when finished, or ask the user before replacing it."
            )

        summary = (ui_summary or "").strip()[:120]
        blob = {
            "status": "active",
            "objective": goal.strip(),
            "ui_summary": summary,
            "started_at": _iso_now(),
        }
        sess.metadata[THREAD_GOAL_KEY] = blob
        self._sessions.save(sess)
        extra = f"\nSummary line: {summary}" if summary else ""
        return (
            "Thread goal recorded. Keep working toward the objective using ordinary tools. "
            "When fully done (verified against what was asked), call complete_goal with a "
            f"short recap.{extra}"
        )


@tool_parameters(
    tool_parameters_schema(
        recap=StringSchema(
            "Brief recap for the user confirming what was achieved (plain text).",
            max_length=8000,
            nullable=True,
        ),
        required=[],
    )
)
class CompleteGoalTool(Tool, _GoalToolsMixin):
    """Mark the active thread goal finished after all required work is verified."""

    @classmethod
    def create(cls, ctx: Any) -> Tool:
        sess = getattr(ctx, "sessions", None)
        assert sess is not None
        return cls(sessions=sess)

    @classmethod
    def enabled(cls, ctx: Any) -> bool:
        return getattr(ctx, "sessions", None) is not None

    @property
    def name(self) -> str:
        return "complete_goal"

    @property
    def description(self) -> str:
        return (
            "Call only after the active thread goal has been fully achieved and verified. "
            "Summarize outcomes for the user. If no goal is active, the tool reports that "
            "and leaves metadata unchanged."
        )

    async def execute(self, recap: str | None = None, **kwargs: Any) -> str:
        sess = self._session()
        if sess is None:
            return "Error: complete_goal requires an active chat session."
        prior = _parse_goal(sess.metadata.get(THREAD_GOAL_KEY))
        if not isinstance(prior, dict) or prior.get("status") != "active":
            return "No active thread goal to complete."

        ended = _iso_now()
        sess.metadata[THREAD_GOAL_KEY] = {
            **prior,
            "status": "completed",
            "completed_at": ended,
            "recap": (recap or "").strip(),
        }
        self._sessions.save(sess)
        tail = (recap or "").strip()
        if tail:
            return f"Goal marked complete ({ended}). Recap:\n{tail}"
        return f"Goal marked complete ({ended})."

