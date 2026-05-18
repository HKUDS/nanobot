"""Sustained goal tools on the main agent (Codex-style).

Follow the built-in **long-goal** skill for lifecycle rules and how to phrase
objectives (especially **idempotent**, compaction-safe goals). Load that skill
from the skills listing (path shown there) before composing ``long_task.goal`` text.

``long_task`` registers an objective on the session (JSON-serializable metadata).
Active objectives are mirrored each turn into the Runtime Context block (see
``nanobot.session.goal_state.goal_state_runtime_lines``) so compaction cannot hide them.
Work proceeds in ordinary agent turns (same runner, compaction as configured).
Call ``complete_goal`` when the sustained objective should stop being tracked:
finished successfully, or cancelled / superseded / redirected—in every case the recap should match reality.

There is **no** sub-agent orchestrator and **no** special WebSocket ``agent_ui`` stream.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from nanobot.agent.tools.base import Tool, tool_parameters
from nanobot.agent.tools.context import ContextAware, RequestContext
from nanobot.agent.tools.schema import StringSchema, tool_parameters_schema
from nanobot.bus.events import OutboundMessage
from nanobot.session.goal_state import (
    GOAL_STATE_KEY,
    discard_legacy_goal_state_key,
    goal_state_raw,
    goal_state_ws_blob,
    parse_goal_state,
)

if TYPE_CHECKING:
    from nanobot.session.manager import SessionManager


def _iso_now() -> str:
    return datetime.now().isoformat()


class _GoalToolsMixin(ContextAware):
    """Shared routing context + Session lookup."""

    def __init__(self, sessions: SessionManager, bus: Any | None = None) -> None:
        self._sessions = sessions
        self._bus = bus
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

    async def _publish_goal_state_ws(self, metadata: dict[str, Any]) -> None:
        """Fan-out authoritative goal snapshot for this WebSocket chat only."""
        bus = self._bus
        rc = self._request_ctx
        if bus is None or rc is None or rc.channel != "websocket":
            return
        cid = (rc.chat_id or "").strip()
        if not cid:
            return
        await bus.publish_outbound(
            OutboundMessage(
                channel="websocket",
                chat_id=cid,
                content="",
                metadata={
                    "_goal_state_sync": True,
                    "goal_state": goal_state_ws_blob(metadata),
                },
            ),
        )


@tool_parameters(
    tool_parameters_schema(
        goal=StringSchema(
            "Sustained objective for this chat thread. First read the built-in **long-goal** skill, "
            "especially its Start fast section, then call this promptly once the user's intent is clear. "
            "The goal must still be idempotent, self-contained, bounded, and explicit about done-ness; "
            "do not delay this tool call to over-plan, research, or decide execution details.",
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

    def __init__(self, sessions: Any, bus: Any | None = None) -> None:
        _GoalToolsMixin.__init__(self, sessions, bus)

    @classmethod
    def create(cls, ctx: Any) -> Tool:
        sess = getattr(ctx, "sessions", None)
        assert sess is not None  # guarded by enabled()
        return cls(sessions=sess, bus=getattr(ctx, "bus", None))

    @classmethod
    def enabled(cls, ctx: Any) -> bool:
        return getattr(ctx, "sessions", None) is not None

    @property
    def name(self) -> str:
        return "long_task"

    @property
    def description(self) -> str:
        return (
            "Mark this thread as a sustained long-running task. "
            "First read the built-in **long-goal** skill, especially its Start fast section; then call this "
            "as soon as the user's intent is clear. Write a good idempotent goal, but do not delay the tool "
            "call with long planning, research, or execution-detail thinking. "
            "The active goal is mirrored in Runtime Context each turn. Use normal tools until done, then call "
            "complete_goal when the objective is satisfied, cancelled, or replaced. "
            "If a goal is already active, finish it or call complete_goal before registering another."
        )

    async def execute(self, goal: str, ui_summary: str | None = None, **kwargs: Any) -> str:
        sess = self._session()
        if sess is None:
            return (
                "Error: long_task requires an active chat session (missing routing context)."
            )
        prior = parse_goal_state(goal_state_raw(sess.metadata))
        if isinstance(prior, dict) and prior.get("status") == "active":
            return (
                "Error: a sustained goal is already active. "
                "Use complete_goal when finished, or ask the user before replacing it."
            )

        summary = (ui_summary or "").strip()[:120]
        blob = {
            "status": "active",
            "objective": goal.strip(),
            "ui_summary": summary,
            "started_at": _iso_now(),
        }
        sess.metadata[GOAL_STATE_KEY] = blob
        discard_legacy_goal_state_key(sess.metadata)
        self._sessions.save(sess)
        await self._publish_goal_state_ws(sess.metadata)
        extra = f"\nSummary line: {summary}" if summary else ""
        return (
            "Goal recorded. Keep working toward the objective using ordinary tools. "
            "When fully done (verified against what was asked), call complete_goal with a "
            f"short recap.{extra}"
        )


@tool_parameters(
    tool_parameters_schema(
        recap=StringSchema(
            "Brief recap for the user (plain text). When the goal succeeded, confirm outcomes; "
            "if the user cancelled, pivoted, or replaced the objective, say so honestly.",
            max_length=8000,
            nullable=True,
        ),
        required=[],
    )
)
class CompleteGoalTool(Tool, _GoalToolsMixin):
    """Mark the active sustained goal finished after all required work is verified."""

    def __init__(self, sessions: Any, bus: Any | None = None) -> None:
        _GoalToolsMixin.__init__(self, sessions, bus)

    @classmethod
    def create(cls, ctx: Any) -> Tool:
        sess = getattr(ctx, "sessions", None)
        assert sess is not None
        return cls(sessions=sess, bus=getattr(ctx, "bus", None))

    @classmethod
    def enabled(cls, ctx: Any) -> bool:
        return getattr(ctx, "sessions", None) is not None

    @property
    def name(self) -> str:
        return "complete_goal"

    @property
    def description(self) -> str:
        return (
            "End bookkeeping for the active sustained goal. "
            "Use when the objective is fully achieved and verified—recap what was delivered. "
            "Also call when the user cancels, redirects, or replaces the goal: recap must reflect "
            "what actually happened (not necessarily success). "
            "If no goal is active, the tool reports that and leaves metadata unchanged."
        )

    async def execute(self, recap: str | None = None, **kwargs: Any) -> str:
        sess = self._session()
        if sess is None:
            return "Error: complete_goal requires an active chat session."
        prior = parse_goal_state(goal_state_raw(sess.metadata))
        if not isinstance(prior, dict) or prior.get("status") != "active":
            return "No active goal to complete."

        ended = _iso_now()
        sess.metadata[GOAL_STATE_KEY] = {
            **prior,
            "status": "completed",
            "completed_at": ended,
            "recap": (recap or "").strip(),
        }
        discard_legacy_goal_state_key(sess.metadata)
        self._sessions.save(sess)
        await self._publish_goal_state_ws(sess.metadata)
        tail = (recap or "").strip()
        if tail:
            return f"Goal marked complete ({ended}). Recap:\n{tail}"
        return f"Goal marked complete ({ended})."

