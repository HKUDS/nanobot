"""Sustained-goal tools with explicit user opt-in at the execution boundary."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import TYPE_CHECKING, Any

from nanobot.agent.goal_permission import (
    goal_mutation_allowed,
    revoke_goal_mutation_permission,
)
from nanobot.agent.tools.base import Tool, ToolResult, tool_parameters
from nanobot.agent.tools.context import RequestContext, current_request_context
from nanobot.agent.tools.schema import StringSchema, tool_parameters_schema
from nanobot.bus.runtime_events import GoalStateChanged, RuntimeEventBus, RuntimeEventContext
from nanobot.runtime_context import RuntimeContextBlock, wrap_runtime_context_lines
from nanobot.session.goal_state import (
    GOAL_STATE_KEY,
    MAX_GOAL_OBJECTIVE_CHARS,
    discard_legacy_goal_state_key,
    explicit_goal_requested,
    goal_state_raw,
    goal_state_runtime_lines,
    parse_goal_state,
    sustained_goal_active,
)
from nanobot.session.turn_continuation import reset_goal_continuation_rounds
from nanobot.utils.prompt_templates import render_template

if TYPE_CHECKING:
    from nanobot.session.manager import SessionManager


_GOAL_ACTIONS = ("complete", "cancel", "block", "replace")
_CREATE_UNAVAILABLE_ERROR = (
    "Error: create_goal is unavailable for this turn. Ask the user to submit the complete "
    "objective as `/goal <task>`."
)
_REPLACE_UNAVAILABLE_ERROR = (
    "Error: replacing the goal is unavailable for this turn. Ask the user to submit the "
    "replacement objective as `/goal <task>`."
)


def _iso_now() -> str:
    return datetime.now().isoformat()


class _GoalToolsMixin:
    """Shared routing context and session lookup."""

    def __init__(
        self,
        sessions: SessionManager,
        runtime_events: RuntimeEventBus | None = None,
    ) -> None:
        self._sessions = sessions
        self._runtime_events = runtime_events

    def _session(self):
        request_ctx = current_request_context()
        if request_ctx is None:
            return None
        key = request_ctx.session_key
        if not key:
            return None
        return self._sessions.get_or_create(key)

    def _goal_mutation_allowed(self) -> bool:
        return current_request_context() is not None and goal_mutation_allowed()

    def _save_goal_state(
        self,
        sess: Any,
        blob: dict[str, Any],
        *,
        reset_continuation: bool = False,
    ) -> None:
        previous_metadata = deepcopy(sess.metadata)
        sess.metadata[GOAL_STATE_KEY] = blob
        discard_legacy_goal_state_key(sess.metadata)
        if reset_continuation:
            reset_goal_continuation_rounds(sess.metadata)
        try:
            self._sessions.save(sess)
        except BaseException:
            sess.metadata.clear()
            sess.metadata.update(previous_metadata)
            raise

    async def _publish_goal_state_changed(self, metadata: dict[str, Any]) -> None:
        runtime_events = self._runtime_events
        rc = current_request_context()
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
            "The sustained objective for this session. It may consolidate a plan from earlier "
            "discussion, but must be self-contained, bounded, safe under repetition, and "
            "explicit about done-ness.",
            min_length=1,
            max_length=MAX_GOAL_OBJECTIVE_CHARS,
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
            "Create one sustained goal for the current session when Goal Runtime Guidance asks "
            "you to record it. Consolidate relevant prior discussion into a durable objective "
            "that is self-contained, bounded, safe under repetition, and explicit about "
            "completion criteria. Do not retry after a successful creation."
        )

    def runtime_context_provider(self):
        return self._provide_runtime_context

    async def _provide_runtime_context(
        self,
        request: RequestContext,
    ) -> RuntimeContextBlock | None:
        if not request.session_key:
            return None
        session = self._sessions.get_or_create(request.session_key)
        goal_start_requested = explicit_goal_requested(request.metadata)
        goal_active = sustained_goal_active(session.metadata)
        if not goal_start_requested and not goal_active:
            return None

        guidance = render_template(
            "agent/goal_runtime.md",
            strip=True,
            goal_start_requested=goal_start_requested,
            goal_active=goal_active,
        )
        state = wrap_runtime_context_lines(goal_state_runtime_lines(session.metadata))
        content = "\n\n".join(part for part in (guidance, state) if part)
        return RuntimeContextBlock(source="goal", content=content)

    async def execute(
        self,
        objective: str,
        ui_summary: str | None = None,
        **kwargs: Any,
    ) -> str:
        sess = self._session()
        if sess is None:
            return ToolResult.error(
                "Error: create_goal requires an active chat session (missing routing context)."
            )
        if not self._goal_mutation_allowed():
            return ToolResult.error(_CREATE_UNAVAILABLE_ERROR)
        prior = parse_goal_state(goal_state_raw(sess.metadata))
        if isinstance(prior, dict) and prior.get("status") == "active":
            return ToolResult.error(
                "Error: a sustained goal is already active. Use update_goal with "
                "action='replace' only if the user explicitly changes the objective."
            )

        objective_text = objective.strip()
        if not objective_text:
            return ToolResult.error("Error: objective must not be empty.")
        if len(objective_text) > MAX_GOAL_OBJECTIVE_CHARS:
            return ToolResult.error(
                f"Error: objective must not exceed {MAX_GOAL_OBJECTIVE_CHARS} characters."
            )
        summary = (ui_summary or "").strip()[:120]
        blob = {
            "status": "active",
            "objective": objective_text,
            "ui_summary": summary,
            "started_at": _iso_now(),
        }
        self._save_goal_state(sess, blob, reset_continuation=True)
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
            max_length=MAX_GOAL_OBJECTIVE_CHARS,
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
            "the requested objective changes."
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
            if not self._goal_mutation_allowed():
                return ToolResult.error(_REPLACE_UNAVAILABLE_ERROR)
            objective_text = (objective or "").strip()
            if not objective_text:
                return ToolResult.error(
                    "Error: update_goal action='replace' requires a replacement objective."
                )
            if len(objective_text) > MAX_GOAL_OBJECTIVE_CHARS:
                return ToolResult.error(
                    f"Error: objective must not exceed {MAX_GOAL_OBJECTIVE_CHARS} characters."
                )
            summary = (ui_summary or "").strip()[:120]
            blob = {
                "status": "active",
                "objective": objective_text,
                "ui_summary": summary,
                "started_at": _iso_now(),
                "replaced_at": _iso_now(),
                "previous_objective": str(prior.get("objective") or ""),
                "recap": (recap or "").strip(),
            }
            self._save_goal_state(sess, blob, reset_continuation=True)
            await self._publish_goal_state_changed(sess.metadata)
            extra = f"\nSummary line: {summary}" if summary else ""
            return "Goal replaced. Continue toward the new objective using ordinary tools." + extra

        ended = _iso_now()
        status = {
            "complete": "completed",
            "cancel": "cancelled",
            "block": "blocked",
        }[normalized]
        blob = {
            **prior,
            "status": status,
            "ended_at": ended,
            "recap": (recap or "").strip(),
        }
        if normalized == "complete":
            blob["completed_at"] = ended
        self._save_goal_state(sess, blob)
        revoke_goal_mutation_permission()
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
