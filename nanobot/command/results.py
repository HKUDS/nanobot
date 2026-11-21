"""Slash-command receipts: named facts for clients and readable text for IM."""

from __future__ import annotations

from typing import Any

from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.bus.outbound_events import CommandLine, CommandPart, CommandResultEvent, LiteralLine
from nanobot.command_copy import command_text


def line(key: str, **values: str | int | float) -> CommandLine:
    return {"key": key, "values": values}


def render(parts: tuple[CommandPart, ...], locale: object = None) -> str:
    def translate(part: CommandPart) -> str:
        return part["text"] if "text" in part else command_text(part["key"], locale, **part["values"])

    return "\n".join(translate(part) for part in parts)


def command_reply(
    msg: InboundMessage, command: str, *parts: CommandLine | str,
    metadata: dict[str, Any] | None = None, notification_id: str | None = None,
) -> OutboundMessage:
    structured = tuple(LiteralLine(text=p) if isinstance(p, str) else p for p in parts)
    return OutboundMessage(
        channel=msg.channel, chat_id=msg.chat_id, content=render(structured, msg.metadata.get("locale")),
        metadata={**msg.metadata, **(metadata or {})},
        event=CommandResultEvent(command=command, parts=structured, notification_id=notification_id),
    )
