"""Deterministic development controls; no model call needed for status or pause."""

from __future__ import annotations

from filelock import Timeout

from nanobot.agent.tools.development import DevelopmentTool
from nanobot.bus.events import OutboundMessage
from nanobot.command.router import CommandContext


async def cmd_development(ctx: CommandContext) -> OutboundMessage:
    tool = ctx.loop.tools.get("development")
    try:
        if not isinstance(tool, DevelopmentTool):
            raise ValueError("Projekt rozwoju nie jest włączony w tym gatewayu.")
        tool.service.authorize(ctx.key)
        if not ctx.is_user_turn:
            raise ValueError("Sterowanie rozwojem wymaga polecenia właściciela.")
        args = (ctx.args.strip() or ctx.raw.partition(" ")[2]).split()
        action = args[0].lower() if args else "status"
        aliases = {"wznów": "continue", "wznow": "continue", "kontynuuj": "continue",
                   "pauza": "pause", "wstrzymaj": "pause", "anuluj": "cancel"}
        action = aliases.get(action, action)
        if len(args) > 2:
            raise ValueError("Użyj: /development [status|continue|pause|start|cancel] [ID].")
        content = tool.service.control(action, args[1] if len(args) == 2 else None)
    except (ValueError, OSError, Timeout) as exc:
        content = str(exc)
    return OutboundMessage(channel=ctx.msg.channel, chat_id=ctx.msg.chat_id, content=content,
                           metadata={**dict(ctx.msg.metadata or {}), "render_as": "text"})
