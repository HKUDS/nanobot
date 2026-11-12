"""Admission identity and metadata shared by normal commits and checkpoint recovery."""

from __future__ import annotations

from typing import Any, cast

from nanobot.bus.events import INBOUND_META_LOCAL_MEDIA, INBOUND_META_TURN_ID, InboundMessage
from nanobot.runtime_context import RUNTIME_CONTEXT_HISTORY_META, RUNTIME_CONTEXT_MESSAGE_META
from nanobot.session.session_messages import session_message_input, session_message_public_metadata


def input_history_metadata(message: InboundMessage) -> dict[str, Any]:
    # None marks an input without a public ID; synthetic continuations omit the key.
    extra: dict[str, Any] = {"timestamp": message.timestamp.isoformat(), "input_id": None}
    envelope = session_message_input(message)
    if envelope is not None:
        extra["session_message"] = session_message_public_metadata(envelope)
        extra["input_id"] = f"session-message:{envelope['message_id']}"
    turn_id = message.metadata.get(INBOUND_META_TURN_ID)
    if isinstance(turn_id, str) and turn_id:
        extra[INBOUND_META_TURN_ID] = turn_id
        if message.is_user_input and envelope is None:
            extra["input_id"] = f"user:{turn_id}"
    local_media = message.metadata.get(INBOUND_META_LOCAL_MEDIA)
    if isinstance(local_media, list) and local_media:
        extra[INBOUND_META_LOCAL_MEDIA] = [path for path in cast(list[object], local_media) if isinstance(path, str)]
    return extra


def persisted_message(message: dict[str, Any]) -> dict[str, Any]:
    """Move internal transcript annotations to their durable history fields."""
    entry = dict(message)
    metadata = entry.pop("_meta", None)
    if not isinstance(metadata, dict):
        return entry
    metadata = cast(dict[str, Any], metadata)
    if entry.get("role") == "user":
        if "input_id" in metadata:
            entry["input_id"] = metadata["input_id"]
        for key in ("timestamp", INBOUND_META_TURN_ID):
            if isinstance(value := metadata.get(key), str) and value:
                entry[key] = value
        if isinstance(source := metadata.get("session_message"), dict):
            entry["session_message"] = source
        if isinstance(context := metadata.get(RUNTIME_CONTEXT_MESSAGE_META), dict):
            entry[RUNTIME_CONTEXT_HISTORY_META] = context
    elif entry.get("role") == "assistant" and "response_input_ids" in metadata:
        entry["response_input_ids"] = metadata["response_input_ids"]
    return entry
