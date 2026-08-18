"""Bounded delivery of messages between persisted sessions."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any, TypedDict, cast

from nanobot.bus.events import InboundMessage
from nanobot.session.session_handles import (
    normalize_session_handle as normalize_stored_session_handle,
)

SESSION_MESSAGE_METADATA_KEY = "_session_message"
SESSION_REPLY_TIMEOUT_METADATA_KEY = "_session_reply_timeout"
SESSION_MESSAGE_SENDER_ID = "session"
SESSION_REPLY_TIMEOUT_SENDER_ID = "session_timeout"

MIN_REPLY_TIMEOUT_SECONDS = 5
MAX_REPLY_TIMEOUT_SECONDS = 60

_MAX_SESSION_KEY_CHARS = 512
_MESSAGE_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


class SessionMessageEndpoint(TypedDict):
    """One endpoint stored in an internal session-message envelope."""

    name: str
    session_key: str


class SessionMessageSourceEndpoint(SessionMessageEndpoint):
    """Source fields used for WebUI provenance."""

    handle_id: str
    color_slot: int


class SessionMessageEnvelope(TypedDict):
    """Metadata persisted with session-authored user input."""

    message_id: str
    created_at_ms: int
    expect_reply: bool
    source: SessionMessageSourceEndpoint
    target: SessionMessageEndpoint


class SessionReplyTimeoutEnvelope(SessionMessageEnvelope):
    """Trusted metadata for resuming a session after a session reply deadline."""

    timeout_seconds: int


class SessionMessageError(ValueError):
    """A session message was rejected before reaching the inbound bus."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def normalize_session_handle(value: str) -> str:
    """Return the canonical bare session handle accepted by the directory."""
    try:
        return normalize_stored_session_handle(value)
    except ValueError as exc:
        raise SessionMessageError("invalid_name", str(exc)) from exc


def session_message_envelope(
    metadata: Mapping[str, Any] | None,
) -> SessionMessageEnvelope | None:
    """Validate and normalize a session envelope from an inbound metadata boundary."""
    if not isinstance(metadata, Mapping):
        return None
    raw = metadata.get(SESSION_MESSAGE_METADATA_KEY)
    if not isinstance(raw, Mapping):
        return None
    data = cast(Mapping[str, object], raw)

    message_id = _bounded_id(data.get("message_id"))
    created_at_ms = data.get("created_at_ms")
    expect_reply = data.get("expect_reply")
    source = _session_source_endpoint(data.get("source"))
    target = _session_endpoint(data.get("target"))
    if (
        message_id is None
        or not isinstance(created_at_ms, int)
        or isinstance(created_at_ms, bool)
        or created_at_ms < 0
        or not isinstance(expect_reply, bool)
        or source is None
        or target is None
    ):
        return None
    return {
        "message_id": message_id,
        "created_at_ms": created_at_ms,
        "expect_reply": expect_reply,
        "source": source,
        "target": target,
    }


def session_reply_timeout_envelope(
    metadata: Mapping[str, Any] | None,
) -> SessionReplyTimeoutEnvelope | None:
    """Validate and normalize a session reply-timeout envelope."""
    if not isinstance(metadata, Mapping):
        return None
    raw = metadata.get(SESSION_REPLY_TIMEOUT_METADATA_KEY)
    if not isinstance(raw, Mapping):
        return None
    data = cast(Mapping[str, object], raw)
    request = session_message_envelope({SESSION_MESSAGE_METADATA_KEY: data})
    timeout_seconds = data.get("timeout_seconds")
    if (
        request is None
        or not request["expect_reply"]
        or not isinstance(timeout_seconds, int)
        or isinstance(timeout_seconds, bool)
        or not MIN_REPLY_TIMEOUT_SECONDS <= timeout_seconds <= MAX_REPLY_TIMEOUT_SECONDS
    ):
        return None
    return {
        **request,
        "timeout_seconds": timeout_seconds,
    }


