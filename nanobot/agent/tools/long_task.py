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

from nanobot.agent.tools.base import Tool, ToolResult, tool_parameters
from nanobot.agent.tools.context import current_request_context
from nanobot.agent.tools.schema import StringSchema, tool_parameters_schema
from nanobot.bus.runtime_events import GoalStateChanged, RuntimeEventBus, RuntimeEventContext
from nanobot.session.goal_state import (
    GOAL_STATE_KEY,
    discard_legacy_goal_state_key,
    goal_state_raw,
    parse_goal_state,
)

# Re-export so ``from nanobot.agent.tools.long_task import LongTaskToolConfig``
# keeps working; the class itself lives in a dependency-light module to avoid
# import cycles during pydantic model_rebuild of ToolsConfig.
from nanobot.agent.tools.long_task_config import LongTaskToolConfig

if TYPE_CHECKING:
    from nanobot.session.manager import SessionManager


def _iso_now() -> str:
    return datetime.now().isoformat()


def _goal_feature_enabled(ctx: Any) -> bool:
    """Whether the sustained-goal feature (long_task/complete_goal + auto
    continuation) is active. Disabled by default; enable via config flag
    ``tools.long_task.enable = true`` or ``long_task_enable = true``.
    """
    config = getattr(ctx, "config", None)
    if config is None:
        return False
    lt = getattr(config, "long_task", None)
    if lt is not None:
        flag = getattr(lt, "enable", None)
        if flag is not None:
            return bool(flag)
    tools = getattr(config, "tools", None)
    if isinstance(tools, dict):
        lt = tools.get("long_task")
        if isinstance(lt, dict) and "enable" in lt:
            return bool(lt["enable"])
    flag = getattr(config, "long_task_enable", None)
    if flag is not None:
        return bool(flag)
    return False


class _GoalToolsMixin:
    """Shared routing context + Session lookup."""

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

    async def _publish_goal_state_changed(self, metadata: dict[str, Any]) -> None:
        """Publish authoritative goal metadata as a runtime event."""
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

    def __init__(
        self,
        sessions: Any,
        runtime_events: RuntimeEventBus | None = None,
    ) -> None:
        _GoalToolsMixin.__init__(self, sessions, runtime_events)

    @classmethod
    def create(cls, ctx: Any) -> Tool:
        sess = getattr(ctx, "sessions", None)
        assert sess is not None  # guarded by enabled()
        return cls(
            sessions=sess,
            runtime_events=getattr(ctx, "runtime_events", None),
        )

    @classmethod
    def enabled(cls, ctx: Any) -> bool:
        if not _goal_feature_enabled(ctx):
            return False
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
            return ToolResult.error(
                "Error: long_task requires an active chat session (missing routing context)."
            )
        prior = parse_goal_state(goal_state_raw(sess.metadata))
        if isinstance(prior, dict) and prior.get("status") == "active":
            return ToolResult.error(
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
        await self._publish_goal_state_changed(sess.metadata)
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
        if not _goal_feature_enabled(ctx):
            return False
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
            return ToolResult.error("Error: complete_goal requires an active chat session.")
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
        await self._publish_goal_state_changed(sess.metadata)
        tail = (recap or "").strip()
        if tail:
            return f"Goal marked complete ({ended}). Recap:\n{tail}"
        return f"Goal marked complete ({ended})."
