"""WebUI restart recovery over durable session checkpoints."""

from __future__ import annotations

import asyncio
import dataclasses
from collections.abc import Mapping
from datetime import datetime
from typing import Any, cast
from uuid import uuid4

from loguru import logger

from nanobot.bus.events import InboundMessage
from nanobot.bus.outbound_events import (
    RecoveryStateEvent,
    SessionUpdatedEvent,
    outbound_message_for_event,
)
from nanobot.bus.queue import MessageBus
from nanobot.session import turn_continuation
from nanobot.session.keys import UNIFIED_SESSION_KEY, last_channel_from_metadata
from nanobot.session.manager import Session, SessionManager
from nanobot.session.recovery import (
    KNOWN_CHECKPOINT_PHASES,
    PENDING_FOLLOWUPS_KEY,
    PENDING_USER_TURN_KEY,
    RECOVERY_INBOUND_METADATA_KEY,
    RECOVERY_METADATA_KEY,
    REQUEST_ORIGIN_METADATA_KEY,
    RUNTIME_CHECKPOINT_KEY,
    UNCERTAIN_TOOL_PHASES,
    append_recovery_interruption,
    discard_runtime_checkpoint,
    pending_followups,
    recovery_state_from_metadata,
    request_origin_from_metadata,
    restore_pending_interruption,
    restore_runtime_checkpoint,
    runtime_checkpoint_is_well_formed,
)
from nanobot.webui.metadata import WEBUI_TURN_METADATA_KEY
from nanobot.webui.session_identity import webui_chat_id, webui_session_key


