"""Explicit sustained-goal tools.

The tools in this module are runtime-gated by the agent loop.  They remain
registered in the process-wide registry, but are exposed to the model only for
``/goal`` creation turns or turns with an active persisted goal.
"""

from __future__ import annotations

from contextvars import ContextVar
from datetime import datetime
from typing import TYPE_CHECKING, Any

from nanobot.agent.tools.base import Tool, ToolResult, tool_parameters
from nanobot.agent.tools.context import ContextAware, RequestContext
from nanobot.agent.tools.schema import StringSchema, tool_parameters_schema
from nanobot.bus.runtime_events import GoalStateChanged, RuntimeEventBus, RuntimeEventContext
from nanobot.session.goal_state import (
    GOAL_STATE_KEY,
    discard_legacy_goal_state_key,
    explicit_goal_requested,
    goal_state_raw,
    parse_goal_state,
)

if TYPE_CHECKING:
    from nanobot.session.manager import SessionManager


_GOAL_ACTIONS = ("complete", "cancel", "block", "replace")


def _iso_now() -> str:
    return datetime.now().isoformat()


class _GoalToolsMixin(ContextAware):
    """Shared routing context and session lookup."""

    def __init__(
        self,
        sessions: SessionManager,
        runtime_events: RuntimeEventBus | None = None,
    ) -> None:
        self._sessions = sessions
        self._runtime_events = runtime_events
        self._request_ctx: ContextVar[RequestContext | None] = ContextVar(
            f"{self.__class__.__name__}_request_ctx",
            default=None,
        )

    def set_context(self, ctx: RequestContext) -> None:
        self._request_ctx.set(ctx)

    def _session(self):
        request_ctx = self._request_ctx.get()
        if request_ctx is None:
            return None
        key = request_ctx.session_key
        if not key:
            return None
        return self._sessions.get_or_create(key)

    def _message_metadata(self) -> dict[str, Any]:
        request_ctx = self._request_ctx.get()
        if request_ctx is None:
            return {}
        return dict(request_ctx.metadata or {})

    async def _publish_goal_state_changed(self, metadata: dict[str, Any]) -> None:
        runtime_events = self._runtime_events
        rc = self._request_ctx.get()
        if runtime_events is None or rc is None:
            return
        cid = (rc.chat_id or "").strip()
        if not cid:
            return
        await runtime_events.publish(
            GoalStateChanged(
                context=RuntimeEventContext(
                    channel=rc.channel,
                    chat_id=cid,
                    session_key=rc.session_key or f"{rc.channel}:{cid}",
                    metadata=dict(rc.metadata or {}),
                ),
                session_metadata=dict(metadata),
            )
        )


@tool_parameters(
    tool_parameters_schema(
        objective=StringSchema(
            "The sustained objective for this chat thread. Use only during an explicit /goal "
            "turn. Make it self-contained, bounded, safe under repetition, and explicit about "
            "done-ness; do not infer goals from ordinary user requests.",
            min_length=1,
            max_length=12_000,
        ),
        ui_summary=StringSchema(
            "Optional one-line display label for session lists and logs. It is not load-bearing.",
            max_length=120,
            nullable=True,
        ),
        required=["objective"],
    )
)
class CreateGoalTool(Tool, _GoalToolsMixin):
    """Create one explicit sustained objective for the current session."""

    def __init__(
        self,
        sessions: Any,
        runtime_events: RuntimeEventBus | None = None,
    ) -> None:
        _GoalToolsMixin.__init__(self, sessions, runtime_events)

    @classmethod
    def create(cls, ctx: Any) -> Tool:
        sess = getattr(ctx, "sessions", None)
        assert sess is not None
        return cls(
            sessions=sess,
            runtime_events=getattr(ctx, "runtime_events", None),
        )

    @classmethod
    def enabled(cls, ctx: Any) -> bool:
        return getattr(ctx, "sessions", None) is not None

    @property
    def name(self) -> str:
        return "create_goal"

    @property
    def description(self) -> str:
        return (
            "Create a sustained goal only when this turn was explicitly started with /goal. "
            "The objective should be durable across compaction and retries: self-contained, "
            "bounded, safe under repetition, and explicit about completion criteria. Do not "
            "infer or create goals from ordinary user requests."
        )

    async def execute(self, objective: str, ui_summary: str | None = None, **kwargs: Any) -> str:
        sess = self._session()
        if sess is None:
            return ToolResult.error(
                "Error: create_goal requires an active chat session (missing routing context)."
            )
        if not explicit_goal_requested(self._message_metadata()):
            return ToolResult.error(
                "Error: create_goal is only allowed during an explicit /goal turn."
            )
        prior = parse_goal_state(goal_state_raw(sess.metadata))
        if isinstance(prior, dict) and prior.get("status") == "active":
            return ToolResult.error(
                "Error: a sustained goal is already active. Use update_goal with "
                "action='replace' only if the user explicitly changes the objective."
            )

        objective_text = objective.strip()
        if not objective_text:
            return ToolResult.error("Error: objective must not be empty.")
        summary = (ui_summary or "").strip()[:120]
        blob = {
            "status": "active",
            "objective": objective_text,
            "ui_summary": summary,
            "started_at": _iso_now(),
        }
        sess.metadata[GOAL_STATE_KEY] = blob
        discard_legacy_goal_state_key(sess.metadata)
        self._sessions.save(sess)
        await self._publish_goal_state_changed(sess.metadata)
        extra = f"\nSummary line: {summary}" if summary else ""
        return (
            "Goal recorded. Keep working toward the objective using ordinary tools. "
            "When fully done and verified, call update_goal with action='complete'."
            f"{extra}"
        )


