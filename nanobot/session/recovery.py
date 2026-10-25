"""Durable session checkpoints and pending-turn recovery state."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any, Protocol, TypedDict, cast
from uuid import uuid4

from loguru import logger

from nanobot.bus.events import InboundMessage
from nanobot.session.manager import Session

RUNTIME_CHECKPOINT_KEY = "runtime_checkpoint"
PENDING_USER_TURN_KEY = "pending_user_turn"
REQUEST_ORIGIN_METADATA_KEY = "request_origin"
RECOVERY_METADATA_KEY = "webui_recovery"
RECOVERY_INBOUND_METADATA_KEY = "_webui_recovery_id"
PENDING_FOLLOWUPS_KEY = "pending_user_followups"
PENDING_FOLLOWUP_ID_KEY = "_recovery_followup_id"
PROVIDER_STATE_CHECKPOINT_VERSION_KEY = "provider_state_checkpoint_version"
PROVIDER_STATE_CHECKPOINT_VERSION = "v1"

_RECOVERY_STATUSES = frozenset({"resuming", "awaiting_user", "recovered", "failed"})
UNCERTAIN_TOOL_PHASES = frozenset({"awaiting_tools"})
KNOWN_CHECKPOINT_PHASES = frozenset(
    {"final_response", "tools_completed", "awaiting_tools", "error"}
)


class RequestOrigin(TypedDict):
    message_id: str | None
    turn_id: str


def request_origin_from_metadata(metadata: Mapping[str, Any]) -> RequestOrigin | None:
    """Read the request identity carried by continuation or recovery metadata."""
    value = metadata.get(REQUEST_ORIGIN_METADATA_KEY)
    if not isinstance(value, dict):
        return None
    origin = cast(dict[str, object], value)
    message_id = origin.get("message_id")
    turn_id = origin.get("turn_id")
    if message_id is not None and not isinstance(message_id, str):
        return None
    if not isinstance(turn_id, str) or not turn_id:
        return None
    return {"message_id": message_id, "turn_id": turn_id}


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
            "timestamp": message.timestamp.isoformat(),
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
        timestamp = record.get("timestamp")
        # Older journals did not retain admission time; retain their existing recovery policy.
        received_at = datetime.fromisoformat(timestamp) if isinstance(timestamp, str) else datetime.now()
        messages.append(
            InboundMessage(
                channel="websocket",
                sender_id=sender_id,
                chat_id=chat_id,
                content=content,
                timestamp=received_at,
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


def runtime_checkpoint_is_well_formed(checkpoint: Mapping[str, Any]) -> bool:
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


def discard_runtime_checkpoint(session: Session) -> bool:
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
    failure_error_kind = state.get("failure_error_kind")
    if isinstance(failure_error_kind, str) and failure_error_kind in {
        "authentication", "billing", "connection", "timeout", "rate_limit", "server", "unknown",
    }:
        payload["failure_error_kind"] = failure_error_kind
    return payload
