"""Sustained-goal tools with explicit user opt-in at the execution boundary."""

# pyright: reportIncompatibleMethodOverride=false

from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import replace
from datetime import datetime
from typing import TYPE_CHECKING, Any

from nanobot.agent.completion import (
    CompletionVerdict,
    CompletionVerifier,
    current_completion_evidence,
)
from nanobot.agent.goal_permission import (
    goal_mutation_allowed,
    revoke_goal_mutation_permission,
)
from nanobot.agent.tools.base import Tool, ToolResult, tool_parameters
from nanobot.agent.tools.context import RequestContext, ToolContext, current_request_context
from nanobot.agent.tools.schema import StringSchema, tool_parameters_schema
from nanobot.bus.queue import MessageBus
from nanobot.bus.runtime_events import GoalStateChanged, RuntimeEventContext
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
    from nanobot.session.manager import Session, SessionManager


_GOAL_ACTIONS = ("complete", "cancel", "block", "replace")
_MAX_VERIFICATION_ATTEMPTS = 2


def _criteria_error(criteria: str | None) -> str | None:
    if criteria is not None and not (0 < len(criteria.strip()) <= 4000):
        return "Error: acceptance_criteria must contain between 1 and 4000 characters."
    return None


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
        bus: MessageBus | None = None,
    ) -> None:
        self._sessions = sessions
        self._bus = bus

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
        bus = self._bus
        rc = current_request_context()
        if bus is None or rc is None:
            return
        cid = (rc.chat_id or "").strip()
        if not cid:
            return
        await bus.publish(
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
        acceptance_criteria=StringSchema(
            "Optional concrete acceptance criteria, frozen when the goal is created. "
            "Enables up to two independent completion reviews of the result and observed tool evidence.",
            min_length=1, max_length=4000, nullable=True,
        ),
        required=["objective"],
    )
)
class CreateGoalTool(Tool, _GoalToolsMixin):
    """Create one explicit sustained objective for the current session."""

    def __init__(
        self,
        sessions: SessionManager,
        bus: MessageBus | None = None,
    ) -> None:
        _GoalToolsMixin.__init__(self, sessions, bus)

    @classmethod
    def create(cls, ctx: ToolContext) -> Tool:
        sess = ctx.sessions
        if sess is None:
            raise RuntimeError("CreateGoalTool requires an initialized session manager")
        return cls(
            sessions=sess,
            bus=ctx.bus,
        )

    @classmethod
    def enabled(cls, ctx: ToolContext) -> bool:
        return ctx.sessions is not None

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
            " Supply acceptance_criteria to require an independent review before completion."
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
        acceptance_criteria: str | None = None,
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
        if criteria_error := _criteria_error(acceptance_criteria):
            return ToolResult.error(criteria_error)
        blob = {
            "status": "active",
            "objective": objective_text,
            "ui_summary": summary,
            "started_at": _iso_now(),
        }
        if acceptance_criteria is not None:
            blob["acceptance_criteria"] = acceptance_criteria.strip()
        self._save_goal_state(sess, blob, reset_continuation=True)
        if acceptance_criteria is not None:
            revoke_goal_mutation_permission()
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
        acceptance_criteria=StringSchema(
            "Acceptance criteria for a replacement goal only. Completion cannot change the criteria.",
            min_length=1, max_length=4000, nullable=True,
        ),
        required=["action"],
    )
)
class UpdateGoalTool(Tool, _GoalToolsMixin):
    """Complete, cancel, block, or replace the active sustained goal."""

    def __init__(
        self,
        sessions: SessionManager,
        bus: MessageBus | None = None,
    ) -> None:
        _GoalToolsMixin.__init__(self, sessions, bus)

    @classmethod
    def create(cls, ctx: ToolContext) -> Tool:
        sess = ctx.sessions
        if sess is None:
            raise RuntimeError("UpdateGoalTool requires an initialized session manager")
        return cls(
            sessions=sess,
            bus=ctx.bus,
        )

    @classmethod
    def enabled(cls, ctx: ToolContext) -> bool:
        return ctx.sessions is not None

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
            " For a goal with acceptance_criteria, complete runs an independent review; "
            "call it on its own after the work and verification tools finish."
        )

    async def execute(
        self,
        action: str,
        recap: str | None = None,
        objective: str | None = None,
        ui_summary: str | None = None,
        acceptance_criteria: str | None = None,
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
        if acceptance_criteria is not None and normalized != "replace":
            return ToolResult.error("Error: acceptance_criteria can only change when replacing the goal.")

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
            if criteria_error := _criteria_error(acceptance_criteria):
                return ToolResult.error(criteria_error)
            blob = {
                "status": "active",
                "objective": objective_text,
                "ui_summary": summary,
                "started_at": _iso_now(),
                "replaced_at": _iso_now(),
                "previous_objective": str(prior.get("objective") or ""),
                "recap": (recap or "").strip(),
            }
            if acceptance_criteria is not None:
                blob["acceptance_criteria"] = acceptance_criteria.strip()
            self._save_goal_state(sess, blob, reset_continuation=True)
            if acceptance_criteria is not None:
                revoke_goal_mutation_permission()
            await self._publish_goal_state_changed(sess.metadata)
            extra = f"\nSummary line: {summary}" if summary else ""
            return "Goal replaced. Continue toward the new objective using ordinary tools." + extra

        verdict: CompletionVerdict | None = None
        if normalized == "complete" and prior.get("acceptance_criteria"):
            reviewed = await self._review_completion(sess, prior, (recap or "").strip())
            if isinstance(reviewed, str):
                return ToolResult.error(reviewed)
            prior, verdict = reviewed

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
        if verdict is not None:
            evidence = current_completion_evidence()
            assert evidence is not None
            evidence.verified_goal = ((recap or "").strip(), verdict)

        tail = (recap or "").strip()
        label = {
            "complete": "complete",
            "cancel": "cancelled",
            "block": "blocked",
        }[normalized]
        if tail:
            return f"Goal marked {label} ({ended}). Recap:\n{tail}"
        return f"Goal marked {label} ({ended})."

    async def _review_completion(
        self, sess: Session, prior: dict[str, Any], recap: str,
    ) -> tuple[dict[str, Any], CompletionVerdict] | str:
        request = current_request_context()
        evidence = current_completion_evidence()
        if request is None or request.runtime is None or evidence is None:
            return "Error: completion review requires an active agent run and model runtime."
        if not recap:
            return "Error: provide a result recap for completion review."
        messages = evidence.snapshot()
        # A batch is recorded only after all its calls return. Do not accept a
        # proof while another tool in this batch can still change the result.
        pending = {
            call["id"]: call.get("function", {}).get("name")
            for message in messages
            for call in message.get("tool_calls", [])
        }
        for message in messages:
            if message.get("role") == "tool":
                pending.pop(message.get("tool_call_id"), None)
        if pending and (len(pending) != 1 or next(iter(pending.values())) != "update_goal"):
            return "Error: call update_goal complete on its own after all other tools finish."

        snapshot = deepcopy(prior)
        attempts = int(prior.get("verification_attempts", 0))
        verifier = CompletionVerifier(
            request.runtime,
            f"Objective:\n{prior['objective']}\n\nAcceptance criteria:\n{prior['acceptance_criteria']}",
            max_attempts=max(0, _MAX_VERIFICATION_ATTEMPTS - attempts),
        )
        verdict = await verifier.verify(recap, messages)
        evidence.record_usage(verifier.usage)
        task = asyncio.current_task()
        if task is not None and task.cancelling():
            raise asyncio.CancelledError
        if parse_goal_state(goal_state_raw(sess.metadata)) != snapshot:
            return "Error: the goal changed during completion review; the result was not applied."
        attempts += verifier.attempts
        if verdict.status == "needs_revision" and attempts >= _MAX_VERIFICATION_ATTEMPTS:
            verdict = replace(verdict, status="exhausted")
        reviewed = {
            **prior,
            "verification_attempts": attempts,
            "completion": verdict.as_dict(),
        }
        if verdict.status == "verified":
            return reviewed, verdict
        if verdict.status in {"blocked", "exhausted"}:
            reviewed.update(status="blocked", ended_at=_iso_now(), recap=verdict.reason)
        self._save_goal_state(sess, reviewed)
        await self._publish_goal_state_changed(sess.metadata)
        return f"Completion was not verified ({verdict.status}): {verdict.reason}"
