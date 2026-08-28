"""Durable, side-effect-safe recovery for interrupted WebUI turns.

The coordinator owns restart policy.  Checkpoint materialization is a session
operation shared with AgentLoop lifecycle boundaries, so transport code never
has to guess whether an interrupted tool call is safe to replay.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any, Protocol, cast
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
from nanobot.session.async_compat import call_session_manager
from nanobot.session.keys import UNIFIED_SESSION_KEY, last_channel_from_metadata
from nanobot.session.manager import Session, SessionManager
from nanobot.webui.metadata import WEBUI_TURN_METADATA_KEY
from nanobot.webui.session_identity import webui_chat_id, webui_session_key

RUNTIME_CHECKPOINT_KEY = "runtime_checkpoint"
PENDING_USER_TURN_KEY = "pending_user_turn"
RECOVERY_METADATA_KEY = "webui_recovery"
RECOVERY_INBOUND_METADATA_KEY = "_webui_recovery_id"
PENDING_FOLLOWUPS_KEY = "pending_user_followups"
PENDING_FOLLOWUP_ID_KEY = "_recovery_followup_id"
PROVIDER_STATE_CHECKPOINT_VERSION_KEY = "provider_state_checkpoint_version"
PROVIDER_STATE_CHECKPOINT_VERSION = "v1"

_RECOVERY_STATUSES = frozenset({"resuming", "awaiting_user", "recovered", "failed"})
_UNCERTAIN_TOOL_PHASES = frozenset({"awaiting_tools"})
_KNOWN_CHECKPOINT_PHASES = frozenset(
    {"final_response", "tools_completed", "awaiting_tools", "error"}
)


class RecoveryActionError(ValueError):
    """A stale or malformed recovery action from an authenticated WebUI."""

    def __init__(self, message: str, *, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


class RecoveryAdmission(Protocol):
    """Narrow AgentLoop boundary for explicit recovery validation."""

    async def admit(self, message: InboundMessage) -> bool: ...

    def register_recovery_task(self, session_key: str, task: asyncio.Task[Any]) -> None: ...

    def unregister_recovery_task(self, session_key: str, task: asyncio.Task[Any]) -> None: ...


def record_pending_followup(session: Session, message: InboundMessage) -> str | None:
    """Durably journal a WebUI follow-up before injecting it into a live turn."""
    if message.channel != "websocket":
        return None
    try:
        metadata_value: object = json.loads(json.dumps(message.metadata))
    except (TypeError, ValueError):
        logger.warning("Skipping non-serializable WebUI follow-up for recovery")
        return None
    if not isinstance(metadata_value, dict):
        return None
    metadata = cast(dict[str, Any], metadata_value)
    existing_id = metadata.pop(PENDING_FOLLOWUP_ID_KEY, None)
    followup_id = (
        existing_id
        if isinstance(existing_id, str) and existing_id
        else uuid4().hex
    )
    records = _pending_followup_records(session)
    if any(record.get("id") == followup_id for record in records):
        return followup_id
    records.append(
        {
            "id": followup_id,
            "sender_id": message.sender_id,
            "chat_id": message.chat_id,
            "content": message.content,
            "media": list(message.media or []),
            "metadata": metadata,
        }
    )
    # This journal is the recovery source of truth, not a mirror of the
    # bounded in-memory injection queue.  A queued turn can receive more
    # follow-ups than the live queue accepts; dropping older journal entries
    # would make those acknowledged user messages unrecoverable after a
    # gateway restart.  Entries are removed only once their user rows are
    # committed by ``acknowledge_pending_followups``.
    session.metadata[PENDING_FOLLOWUPS_KEY] = records
    session.updated_at = datetime.now()
    return followup_id


def pending_followups(session: Session) -> list[InboundMessage]:
    """Decode still-unacknowledged follow-ups from durable session metadata."""
    messages: list[InboundMessage] = []
    for record in _pending_followup_records(session):
        followup_id = cast(object, record.get("id"))
        sender_id = cast(object, record.get("sender_id"))
        chat_id = cast(object, record.get("chat_id"))
        content = cast(object, record.get("content"))
        metadata = cast(object, record.get("metadata"))
        if (
            not isinstance(followup_id, str)
            or not followup_id
            or not isinstance(sender_id, str)
            or not sender_id
            or not isinstance(chat_id, str)
            or not chat_id
        ):
            continue
        if not isinstance(content, str) or not isinstance(metadata, dict):
            continue
        media_value = cast(object, record.get("media"))
        media = (
            [item for item in cast(list[object], media_value) if isinstance(item, str)]
            if isinstance(media_value, list)
            else []
        )
        messages.append(
            InboundMessage(
                channel="websocket",
                sender_id=sender_id,
                chat_id=chat_id,
                content=content,
                media=media,
                metadata={**cast(dict[str, Any], metadata), PENDING_FOLLOWUP_ID_KEY: followup_id},
                session_key_override=session.key,
                require_existing_session=True,
            )
        )
    return messages


def acknowledge_pending_followups(session: Session, followup_ids: Iterable[str]) -> None:
    """Remove journal entries whose user rows were committed to history."""
    acknowledged = set(followup_ids)
    if not acknowledged:
        return
    records = [record for record in _pending_followup_records(session) if record.get("id") not in acknowledged]
    if records:
        session.metadata[PENDING_FOLLOWUPS_KEY] = records
    else:
        session.metadata.pop(PENDING_FOLLOWUPS_KEY, None)


def _pending_followup_records(session: Session) -> list[dict[str, Any]]:
    raw = cast(object, session.metadata.get(PENDING_FOLLOWUPS_KEY))
    if not isinstance(raw, list):
        return []
    values = cast(list[object], raw)
    return [cast(dict[str, Any], value) for value in values if isinstance(value, dict)]


def _checkpoint_message_key(message: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        message.get("role"),
        message.get("content"),
        message.get("tool_call_id"),
        message.get("name"),
        message.get("tool_calls"),
        message.get("reasoning_content"),
        message.get("thinking_blocks"),
    )


def _checkpoint_tool_call_ids(
    value: object,
    *,
    result_rows: bool = False,
) -> list[str] | None:
    """Validate checkpoint tool rows and return their stable IDs."""
    if not isinstance(value, list):
        return None
    ids: list[str] = []
    for raw in cast(list[object], value):
        if not isinstance(raw, dict):
            return None
        row = cast(dict[str, Any], raw)
        id_key = "tool_call_id" if result_rows else "id"
        call_id = cast(object, row.get(id_key))
        if not isinstance(call_id, str) or not call_id:
            return None
        if result_rows:
            if row.get("role") != "tool":
                return None
        else:
            function_value = cast(object, row.get("function"))
            if not isinstance(function_value, dict):
                return None
            function = cast(dict[str, Any], function_value)
            name = cast(object, function.get("name"))
            if not isinstance(name, str) or not name:
                return None
        ids.append(call_id)
    return ids if len(ids) == len(set(ids)) else None


def _runtime_checkpoint_is_well_formed(checkpoint: Mapping[str, Any]) -> bool:
    """Return whether a checkpoint is safe to offer for continuation.

    Restoration stays tolerant so Dismiss can always clear corrupt state.
    Continue is stricter: silently dropping a malformed tool result could make
    the model repeat an external side effect.
    """
    assistant_value = cast(object, checkpoint.get("assistant_message"))
    if not isinstance(assistant_value, dict):
        return False
    assistant = cast(dict[str, Any], assistant_value)
    if assistant.get("role") != "assistant":
        return False

    completed_ids = _checkpoint_tool_call_ids(
        cast(object, checkpoint.get("completed_tool_results")),
        result_rows=True,
    )
    pending_ids = _checkpoint_tool_call_ids(
        cast(object, checkpoint.get("pending_tool_calls")),
    )
    if completed_ids is None or pending_ids is None:
        return False
    assistant_calls_value = cast(object, assistant.get("tool_calls"))
    assistant_call_ids = (
        []
        if assistant_calls_value is None
        else _checkpoint_tool_call_ids(assistant_calls_value)
    )
    if assistant_call_ids is None:
        return False

    phase = checkpoint.get("phase")
    if phase == "final_response":
        content = cast(object, assistant.get("content"))
        return (
            isinstance(content, str)
            and bool(content.strip())
            and not assistant_call_ids
            and not completed_ids
            and not pending_ids
        )
    if phase == "awaiting_tools":
        return (
            bool(assistant_call_ids)
            and not completed_ids
            and len(assistant_call_ids) == len(pending_ids)
            and set(assistant_call_ids) == set(pending_ids)
        )
    if phase == "tools_completed":
        return (
            bool(assistant_call_ids)
            and not pending_ids
            and len(assistant_call_ids) == len(completed_ids)
            and set(assistant_call_ids) == set(completed_ids)
        )
    # Error checkpoints have no current producer contract. Treat legacy or
    # future instances as review-only until their exact persisted shape is
    # specified; guessing here could make a partial side effect repeat.
    return False


def restore_runtime_checkpoint(session: Session) -> bool:
    """Materialize the durable checkpoint exactly once and clear it.

    Pending tool calls become explicit interrupted tool results.  They are
    never executed here.  Provider-native state is retained only for the two
    checkpoint shapes known to be synchronized with persisted history.
    """
    checkpoint = cast(object, session.metadata.get(RUNTIME_CHECKPOINT_KEY))
    if not isinstance(checkpoint, dict):
        return False
    data = cast(dict[str, Any], checkpoint)
    assistant = cast(object, data.get("assistant_message"))
    completed_value = cast(object, data.get("completed_tool_results"))
    pending_value = cast(object, data.get("pending_tool_calls"))
    completed = cast(list[object], completed_value) if isinstance(completed_value, list) else []
    pending = cast(list[object], pending_value) if isinstance(pending_value, list) else []

    restored: list[dict[str, Any]] = []
    if isinstance(assistant, dict):
        assistant_row = cast(dict[str, Any], assistant)
    else:
        assistant_row = {}
    if assistant_row.get("role") == "assistant":
        row = dict(assistant_row)
        row.setdefault("timestamp", datetime.now().isoformat())
        restored.append(row)
    for value in completed:
        if not isinstance(value, dict):
            continue
        tool_result = cast(dict[str, Any], value)
        if tool_result.get("role") != "tool":
            continue
        row = dict(tool_result)
        row.setdefault("timestamp", datetime.now().isoformat())
        restored.append(row)
    for value in pending:
        if not isinstance(value, dict):
            continue
        tool_call = cast(dict[str, Any], value)
        tool_call_id = tool_call.get("id")
        function_value = cast(object, tool_call.get("function"))
        if not isinstance(tool_call_id, str) or not tool_call_id:
            continue
        function = (
            cast(dict[str, Any], function_value)
            if isinstance(function_value, dict)
            else {}
        )
        name = function.get("name")
        restored.append(
            {
                "role": "tool",
                "tool_call_id": tool_call_id,
                "name": name if isinstance(name, str) and name else "tool",
                "content": "Error: Task interrupted before this tool finished.",
                "timestamp": datetime.now().isoformat(),
                "_recovery_interrupted": True,
            }
        )

    overlap = 0
    for size in range(min(len(session.messages), len(restored)), 0, -1):
        if all(
            _checkpoint_message_key(left) == _checkpoint_message_key(right)
            for left, right in zip(session.messages[-size:], restored[:size])
        ):
            overlap = size
            break
    session.messages.extend(restored[overlap:])

    assistant_data = cast(dict[str, Any], assistant) if isinstance(assistant, dict) else None
    synchronized = (
        data.get(PROVIDER_STATE_CHECKPOINT_VERSION_KEY)
        == PROVIDER_STATE_CHECKPOINT_VERSION
    )
    phase = data.get("phase")
    exact_final = (
        phase == "final_response"
        and assistant_data is not None
        and assistant_data.get("role") == "assistant"
        and not data.get("completed_tool_results")
        and not data.get("pending_tool_calls")
    )
    exact_tools = (
        phase == "tools_completed"
        and assistant_data is not None
        and assistant_data.get("role") == "assistant"
        and not data.get("pending_tool_calls")
    )
    if not (synchronized and (exact_final or exact_tools)):
        session.provider_state = None

    session.metadata.pop(PENDING_USER_TURN_KEY, None)
    session.metadata.pop(RUNTIME_CHECKPOINT_KEY, None)
    session.updated_at = datetime.now()
    return True


def _discard_runtime_checkpoint(session: Session) -> bool:
    """Drop checkpoint state that cannot be projected into valid history."""
    if RUNTIME_CHECKPOINT_KEY not in session.metadata:
        return False
    session.metadata.pop(RUNTIME_CHECKPOINT_KEY, None)
    session.provider_state = None
    session.updated_at = datetime.now()
    return True


def restore_pending_interruption(session: Session, *, superseded: bool = False) -> bool:
    """Close a persisted user-only turn without pretending it was answered."""
    if not session.metadata.get(PENDING_USER_TURN_KEY):
        return False
    if session.messages and session.messages[-1].get("role") == "user":
        content = (
            "Task recovery was superseded by a newer message."
            if superseded
            else "Error: Task interrupted before a response was generated."
        )
        session.messages.append(
            {
                "role": "assistant",
                "content": content,
                "timestamp": datetime.now().isoformat(),
                "_recovery_interrupted": True,
            }
        )
        session.provider_state = None
        session.updated_at = datetime.now()
    session.metadata.pop(PENDING_USER_TURN_KEY, None)
    return True


def append_recovery_interruption(session: Session, *, superseded: bool = False) -> None:
    """Close a restored partial turn whose last durable row is not the user message."""
    if session.messages and session.messages[-1].get("_recovery_interrupted") is True:
        return
    session.messages.append(
        {
            "role": "assistant",
            "content": (
                "Task recovery was superseded by a newer message."
                if superseded
                else "Error: Task recovery was interrupted before completion."
            ),
            "timestamp": datetime.now().isoformat(),
            "_recovery_interrupted": True,
        }
    )
    session.provider_state = None
    session.updated_at = datetime.now()


def recovery_state_from_metadata(metadata: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Return a sanitized recovery state suitable for the WebSocket wire."""
    value = metadata.get(RECOVERY_METADATA_KEY) if metadata else None
    if not isinstance(value, dict):
        return None
    state = cast(dict[str, Any], value)
    status = state.get("status")
    recovery_id = state.get("recovery_id")
    if status not in _RECOVERY_STATUSES or not isinstance(recovery_id, str):
        return None
    payload: dict[str, Any] = {"status": status, "recovery_id": recovery_id}
    reason = state.get("reason")
    if isinstance(reason, str) and reason:
        payload["reason"] = reason
    attempts = state.get("attempts")
    if isinstance(attempts, int) and attempts >= 0:
        payload["attempts"] = attempts
    can_continue = state.get("can_continue")
    if isinstance(can_continue, bool):
        payload["can_continue"] = can_continue
    return payload


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

    async def _get_or_create_session(self, key: str) -> Session:
        return await call_session_manager(
            self.sessions,
            "get_or_create_async",
            self.sessions.get_or_create,
            key,
        )

    async def _save_session(self, session: Session) -> None:
        await call_session_manager(
            self.sessions,
            "save_async",
            self.sessions.save,
            session,
        )

    async def _read_session_metadata(self, key: str) -> dict[str, Any] | None:
        return await call_session_manager(
            self.sessions,
            "read_session_metadata_async",
            self.sessions.read_session_metadata,
            key,
        )

    async def _list_sessions(self) -> list[dict[str, Any]]:
        return await call_session_manager(
            self.sessions,
            "list_sessions_async",
            self.sessions.list_sessions,
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
            metadata_payload = await self._read_session_metadata(key)
            raw_metadata = metadata_payload.get("metadata") if metadata_payload else None
            metadata = cast(dict[str, Any], raw_metadata) if isinstance(raw_metadata, dict) else {}
            route = self._websocket_route_for(key, metadata)
            if route is None:
                continue
            unfinished = self._has_unfinished_webui_transcript(key)
            if not self._needs_recovery(metadata) and not unfinished:
                continue
            session = await self._get_or_create_session(key)
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
                await self._save_session(session)
                await self._publish(route[1], failed)

    async def _recovery_candidates(self) -> list[str]:
        """Discover canonical and transcript-only WebUI sessions cheaply."""
        candidates = dict.fromkeys(
            key
            for item in await self._list_sessions()
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
            session = await self._get_or_create_session(message.session_key)
            state = recovery_state_from_metadata(session.metadata)
            return bool(
                state
                and state["status"] == "resuming"
                and state["recovery_id"] == recovery_id
            )
        if message.channel != "websocket":
            return True
        session = await self._get_or_create_session(message.session_key)
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
            await self._save_session(session)
            await self._publish(message.chat_id, recovered)
        return True

    async def turn_completed(self, session_key: str) -> None:
        """Resolve a resuming state after the recovered turn commits."""
        session = await self._get_or_create_session(session_key)
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
        await self._save_session(session)
        await self._publish(route[1], recovered)

    async def handle_action(self, action: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Apply an authenticated continue/dismiss operation."""
        chat_id = payload.get("chat_id")
        recovery_id = payload.get("recovery_id")
        if not isinstance(chat_id, str) or not chat_id:
            raise RecoveryActionError("missing chat_id")
        if not isinstance(recovery_id, str) or not recovery_id:
            raise RecoveryActionError("missing recovery_id")
        session = await self._get_or_create_session(self._session_key(chat_id))
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
            await self._save_session(session)
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
        await self._save_session(session)
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
                await self._save_session(session)
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
                await self._save_session(session)
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
            await self._save_session(session)
            await self._publish(chat_id, waiting)
            return

        recovery_id = uuid4().hex
        phase = checkpoint.get("phase") if checkpoint is not None else None
        pending_calls = checkpoint.get("pending_tool_calls") if checkpoint is not None else None
        if checkpoint is not None and phase not in _KNOWN_CHECKPOINT_PHASES:
            _discard_runtime_checkpoint(session)
            restore_pending_interruption(session)
            waiting = self._set_state(
                session,
                status="awaiting_user",
                recovery_id=recovery_id,
                attempts=0,
                reason="checkpoint_unknown",
                can_continue=False,
            )
            await self._save_session(session)
            await self._publish(chat_id, waiting)
            return
        if checkpoint is not None and not _runtime_checkpoint_is_well_formed(checkpoint):
            _discard_runtime_checkpoint(session)
            restore_pending_interruption(session)
            waiting = self._set_state(
                session,
                status="awaiting_user",
                recovery_id=recovery_id,
                attempts=0,
                reason="checkpoint_invalid",
                can_continue=False,
            )
            await self._save_session(session)
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
            await self._save_session(session)
            await self._publish(chat_id, recovered)
            return
        if phase in _UNCERTAIN_TOOL_PHASES or pending_calls:
            restore_runtime_checkpoint(session)
            waiting = self._set_state(
                session,
                status="awaiting_user",
                recovery_id=recovery_id,
                attempts=0,
                reason="tool_state_unknown",
            )
            await self._save_session(session)
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
        await self._save_session(session)
        await self._publish(chat_id, waiting)

    async def _queue_continuation(
        self,
        session: Session,
        chat_id: str,
        state: Mapping[str, Any],
    ) -> None:
        recovery_id = cast(str, state["recovery_id"])
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
