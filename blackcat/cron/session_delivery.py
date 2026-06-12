"""Helpers for routing bound cron turns back through their origin session."""

from __future__ import annotations

from typing import Any


def bound_session_inbound_context(session_key: str) -> tuple[str, str, dict[str, Any]]:
    """Return ``(channel, chat_id, metadata)`` for a bound cron session key."""
    if ":" not in session_key:
        raise ValueError(f"bound cron session_key is invalid: {session_key!r}")
    channel, rest = session_key.split(":", 1)
    if not channel or not rest:
        raise ValueError(f"bound cron session_key is invalid: {session_key!r}")

    metadata: dict[str, Any] = {}

    if channel == "discord" and ":thread:" in rest:
        parent_channel_id, thread_id = rest.split(":thread:", 1)
        if parent_channel_id and thread_id:
            metadata.update({
                "context_chat_id": parent_channel_id,
                "parent_channel_id": parent_channel_id,
                "thread_id": thread_id,
            })
            return channel, thread_id, metadata

    if channel == "feishu" and ":" in rest:
        chat_id, thread_id = rest.split(":", 1)
        if chat_id and thread_id:
            metadata.update({
                "chat_type": "group",
                "message_id": thread_id,
                "thread_id": thread_id,
            })
            return channel, chat_id, metadata

    if channel == "slack" and ":" in rest:
        chat_id, thread_ts = rest.split(":", 1)
        if thread_ts:
            metadata["slack"] = {"thread_ts": thread_ts}
        return channel, chat_id, metadata

    if channel == "telegram" and ":topic:" in rest:
        chat_id, thread_id = rest.split(":topic:", 1)
        if thread_id:
            metadata["message_thread_id"] = (
                int(thread_id) if thread_id.isdigit() else thread_id
            )
        return channel, chat_id, metadata

    if channel == "dingtalk" and rest.startswith("group:"):
        parts = rest.split(":", 2)
        if len(parts) >= 2 and parts[1]:
            return channel, f"group:{parts[1]}", metadata

    return channel, rest, metadata
