"""Runtime delivery helpers for completed subagent task results."""

from __future__ import annotations

import dataclasses
from typing import Any

from nanobot.bus.events import InboundMessage
from nanobot.session import turn_continuation

_FORWARDED_METADATA_KEYS = frozenset({
    "message_id",
    "origin_message_id",
    "_wants_stream",
    "webui",
    "slack",
})


def build_subagent_result_continuation(result: Any) -> InboundMessage:
    """Build an internal inbound wake-up for a ready subagent result."""
    metadata = dict(result.metadata or {})
    channel = str(metadata.get("origin_channel") or "")
    chat_id = str(metadata.get("origin_chat_id") or "")
    if not channel or not chat_id:
        channel, chat_id = _channel_chat_from_session_key(result.session_key)

    wake_meta = turn_continuation.subagent_result_continuation_metadata(
        {key: value for key, value in metadata.items() if key in _FORWARDED_METADATA_KEYS},
        task_id=result.task_id,
    )
    return InboundMessage(
        channel=channel,
        sender_id="system:continuation",
        chat_id=chat_id,
        content=(
            "A subagent task result is ready. The runtime will attach the "
            "result to this continuation turn."
        ),
        metadata=wake_meta,
        session_key_override=result.session_key,
    )


async def materialize_subagent_result_continuation(
    msg: InboundMessage,
    *,
    session_key: str,
    subagents: Any,
) -> InboundMessage:
    """Replace a subagent-result continuation placeholder with the mailbox result."""
    task_id = turn_continuation.subagent_result_continuation_task_id(msg.metadata)
    if not task_id:
        return msg
    read = await subagents.wait_for_result(
        session_key,
        task_id=task_id,
        timeout_seconds=0,
    )
    return dataclasses.replace(msg, content=_subagent_result_continuation_content(read, task_id))


def _channel_chat_from_session_key(session_key: str) -> tuple[str, str]:
    channel, _, chat_id = session_key.partition(":")
    return channel or "cli", chat_id or "direct"


def _subagent_result_continuation_content(read: Any, requested_task_id: str) -> str:
    if read.state == "ready" and read.result is not None:
        status_text = {
            "ok": "completed",
            "error": "failed",
            "cancelled": "cancelled",
        }.get(read.result.status, read.result.status)
        return (
            "A subagent result was delivered by the runtime. Use this result "
            "as authoritative context for the next answer; do not mention the "
            "internal continuation boundary.\n\n"
            f"Subagent [{read.result.label}] "
            f"(id: {read.result.task_id}, status: {status_text})\n\n"
            f"Task:\n{read.result.task}\n\n"
            f"Result:\n{read.result.content}"
        )
    if read.state == "consumed":
        return (
            f"Subagent task {requested_task_id} already has a consumed result. "
            "Check poll_subagents if you need its current status."
        )
    if read.state == "running":
        return (
            f"Subagent task {requested_task_id} is still running. "
            "Use poll_subagents or wait_subagents if you need to block."
        )
    return f"Subagent task {requested_task_id} result is not available ({read.state})."
