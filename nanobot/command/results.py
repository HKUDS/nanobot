"""Slash-command receipts: named facts for clients and readable text for IM."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.bus.outbound_events import CommandLine, CommandPart, CommandResultEvent, LiteralLine
from nanobot.command_copy import command_text


def line(key: str, **values: str | int | float) -> CommandLine:
    return {"key": key, "values": values}


def render(parts: tuple[CommandPart, ...], locale: object = None) -> str:
    def translate(part: CommandPart) -> str:
        if "text" in part:
            return part["text"]
        return part.get("prefix", "") + command_text(part["key"], locale, **part["values"])

    return "\n".join(translate(part) for part in parts)


def message_text(msg: OutboundMessage) -> str:
    """Plain-text projection for text channels, direct calls and the session log."""
    if isinstance(msg.event, CommandResultEvent):
        return render(msg.event.parts, msg.metadata.get("locale"))
    return msg.content


def as_text_message(msg: OutboundMessage) -> OutboundMessage:
    if not isinstance(msg.event, CommandResultEvent):
        return msg
    # Preserve literal command syntax and diagnostics on Markdown-capable text channels.
    literal = msg.event.command in {
        "/help", "/__shell", "/status", "/model", "/goal", "/cancel_goal", "/dream-prompt",
        "/evaluator-prompt", "/dream-log", "/dream-restore", "/trigger",
    } or any(p.get("key") in {"invalid.command", "invalid.args", "dream.no_input"} for p in msg.event.parts)
    metadata = {**msg.metadata, "render_as": "text"} if literal else msg.metadata
    return replace(msg, content=message_text(msg), metadata=metadata)


def command_reply(
    msg: InboundMessage, command: str, *parts: CommandLine | str,
    metadata: dict[str, Any] | None = None, notification_id: str | None = None,
) -> OutboundMessage:
    return command_result(
        msg.channel, msg.chat_id, command, *parts,
        metadata={**msg.metadata, **(metadata or {})}, notification_id=notification_id,
    )


def command_result(
    channel: str, chat_id: str, command: str, *parts: CommandLine | str,
    metadata: dict[str, Any], notification_id: str | None = None,
) -> OutboundMessage:
    structured = tuple(LiteralLine(text=p) if isinstance(p, str) else p for p in parts)
    return OutboundMessage(
        channel=channel, chat_id=chat_id, content="",
        metadata=metadata,
        event=CommandResultEvent(command=command, parts=structured, notification_id=notification_id),
    )
