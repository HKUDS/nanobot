"""Opt-in gateway watchdog; no cron jobs, tool replay, or model-based polling.

Claims and bounded audit history live alongside durable goal/checkpoint metadata.
The gateway owns one timer; AgentLoop revalidates claims under its session lock.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import time
from collections.abc import Callable
from typing import Any, cast
from uuid import uuid4

from loguru import logger

from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import GoalRecoveryConfig
from nanobot.session import turn_continuation
from nanobot.session.goal_state import goal_state_raw, parse_goal_state
from nanobot.session.keys import UNIFIED_SESSION_KEY, last_channel_from_metadata
from nanobot.session.manager import Session, SessionManager
from nanobot.session.recovery import (
    PENDING_FOLLOWUP_ID_KEY,
    PENDING_FOLLOWUPS_KEY,
    RUNTIME_CHECKPOINT_KEY,
    recovery_state_from_metadata,
    restore_pending_interruption,
    restore_runtime_checkpoint,
    runtime_checkpoint_safe_to_resume,
)

GOAL_RECOVERY_KEY = "goal_recovery"
GOAL_RECOVERY_INBOUND_KEY = "_goal_recovery_id"
_HOLD_STATUSES = {"paused", "closed", "cancelled", "canceled", "completed", "blocked",
                  "pending_confirmation", "awaiting_user", "awaiting_approval"}


def _record(session: Session) -> dict[str, Any]:
    value: object = session.metadata.get(GOAL_RECOVERY_KEY)
    return dict(cast(dict[str, Any], value)) if isinstance(value, dict) else {}


def _goal_id(session: Session) -> str:
    goal = parse_goal_state(goal_state_raw(session.metadata)) or {}
    identity = [goal.get("objective"), goal.get("started_at"), goal.get("replaced_at")]
    return hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:24]


def session_recovery_hold_reason(session: Session) -> str | None:
    """Shared safety gates for watchdog work and journaled (not new) user input."""
    # A durable user decision outranks diagnostic holds. Otherwise observing an
    # approval/inactive status can persist `held` over `paused` and lose /stop.
    record = _record(session)
    if record.get("goal_id") == _goal_id(session) and record.get("status") == "paused":
        return "paused"
    goal = parse_goal_state(goal_state_raw(session.metadata)) or {}
    if goal and goal.get("status") != "active":
        return "goal_inactive"
    metadata = session.metadata
    status: object = metadata.get("status")
    if status is not None and (not isinstance(status, str) or status in _HOLD_STATUSES):
        return "session_inactive"
    for key in ("paused", "closed", "pending_confirmation", "pending_approval"):
        if metadata.get(key) or goal.get(key):
            return key
    recovery = recovery_state_from_metadata(metadata)
    if recovery and (
        recovery["status"] in {"awaiting_user", "failed", "resuming"}
        or recovery.get("reason") == "dismissed"
    ):
        return "recovery_requires_user"
    checkpoint: object = metadata.get(RUNTIME_CHECKPOINT_KEY)
    if checkpoint is not None:
        if not isinstance(checkpoint, dict):
            return "checkpoint_invalid"
        data = cast(dict[str, Any], checkpoint)
        if data.get("phase") == "awaiting_tools":
            return "tool_state_unknown"
        if not runtime_checkpoint_safe_to_resume(data):
            return "checkpoint_invalid"
    # A materialized interrupted tool has unknown external effects even when its
    # original checkpoint was cleared by a graceful user cancellation.
    last_user = next((i for i in range(len(session.messages) - 1, -1, -1)
                      if session.messages[i].get("role") == "user"), -1)
    if any(row.get("role") == "tool" and row.get("_recovery_interrupted") is True
           for row in session.messages[last_user + 1:]):
        return "tool_state_unknown"
    return None


def goal_recovery_hold_reason(session: Session) -> str | None:
    """Require an explicit active goal in addition to the shared recovery gates."""
    reason = session_recovery_hold_reason(session)
    if reason:
        return reason
    goal = parse_goal_state(goal_state_raw(session.metadata))
    if not goal or goal.get("status") != "active":
        return "goal_inactive"
    if not isinstance(goal.get("objective"), str) or not goal["objective"].strip():
        return "goal_invalid"
    if session.metadata.get(PENDING_FOLLOWUPS_KEY):
        return "pending_user_followups"
    return None


class GoalRecoveryWatchdog:
    """Single-process lifecycle service using the gateway's existing session locks.

    A crashed queued claim can be replaced after its persisted cooldown. A crash
    during a tool still requires human review; no automatic replay is attempted.
    """

    def __init__(
        self,
        sessions: SessionManager,
        bus: MessageBus,
        config: GoalRecoveryConfig,
        *,
        is_busy: Callable[[str], bool],
        is_channel_enabled: Callable[[str], bool],
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.sessions = sessions
        self.bus = bus
        self.config = config
        self.is_busy = is_busy
        self.is_channel_enabled = is_channel_enabled
        self.clock = clock
        self._scan_lock = asyncio.Lock()
        self._owned_claims: set[str] = set()

    async def run(self) -> None:
        """Wait a full interval after startup; cancellation belongs to the gateway."""
        if not self.config.enabled:
            return
        logger.info("Goal recovery watchdog enabled; interval={}s", self.config.interval_seconds)
        while True:
            await asyncio.sleep(self.config.interval_seconds)
            try:
                await self.tick()
            except Exception:
                logger.exception("Goal recovery watchdog scan failed")

    def _save(self, session: Session, status: str, reason: str, **fields: Any) -> None:
        now = self.clock()
        record = _record(session)
        history_value: object = record.get("history")
        history: list[object] = (
            list(cast(list[object], history_value)) if isinstance(history_value, list) else []
        )
        if record.get("status") != status or record.get("reason") != reason or fields:
            history.append({"at": now, "status": status, "reason": reason,
                            "attempt_id": fields.get("attempt_id", record.get("attempt_id"))})
        record.update(fields)
        record.update(status=status, reason=reason, updated_at=now, history=history[-32:])
        session.metadata[GOAL_RECOVERY_KEY] = record
        # Use SessionManager's atomic/fsynced save, including restored checkpoints.
        self.sessions.save(session)
        logger.debug("Goal recovery {}: {} ({})", session.key, status, reason)

    def _route(self, session: Session) -> tuple[str, str] | None:
        route = last_channel_from_metadata(session.metadata)
        if route is None and session.key != UNIFIED_SESSION_KEY and ":" in session.key:
            channel, chat_id = session.key.split(":", 1)
            route = (channel, chat_id)
        if not route or not all(route) or not self.is_channel_enabled(route[0]):
            return None
        return route

    async def tick(self) -> None:
        """Inspect durable goals without model calls; claim only an eligible idle goal."""
        if not self.config.enabled or self._scan_lock.locked():
            return
        async with self._scan_lock:
            for item in self.sessions.list_sessions():
                key = item.get("key")
                if not isinstance(key, str) or self.is_busy(key):
                    continue
                try:
                    await self._inspect(key)
                except Exception:
                    # One corrupt session or failed delivery must not kill the timer.
                    logger.exception("Goal recovery failed for {}", key)

    async def _inspect(self, key: str) -> None:
        payload = self.sessions.read_session_metadata(key)
        if payload is None:
            return  # Deleted/closed sessions must never be recreated.
        metadata = payload.get("metadata")
        if not isinstance(metadata, dict) or not goal_state_raw(cast(dict[str, Any], metadata)):
            return
        session = self.sessions.get_or_create(key)
        reason = goal_recovery_hold_reason(session)
        if reason:
            record = _record(session)
            if record.get("reason") != reason:
                self._save(session, "paused" if reason == "paused" else "held", reason)
            return
        route = self._route(session)
        if route is None:
            self._save(session, "held", "channel_unavailable")
            return
        record = _record(session)
        goal_id = _goal_id(session)
        if record.get("goal_id") != goal_id:
            record = {}
        if record.get("attempt_id") in self._owned_claims:
            return
        now = self.clock()
        due = record.get("next_attempt_at", 0)
        if (not isinstance(due, (int, float)) or isinstance(due, bool)
                or not math.isfinite(due) or due < 0):
            self._save(session, "held", "invalid_cooldown")
            return
        # Recent user work and persisted cooldown both take precedence over polling.
        if now < max(due, session.updated_at.timestamp() + self.config.interval_seconds):
            return
        restore_runtime_checkpoint(session)
        restore_pending_interruption(session)
        attempt_id = uuid4().hex
        attempts = record.get("attempts", 0)
        attempts = attempts if isinstance(attempts, int) and attempts >= 0 else 0
        failures = record.get("failures", 0)
        failures = failures if isinstance(failures, int) and failures >= 0 else 0
        if record.get("status") in {"queued", "running"}:
            failures += 1  # Lost ownership on a previous gateway, never reset backoff.
        self._save(
            session, "queued", "idle_goal", goal_id=goal_id, attempt_id=attempt_id,
            attempts=attempts + 1, failures=failures, message_count=len(session.messages),
            next_attempt_at=now + self._delay(failures),
        )
        self._owned_claims.add(attempt_id)
        channel, chat_id = route
        metadata = {
            GOAL_RECOVERY_INBOUND_KEY: attempt_id,
            turn_continuation.INTERNAL_CONTINUATION_META: True,
            turn_continuation.SKIP_USER_PERSIST_META: True,
        }
        if channel == "websocket":
            metadata.update(webui=True, _wants_stream=True)
        try:
            await self.bus.publish_inbound(InboundMessage(
                channel=channel, chat_id=chat_id, sender_id="system:goal-recovery",
                content=(
                    "Continue the active sustained goal from its saved conversation and checkpoint. "
                    "Check actual progress first; do not repeat completed work or replay old tool calls. "
                    "This is permission to pursue the goal, not approval for unsafe or unapproved actions. "
                    "If blocked, uncertain about an external effect, or awaiting user approval, "
                    "stop and mark the goal blocked with update_goal. If done, mark it complete."
                ),
                metadata=metadata, input_role="system", session_key_override=key,
                require_existing_session=True,
            ))
        except Exception:
            self._owned_claims.discard(attempt_id)
            self._save(session, "failed", "enqueue_failed", failures=failures + 1,
                       next_attempt_at=now + self._delay(failures + 1))
            raise

    def _delay(self, failures: int) -> int:
        return min(self.config.interval_seconds * (2 ** min(failures, 16)),
                   max(self.config.interval_seconds, self.config.max_backoff_seconds))

    def observe_inbound(self, message: InboundMessage, key: str) -> bool:
        """Run before routing/priority commands; never inject a watchdog into busy work."""
        if not self.config.enabled:
            return GOAL_RECOVERY_INBOUND_KEY not in message.metadata
        if GOAL_RECOVERY_INBOUND_KEY in message.metadata:
            if self.is_busy(key):
                self.finish(message, "deferred")
                return False
            return True  # The definitive claim check is under the session lock.
        if (not message.is_user_input
                or turn_continuation.internal_continuation_inbound(message.metadata)
                or PENDING_FOLLOWUP_ID_KEY in message.metadata):
            return True  # A journal replay (even /goal text) is not a new user decision.
        session = self.sessions.get_cached(key)
        if session is None and self.sessions.read_session_metadata(key) is not None:
            session = self.sessions.get_or_create(key)
        if session is not None and goal_state_raw(session.metadata):
            record = _record(session)
            self._owned_claims.discard(str(record.get("attempt_id", "")))
            text = message.content.strip()
            stopped = text.lower() == "/stop"
            explicit_goal = text.lower().startswith("/goal ") and bool(text[6:].strip())
            if (record.get("status") == "paused" and record.get("goal_id") == _goal_id(session)
                    and not stopped and not explicit_goal):
                return True  # Ordinary chat or /help is not permission to unpause the watchdog.
            try:
                self._save(session, "paused" if stopped else "waiting",
                           "user_stopped" if stopped else "user_input", goal_id=_goal_id(session),
                           attempt_id=None, failures=0,
                           next_attempt_at=self.clock() + self.config.interval_seconds)
            except Exception:
                # In-memory invalidation already happened. Disk failure must not
                # prevent a user's /stop from reaching the normal cancellation path.
                logger.exception("Could not persist goal recovery user decision for {}", key)
        return True

    def claim(self, message: InboundMessage) -> bool:
        """Revalidate under AgentLoop's session lock, immediately before starting work."""
        attempt_id = message.metadata.get(GOAL_RECOVERY_INBOUND_KEY)
        if attempt_id is None:
            return True
        if not self.config.enabled or self.sessions.read_session_metadata(message.session_key) is None:
            return False
        session = self.sessions.get_cached(message.session_key)
        if session is None:
            return False
        record = _record(session)
        if (record.get("attempt_id") != attempt_id or record.get("status") != "queued"
                or record.get("goal_id") != _goal_id(session)):
            self._owned_claims.discard(str(attempt_id))
            return False
        reason = goal_recovery_hold_reason(session)
        if reason or self._route(session) != (message.channel, message.chat_id):
            self._owned_claims.discard(str(attempt_id))
            self._save(session, "held", reason or "route_changed")
            return False
        if record.get("message_count") != len(session.messages):
            self._owned_claims.discard(str(attempt_id))
            self._save(session, "waiting", "newer_activity",
                       next_attempt_at=self.clock() + self.config.interval_seconds)
            return False
        self._save(session, "running", "claimed")
        return True

    def finish(self, message: InboundMessage, outcome: str, *, shutdown: bool = False) -> None:
        """Record outcomes and backoff; user cancellation stays paused across restart."""
        if not self.config.enabled:
            return
        session = self.sessions.get_cached(message.session_key)
        if session is None or not goal_state_raw(session.metadata):
            return
        record = _record(session)
        attempt_id = message.metadata.get(GOAL_RECOVERY_INBOUND_KEY)
        if attempt_id is not None:
            self._owned_claims.discard(str(attempt_id))
            if record.get("attempt_id") != attempt_id:
                return  # Superseded by newer user input/goal; never overwrite their stop.
        elif record.get("status") == "paused":
            return
        failures = record.get("failures", 0)
        failures = failures if isinstance(failures, int) and failures >= 0 else 0
        if outcome == "cancelled" and not shutdown:
            status, reason = "paused", "user_stopped"
        elif outcome in {"error", "tool_error", "cancelled"}:
            status, reason = "failed", "gateway_shutdown" if shutdown else outcome
            failures += 1
        else:
            status, reason = "waiting", outcome
            if outcome != "deferred":
                failures = 0
        try:
            self._save(session, status, reason, goal_id=_goal_id(session), failures=failures,
                       next_attempt_at=self.clock() + self._delay(failures))
        except Exception:
            # This auxiliary callback must not mask a turn's result or cancellation.
            # Queuing/claiming still require successful durable writes and fail closed.
            logger.exception("Could not persist goal recovery outcome for {}", session.key)
