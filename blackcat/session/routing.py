"""Persisted session routing context for proactive turns."""

from __future__ import annotations

from typing import Any, Mapping

from blackcat.bus.events import InboundMessage
from blackcat.cron.automation import is_automation_turn
from blackcat.session.manager import Session
from blackcat.session.metadata import SESSION_ROUTING_METADATA_KEY

_ROUTING_METADATA_KEYS = {
    "chat_type",
    "context_chat_id",
    "conversation_type",
    "event_id",
    "message_thread_id",
    "msg_type",
    "parent_channel_id",
    "parent_id",
    "platform",
    "root_id",
    "thread_id",
    "thread_reply_to_event_id",
    "thread_root_event_id",
}
_CHANNEL_ROUTING_METADATA_KEYS = {
    # Feishu needs a message anchor to reply into an existing topic. Other
    # channels should avoid stale reply anchors for scheduled automation turns.
    "feishu": {"message_id"},
}
_SLACK_ROUTING_KEYS = {"channel_type", "thread_ts"}


def _scalar(value: Any) -> str | int | float | bool | None:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return None


def _routing_metadata(channel: str, metadata: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(metadata, Mapping):
        return {}

    out: dict[str, Any] = {}
    keys = _ROUTING_METADATA_KEYS | _CHANNEL_ROUTING_METADATA_KEYS.get(channel, set())
    for key in keys:
        if key not in metadata:
            continue
        value = _scalar(metadata.get(key))
        if value is not None:
            out[key] = value

    slack = metadata.get("slack")
    if isinstance(slack, Mapping):
        slack_out = {
            key: value
            for key in _SLACK_ROUTING_KEYS
            if (value := _scalar(slack.get(key))) is not None
        }
        if slack_out:
            out["slack"] = slack_out

    return out


def routing_context_for_message(msg: InboundMessage) -> dict[str, Any]:
    """Return the stable routing context needed to deliver future session turns."""
    return {
        "channel": msg.channel,
        "chat_id": msg.chat_id,
        "metadata": _routing_metadata(msg.channel, msg.metadata),
    }


def persist_routing_context(session: Session, msg: InboundMessage) -> bool:
    """Persist the latest non-automation delivery context for a session."""
    if is_automation_turn(msg.metadata):
        return False
    context = routing_context_for_message(msg)
    if session.metadata.get(SESSION_ROUTING_METADATA_KEY) == context:
        return False
    session.metadata[SESSION_ROUTING_METADATA_KEY] = context
    return True


def read_routing_context(metadata: Mapping[str, Any] | None) -> tuple[str, str, dict[str, Any]] | None:
    """Decode a persisted routing context from session metadata."""
    if not isinstance(metadata, Mapping):
        return None
    raw = metadata.get(SESSION_ROUTING_METADATA_KEY)
    if not isinstance(raw, Mapping):
        return None

    channel = raw.get("channel")
    chat_id = raw.get("chat_id")
    if not isinstance(channel, str) or not channel:
        return None
    if not isinstance(chat_id, str) or not chat_id:
        return None

    route_meta = raw.get("metadata")
    metadata_out = dict(route_meta) if isinstance(route_meta, Mapping) else {}
    return channel, chat_id, metadata_out