@tool_parameters(
    tool_parameters_schema(
        action=StringSchema(
            "How to update the active goal.",
            enum=_GOAL_ACTIONS,
        ),
        recap=StringSchema(
            "Brief honest recap for the user. Required in practice for complete, cancel, and block.",
            max_length=8000,
            nullable=True,
        ),
        objective=StringSchema(
            "Replacement objective. Required only when action is 'replace'; make it durable, "
            "self-contained, bounded, and explicit about done-ness.",
            max_length=12_000,
            nullable=True,
        ),
        ui_summary=StringSchema(
            "Optional one-line display label for a replacement goal.",
            max_length=120,
            nullable=True,
        ),
        required=["action"],
    )
)
class UpdateGoalTool(Tool, _GoalToolsMixin):
    """Complete, cancel, block, or replace the active sustained goal."""

    def __init__(
        self,
        sessions: Any,
        runtime_events: RuntimeEventBus | None = None,
    ) -> None:
        _GoalToolsMixin.__init__(self, sessions, runtime_events)

    @classmethod
    def create(cls, ctx: Any) -> Tool:
        sess = getattr(ctx, "sessions", None)
        assert sess is not None
        return cls(
            sessions=sess,
            runtime_events=getattr(ctx, "runtime_events", None),
        )

    @classmethod
    def enabled(cls, ctx: Any) -> bool:
        return getattr(ctx, "sessions", None) is not None

    @property
    def name(self) -> str:
        return "update_goal"

    @property
    def description(self) -> str:
        return (
            "Update the active sustained goal. Use action='complete' only after the objective "
            "is actually achieved and verified. Use action='cancel' when the user cancels, "
            "action='block' when progress is genuinely blocked, and action='replace' only when "
            "the user explicitly changes the active objective."
        )

    async def execute(
        self,
        action: str,
        recap: str | None = None,
        objective: str | None = None,
        ui_summary: str | None = None,
        **kwargs: Any,
    ) -> str:
        sess = self._session()
        if sess is None:
            return ToolResult.error("Error: update_goal requires an active chat session.")
        prior = parse_goal_state(goal_state_raw(sess.metadata))
        if not isinstance(prior, dict) or prior.get("status") != "active":
            return "No active goal to update."

        normalized = (action or "").strip().lower()
        if normalized not in _GOAL_ACTIONS:
            return ToolResult.error(
                "Error: action must be one of complete, cancel, block, or replace."
            )

        if normalized == "replace":
            objective_text = (objective or "").strip()
            if not objective_text:
                return ToolResult.error(
                    "Error: update_goal action='replace' requires a replacement objective."
                )
            summary = (ui_summary or "").strip()[:120]
            sess.metadata[GOAL_STATE_KEY] = {
                "status": "active",
                "objective": objective_text,
                "ui_summary": summary,
                "started_at": _iso_now(),
                "replaced_at": _iso_now(),
                "previous_objective": str(prior.get("objective") or ""),
                "recap": (recap or "").strip(),
            }
            discard_legacy_goal_state_key(sess.metadata)
            self._sessions.save(sess)
            await self._publish_goal_state_changed(sess.metadata)
            extra = f"\nSummary line: {summary}" if summary else ""
            return "Goal replaced. Continue toward the new objective using ordinary tools." + extra

        ended = _iso_now()
        status = {
            "complete": "completed",
            "cancel": "cancelled",
            "block": "blocked",
        }[normalized]
        sess.metadata[GOAL_STATE_KEY] = {
            **prior,
            "status": status,
            "ended_at": ended,
            "recap": (recap or "").strip(),
        }
        if normalized == "complete":
            sess.metadata[GOAL_STATE_KEY]["completed_at"] = ended
        discard_legacy_goal_state_key(sess.metadata)
        self._sessions.save(sess)
        await self._publish_goal_state_changed(sess.metadata)

        tail = (recap or "").strip()
        label = {
            "complete": "complete",
            "cancel": "cancelled",
            "block": "blocked",
        }[normalized]
        if tail:
            return f"Goal marked {label} ({ended}). Recap:\n{tail}"
        return f"Goal marked {label} ({ended})."
