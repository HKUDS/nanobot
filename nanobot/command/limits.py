"""Deterministic owner-only Codex quota readout."""

from __future__ import annotations

from nanobot.bus.events import OutboundMessage
from nanobot.command.router import CommandContext


async def cmd_limits(ctx: CommandContext) -> OutboundMessage:
    from nanobot.agent.tools.codex_limits import CodexLimitsTool
    from nanobot.operations.codex_limits import limits_report

    tool = ctx.loop.tools.get("codex_limits")
    if not isinstance(tool, CodexLimitsTool) or tool.monitor.config.owner_session_key != ctx.key:
        content = "Podgląd limitów Codex jest niedostępny w tej rozmowie."
    else:
        content = limits_report(await tool.monitor.snapshot())
    return OutboundMessage(channel=ctx.msg.channel, chat_id=ctx.msg.chat_id, content=content,
                           metadata={**dict(ctx.msg.metadata or {}), "render_as": "text"})