class RecoveryActionError(ValueError):
    """A stale or malformed recovery action from an authenticated WebUI."""

    def __init__(self, message: str, *, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


@dataclasses.dataclass(slots=True)
class RecoveryCoordinator:
    """Classify, announce, and gate durable WebUI turn recovery."""

    sessions: SessionManager
    bus: MessageBus
    unified_session: bool = False
    _active_recovery_tasks: dict[str, asyncio.Task[Any]] = dataclasses.field(
        default_factory=dict,
        init=False,
        repr=False,
    )

    def register_recovery_task(self, session_key: str, task: asyncio.Task[Any]) -> None:
        """Track the task that owns an explicit recovery continuation."""
        self._active_recovery_tasks[session_key] = task

    def unregister_recovery_task(self, session_key: str, task: asyncio.Task[Any]) -> None:
        """Drop a recovery task without removing a newer task for the same session."""
        if self._active_recovery_tasks.get(session_key) is task:
            self._active_recovery_tasks.pop(session_key, None)

    async def _cancel_active_recovery(self, session_key: str) -> None:
        """Stop an explicit continuation before accepting newer user input."""
        task = self._active_recovery_tasks.get(session_key)
        if task is None or task is asyncio.current_task() or task.done():
            return
        task.cancel()
        # AgentLoop's cancellation path materializes any partial checkpoint and
        # releases its pending queue. Wait for that ownership to be released
        # before the newer message is routed.
        await asyncio.gather(task, return_exceptions=True)

    async def scan(self) -> None:
        """Recover every interrupted WebUI session once at gateway startup."""
        for key in await self._recovery_candidates():
            metadata_payload = await self.sessions.state.read_metadata(key)
            raw_metadata = metadata_payload.get("metadata") if metadata_payload else None
            metadata = cast(dict[str, Any], raw_metadata) if isinstance(raw_metadata, dict) else {}
            route = self._websocket_route_for(key, metadata)
            if route is None:
                continue
            unfinished = self._has_unfinished_webui_transcript(key)
            if not self._needs_recovery(metadata) and not unfinished:
                continue
            session = await self.sessions.state.get(key)
            try:
                await self._recover_session(session, route[1])
                await self._requeue_pending_followups(session)
            except Exception:
                logger.exception("failed to recover interrupted WebUI session {}", session.key)
                state = recovery_state_from_metadata(session.metadata)
                failed = self._set_state(
                    session,
                    status="failed",
                    recovery_id=cast(str, state["recovery_id"]) if state else uuid4().hex,
                    attempts=cast(int, state.get("attempts", 0)) if state else 0,
                    reason="recovery_failed",
                    can_continue=False,
                )
                await self.sessions.state.restore_interruption(session)
                await self._publish(route[1], failed)

    async def _recovery_candidates(self) -> list[str]:
        """Discover canonical and transcript-only WebUI sessions cheaply."""
        candidates = dict.fromkeys(
            key
            for item in await self.sessions.state.list_sessions()
            if isinstance((key := item.get("key")), str)
        )
        try:
            # Imported lazily because the sidebar index also projects recovery
            # metadata.  The index is the owner of transcript-only discovery;
            # duplicating its filename and migration rules here would drift.
            from nanobot.webui.session_list_index import list_webui_sessions

            for item in await asyncio.to_thread(list_webui_sessions, self.sessions):
                key = item.get("key")
                if isinstance(key, str):
                    candidates.setdefault(key, None)
        except Exception:
            # Canonical checkpoint recovery remains available even if the
            # optional display-history index is corrupt or unavailable.
            logger.exception("failed to discover transcript-only WebUI sessions")
        return list(candidates)

    @staticmethod
    def _needs_recovery(metadata: Mapping[str, Any]) -> bool:
        if metadata.get(PENDING_USER_TURN_KEY) is True:
            return True
        if isinstance(metadata.get(RUNTIME_CHECKPOINT_KEY), dict):
            return True
        followups = metadata.get(PENDING_FOLLOWUPS_KEY)
        if isinstance(followups, list) and len(cast(list[object], followups)) > 0:
            return True
        state = recovery_state_from_metadata(metadata)
        return bool(state and state["status"] in {"resuming", "awaiting_user", "failed"})

    async def admit(self, message: InboundMessage) -> bool:
        """Reject stale queued recoveries and let new user input supersede them."""
        recovery_id = message.metadata.get(RECOVERY_INBOUND_METADATA_KEY)
        if isinstance(recovery_id, str):
            session = await self.sessions.state.get(message.session_key)
            state = recovery_state_from_metadata(session.metadata)
            return bool(
                state
                and state["status"] == "resuming"
                and state["recovery_id"] == recovery_id
            )
        if message.channel != "websocket":
            return True
        session = await self.sessions.state.get(message.session_key)
        state = recovery_state_from_metadata(session.metadata)
        if state and state["status"] in {"resuming", "awaiting_user", "failed"}:
            await self._cancel_active_recovery(message.session_key)
            restore_runtime_checkpoint(session)
            if not restore_pending_interruption(session, superseded=True):
                append_recovery_interruption(session, superseded=True)
            recovered = self._set_state(
                session,
                status="recovered",
                recovery_id=cast(str, state["recovery_id"]),
                attempts=cast(int, state.get("attempts", 0)),
                reason="superseded",
            )
            await self.sessions.state.restore_interruption(session)
            await self._publish(message.chat_id, recovered)
        return True

    async def turn_completed(self, session_key: str) -> None:
        """Resolve a resuming state after the recovered turn commits."""
        session = await self.sessions.state.get(session_key)
        state = recovery_state_from_metadata(session.metadata)
        if not state or state["status"] != "resuming":
            return
        route = self._websocket_route(session)
        if route is None:
            return
        recovered = self._set_state(
            session,
            status="recovered",
            recovery_id=cast(str, state["recovery_id"]),
            attempts=cast(int, state.get("attempts", 0)),
            reason="continued",
        )
        await self.sessions.state.restore_interruption(session)
        await self._publish(route[1], recovered)

    async def handle_action(self, action: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Apply an authenticated continue/dismiss operation."""
        chat_id = payload.get("chat_id")
        recovery_id = payload.get("recovery_id")
        if not isinstance(chat_id, str) or not chat_id:
            raise RecoveryActionError("missing chat_id")
        if not isinstance(recovery_id, str) or not recovery_id:
            raise RecoveryActionError("missing recovery_id")
        session = await self.sessions.state.get(self._session_key(chat_id))
        state = recovery_state_from_metadata(session.metadata)
        if not state or state["recovery_id"] != recovery_id:
            raise RecoveryActionError("recovery state is stale", status=409)

        if action == "dismiss":
            restore_runtime_checkpoint(session)
            restore_pending_interruption(session)
            next_state = self._set_state(
                session,
                status="recovered",
                recovery_id=recovery_id,
                attempts=cast(int, state.get("attempts", 0)),
                reason="dismissed",
            )
            await self.sessions.state.restore_interruption(session)
            await self._publish(chat_id, next_state)
            return next_state
        if action != "continue":
            raise RecoveryActionError("unknown recovery action")
        if state["status"] not in {"awaiting_user", "failed"}:
            raise RecoveryActionError("recovery is not waiting for confirmation", status=409)
        if state.get("can_continue") is False:
            raise RecoveryActionError("recovery context is unavailable", status=409)
        next_state = self._set_state(
            session,
            status="resuming",
            recovery_id=recovery_id,
            attempts=cast(int, state.get("attempts", 0)) + 1,
            reason="user_confirmed",
            resume_message_count=len(session.messages),
        )
        await self.sessions.state.restore_interruption(session)
        await self._publish(chat_id, next_state)
        await self._queue_continuation(session, chat_id, next_state)
        return next_state

    async def _recover_session(self, session: Session, chat_id: str) -> None:
        checkpoint_value = cast(object, session.metadata.get(RUNTIME_CHECKPOINT_KEY))
        checkpoint = (
            cast(dict[str, Any], checkpoint_value)
            if isinstance(checkpoint_value, dict)
            else None
        )
        pending = session.metadata.get(PENDING_USER_TURN_KEY) is True
        state = recovery_state_from_metadata(session.metadata)
        if not pending and checkpoint is None:
            if state and state["status"] == "resuming":
                resume_count = self._resume_message_count(session)
                if resume_count is not None and len(session.messages) > resume_count:
                    next_state = self._set_state(
                        session,
                        status="recovered",
                        recovery_id=cast(str, state["recovery_id"]),
                        attempts=cast(int, state.get("attempts", 0)),
                        reason="committed",
                    )
                else:
                    next_state = self._set_state(
                        session,
                        status="awaiting_user",
                        recovery_id=cast(str, state["recovery_id"]),
                        attempts=cast(int, state.get("attempts", 1)),
                        reason="loop_guard",
                    )
                await self.sessions.state.restore_interruption(session)
                await self._publish(chat_id, next_state)
            elif self._has_unfinished_webui_transcript(session.key):
                # A normal last-client shutdown can materialize the checkpoint
                # before the process exits.  In that path there is no pending
                # marker left to classify, but the append-only transcript still
                # contains an activity row without a turn_end.  Treat it as an
                # interrupted turn instead of letting the UI resurrect it as a
                # forever-running spinner.
                can_continue = self._has_saved_continuation_context(session)
                waiting = self._set_state(
                    session,
                    status="awaiting_user",
                    recovery_id=uuid4().hex,
                    attempts=0,
                    reason=(
                        "interrupted_with_saved_context"
                        if can_continue
                        else "interrupted_without_checkpoint"
                    ),
                    can_continue=can_continue,
                )
                await self.sessions.state.restore_interruption(session)
                await self._publish(chat_id, waiting)
            return
        if state and state["status"] in {"awaiting_user", "failed"}:
            await self._publish(chat_id, state)
            return
        if state and state["status"] == "resuming":
            restore_runtime_checkpoint(session)
            restore_pending_interruption(session)
            waiting = self._set_state(
                session,
                status="awaiting_user",
                recovery_id=cast(str, state["recovery_id"]),
                attempts=cast(int, state.get("attempts", 1)),
                reason="loop_guard",
            )
            await self.sessions.state.restore_interruption(session)
            await self._publish(chat_id, waiting)
            return

        recovery_id = uuid4().hex
        phase = checkpoint.get("phase") if checkpoint is not None else None
        pending_calls = checkpoint.get("pending_tool_calls") if checkpoint is not None else None
        if checkpoint is not None and phase not in KNOWN_CHECKPOINT_PHASES:
            discard_runtime_checkpoint(session)
            restore_pending_interruption(session)
            waiting = self._set_state(
                session,
                status="awaiting_user",
                recovery_id=recovery_id,
                attempts=0,
                reason="checkpoint_unknown",
                can_continue=False,
            )
            await self.sessions.state.restore_interruption(session)
            await self._publish(chat_id, waiting)
            return
        if checkpoint is not None and not runtime_checkpoint_is_well_formed(checkpoint):
            discard_runtime_checkpoint(session)
            restore_pending_interruption(session)
            waiting = self._set_state(
                session,
                status="awaiting_user",
                recovery_id=recovery_id,
                attempts=0,
                reason="checkpoint_invalid",
                can_continue=False,
            )
            await self.sessions.state.restore_interruption(session)
            await self._publish(chat_id, waiting)
            return
        if phase == "final_response":
            restore_runtime_checkpoint(session)
            recovered = self._set_state(
                session,
                status="recovered",
                recovery_id=recovery_id,
                attempts=0,
                reason="answer_restored",
            )
            await self.sessions.state.restore_interruption(session)
            await self._publish(chat_id, recovered)
            return
        if phase in UNCERTAIN_TOOL_PHASES or pending_calls:
            restore_runtime_checkpoint(session)
            waiting = self._set_state(
                session,
                status="awaiting_user",
                recovery_id=recovery_id,
                attempts=0,
                reason="tool_state_unknown",
            )
            await self.sessions.state.restore_interruption(session)
            await self._publish(chat_id, waiting)
            return
        # A gateway restart is a lifecycle boundary.  Never enqueue model work
        # implicitly: even a synchronized checkpoint may sit next to an
        # external side effect that the user should review first.  The final
        # answer path above only restores persisted output; it never executes.
        restore_runtime_checkpoint(session)
        waiting = self._set_state(
            session,
            status="awaiting_user",
            recovery_id=recovery_id,
            attempts=0,
            reason="restart_requires_confirmation",
        )
        await self.sessions.state.restore_interruption(session)
        await self._publish(chat_id, waiting)

    async def _queue_continuation(
        self,
        session: Session,
        chat_id: str,
        state: Mapping[str, Any],
    ) -> None:
        recovery_id = cast(str, state["recovery_id"])
        origin = request_origin_from_metadata(session.metadata)
        await self.bus.publish_inbound(
            InboundMessage(
                channel="websocket",
                sender_id="system:recovery",
                chat_id=chat_id,
                content=(
                    "Continue the interrupted request from the saved conversation context. "
                    "Do not repeat completed work or mention the restart unless it affects the answer."
                ),
                metadata={
                    "webui": True,
                    "_wants_stream": True,
                    WEBUI_TURN_METADATA_KEY: f"recovery:{recovery_id}",
                    RECOVERY_INBOUND_METADATA_KEY: recovery_id,
                    turn_continuation.INTERNAL_CONTINUATION_META: True,
                    turn_continuation.SKIP_USER_PERSIST_META: True,
                    **({REQUEST_ORIGIN_METADATA_KEY: origin} if origin is not None else {}),
                },
                session_key_override=session.key,
                require_existing_session=True,
            )
        )

    async def _requeue_pending_followups(self, session: Session) -> None:
        """Return durable live-turn follow-ups to the bus after a restart."""
        for message in pending_followups(session):
            await self.bus.publish_inbound(message)

    @staticmethod
    def _resume_message_count(session: Session) -> int | None:
        raw_value = cast(object, session.metadata.get(RECOVERY_METADATA_KEY))
        value = cast(dict[str, Any], raw_value) if isinstance(raw_value, dict) else None
        if value is None:
            return None
        count = value.get("resume_message_count")
        return count if isinstance(count, int) and count >= 0 else None

    async def _publish(
        self,
        chat_id: str,
        state: Mapping[str, Any],
    ) -> None:
        """Publish the recovery state and invalidate its sidebar projection."""
        await self.bus.publish_outbound(
            outbound_message_for_event(
                channel="websocket",
                chat_id=chat_id,
                event=RecoveryStateEvent(
                    status=cast(str, state["status"]),
                    recovery_id=cast(str, state["recovery_id"]),
                    reason=cast(str | None, state.get("reason")),
                    attempts=cast(int, state.get("attempts", 0)),
                    can_continue=cast(bool | None, state.get("can_continue")),
                ),
            )
        )
        await self.bus.publish_outbound(
            outbound_message_for_event(
                channel="websocket",
                chat_id=chat_id,
                event=SessionUpdatedEvent(scope="thread"),
            )
        )

    @staticmethod
    def _set_state(
        session: Session,
        *,
        status: str,
        recovery_id: str,
        attempts: int,
        reason: str,
        resume_message_count: int | None = None,
        can_continue: bool = True,
    ) -> dict[str, Any]:
        state = {
            "status": status,
            "recovery_id": recovery_id,
            "attempts": max(0, attempts),
            "reason": reason,
            "updated_at": datetime.now().isoformat(),
        }
        if not can_continue:
            state["can_continue"] = False
        if resume_message_count is not None:
            state["resume_message_count"] = max(0, resume_message_count)
        session.metadata[RECOVERY_METADATA_KEY] = state
        session.updated_at = datetime.now()
        return state

    def _session_key(self, chat_id: str) -> str:
        return UNIFIED_SESSION_KEY if self.unified_session else webui_session_key(chat_id)

    @staticmethod
    def _has_unfinished_webui_transcript(session_key: str) -> bool:
        """Detect a stale WebUI activity tail after an unclean gateway stop.

        The transcript is intentionally consulted only as a last-resort signal:
        a durable pending turn or runtime checkpoint always takes precedence.
        This keeps browser disconnects harmless while preventing a materialized
        partial turn from being presented as active forever after a restart.
        """
        try:
            from nanobot.webui.transcript import has_unfinished_transcript_tail

            return has_unfinished_transcript_tail(session_key)
        except (OSError, ValueError, TypeError):
            # Recovery must fail closed if the optional display transcript is
            # corrupt or unavailable; the normal checkpoint path still applies.
            return False

    @staticmethod
    def _has_saved_continuation_context(session: Session) -> bool:
        """Whether an interrupted turn left model-visible context to continue from."""
        last_user = next(
            (
                index
                for index in range(len(session.messages) - 1, -1, -1)
                if session.messages[index].get("role") == "user"
            ),
            None,
        )
        if last_user is None:
            return False
        tail = session.messages[last_user + 1 :]
        return bool(tail) and (
            tail[-1].get("role") == "tool"
            or any(message.get("_recovery_interrupted") is True for message in tail)
            or any(
                message.get("role") == "assistant" and bool(message.get("tool_calls"))
                for message in tail
            )
        )

    @staticmethod
    def _websocket_route(session: Session) -> tuple[str, str] | None:
        return RecoveryCoordinator._websocket_route_for(session.key, session.metadata)

    @staticmethod
    def _websocket_route_for(
        session_key: str,
        metadata: Mapping[str, Any],
    ) -> tuple[str, str] | None:
        chat_id = webui_chat_id(session_key)
        if chat_id is not None:
            return ("websocket", chat_id)
        if session_key == UNIFIED_SESSION_KEY:
            route = last_channel_from_metadata(metadata)
            if route and route[0] == "websocket":
                return route
        return None