def session_message_inbound(msg: InboundMessage) -> SessionMessageEnvelope | None:
    """Return a session envelope only for the internal delivery shape we mint.

    Metadata alone is not provenance: channel adapters may carry client-provided
    metadata. Requiring the complete internal shape prevents forged session input.
    """
    if (
        msg.sender_id != SESSION_MESSAGE_SENDER_ID
        or msg.session_key_override is None
    ):
        return None
    envelope = session_message_envelope(msg.metadata)
    if envelope is None:
        return None
    target_key = envelope["target"]["session_key"]
    raw_route = msg.channel == "system" and msg.chat_id == target_key
    user_route = msg.channel == "websocket" and f"websocket:{msg.chat_id}" == target_key
    if msg.session_key_override != target_key or not (raw_route or user_route):
        return None
    return envelope


def session_reply_timeout_inbound(
    msg: InboundMessage,
) -> SessionReplyTimeoutEnvelope | None:
    """Return a timeout envelope only for the internal delivery shape we mint."""
    if (
        msg.sender_id != SESSION_REPLY_TIMEOUT_SENDER_ID
        or msg.session_key_override is None
    ):
        return None
    envelope = session_reply_timeout_envelope(msg.metadata)
    if envelope is None:
        return None
    waiter_key = envelope["source"]["session_key"]
    raw_route = msg.channel == "system" and msg.chat_id == waiter_key
    user_route = msg.channel == "websocket" and f"websocket:{msg.chat_id}" == waiter_key
    if msg.session_key_override != waiter_key or not (raw_route or user_route):
        return None
    return envelope


def is_session_input(msg: InboundMessage) -> bool:
    """Return whether *msg* is a server-minted session input."""
    return (
        session_message_inbound(msg) is not None
        or session_reply_timeout_inbound(msg) is not None
    )


def session_input_history_extra(msg: InboundMessage) -> dict[str, Any]:
    """Return private history metadata for one validated session input."""
    envelope = session_message_inbound(msg)
    if envelope is not None:
        return {SESSION_MESSAGE_METADATA_KEY: envelope}
    timeout = session_reply_timeout_inbound(msg)
    return {SESSION_REPLY_TIMEOUT_METADATA_KEY: timeout} if timeout is not None else {}


def session_message_public_metadata(envelope: SessionMessageEnvelope) -> dict[str, Any]:
    """Return public provenance without internal routing identifiers."""
    source = envelope["source"]
    return {
        "direction": "incoming",
        "message_id": envelope["message_id"],
        "session": {
            "id": source["handle_id"],
            "name": source["name"],
            "color_slot": source["color_slot"],
        },
    }


def _bounded_id(value: object) -> str | None:
    return value if isinstance(value, str) and _MESSAGE_ID_RE.fullmatch(value) else None


def _session_endpoint(value: object) -> SessionMessageEndpoint | None:
    if not isinstance(value, Mapping):
        return None
    data = cast(Mapping[str, object], value)
    raw_name = data.get("name")
    raw_key = data.get("session_key")
    if not isinstance(raw_name, str) or not isinstance(raw_key, str):
        return None
    try:
        name = normalize_session_handle(raw_name)
    except SessionMessageError:
        return None
    session_key = raw_key.strip()
    if not session_key or len(session_key) > _MAX_SESSION_KEY_CHARS:
        return None
    return {
        "name": name,
        "session_key": session_key,
    }


def _session_source_endpoint(value: object) -> SessionMessageSourceEndpoint | None:
    endpoint = _session_endpoint(value)
    if endpoint is None:
        return None
    data = cast(Mapping[str, object], value)
    handle_id = data.get("handle_id")
    color_slot = data.get("color_slot")
    if (
        not isinstance(handle_id, str)
        or _MESSAGE_ID_RE.fullmatch(handle_id) is None
        or not isinstance(color_slot, int)
        or isinstance(color_slot, bool)
        or not 0 <= color_slot < 8
    ):
        return None
    return {
        **endpoint,
        "handle_id": handle_id,
        "color_slot": color_slot,
    }


def is_persisted_webui_session(
    session_key: str,
    payload: Mapping[str, Any],
) -> bool:
    """Return whether *payload* is a persisted WebUI conversation."""
    raw_metadata = cast(object, payload.get("metadata"))
    if not session_key.startswith("websocket:") or not isinstance(raw_metadata, Mapping):
        return False
    metadata = cast(Mapping[str, object], raw_metadata)
    return metadata.get("webui") is True
