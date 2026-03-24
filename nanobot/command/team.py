"""Team-mode slash command handlers for the CommandRouter."""

from __future__ import annotations

from nanobot.bus.events import OutboundMessage
from nanobot.command.router import CommandContext, CommandRouter

_TEAM_USAGE = (
    "Usage:\n"
    "/team <goal>\n"
    "/team status\n"
    "/team log [n]\n"
    "/team approve <task_id>\n"
    "/team reject <task_id> <reason>\n"
    "/team manual <task_id> <instruction>\n"
    "/team stop"
)


async def cmd_team_exact(ctx: CommandContext) -> OutboundMessage:
    """Bare /team with no arguments — show usage."""
    return OutboundMessage(
        channel=ctx.msg.channel, chat_id=ctx.msg.chat_id, content=_TEAM_USAGE,
    )


async def cmd_team_prefix(ctx: CommandContext) -> OutboundMessage | None:
    """Dispatch /team <sub>."""
    loop = ctx.loop
    session = ctx.session or loop.sessions.get_or_create(ctx.key)

    instruction = ctx.args.strip()
    parts = instruction.split(maxsplit=2)
    lowered = (parts[0] if parts else "").lower()

    if lowered == "status":
        content = loop.team.status_text(ctx.key)
        session.metadata["nano_team_active"] = bool(loop.team.has_unfinished_run(ctx.key))
        loop.sessions.save(session)
        return OutboundMessage(
            channel=ctx.msg.channel, chat_id=ctx.msg.chat_id,
            content=content, metadata={"team_text": True},
        )

    if lowered == "log":
        n = 20
        if len(parts) > 1:
            try:
                n = max(1, min(200, int(parts[1])))
            except (TypeError, ValueError):
                n = 20
        return OutboundMessage(
            channel=ctx.msg.channel, chat_id=ctx.msg.chat_id,
            content=loop.team.log_text(ctx.key, n=n), metadata={"team_text": True},
        )

    if lowered == "stop":
        with_snapshot = ctx.msg.channel == "cli"
        content = await loop.team.stop_mode(ctx.key, with_snapshot=with_snapshot)
        session.metadata.pop("nano_team_active", None)
        loop.sessions.save(session)
        return OutboundMessage(
            channel=ctx.msg.channel, chat_id=ctx.msg.chat_id,
            content=content, metadata={"team_text": True},
        )

    if lowered == "approve":
        task_id = parts[1] if len(parts) > 1 else ""
        if not task_id:
            return OutboundMessage(
                channel=ctx.msg.channel, chat_id=ctx.msg.chat_id,
                content="Usage: /team approve <task_id>",
            )
        return OutboundMessage(
            channel=ctx.msg.channel, chat_id=ctx.msg.chat_id,
            content=loop.team.approve_for_session(ctx.key, task_id),
            metadata={"team_text": True},
        )

    if lowered == "reject":
        task_id = parts[1] if len(parts) > 1 else ""
        reason = parts[2] if len(parts) > 2 else ""
        if not task_id or not reason.strip():
            return OutboundMessage(
                channel=ctx.msg.channel, chat_id=ctx.msg.chat_id,
                content="Usage: /team reject <task_id> <reason>",
            )
        return OutboundMessage(
            channel=ctx.msg.channel, chat_id=ctx.msg.chat_id,
            content=loop.team.reject_for_session(ctx.key, task_id, reason.strip()),
            metadata={"team_text": True},
        )

    if lowered == "manual":
        task_id = parts[1] if len(parts) > 1 else ""
        instruction_text = parts[2] if len(parts) > 2 else ""
        if not task_id or not instruction_text.strip():
            return OutboundMessage(
                channel=ctx.msg.channel, chat_id=ctx.msg.chat_id,
                content="Usage: /team manual <task_id> <instruction>",
            )
        return OutboundMessage(
            channel=ctx.msg.channel, chat_id=ctx.msg.chat_id,
            content=loop.team.request_changes_for_session(
                ctx.key, task_id, instruction_text.strip(),
            ),
            metadata={"team_text": True},
        )

    content = await loop.team.start_or_route_goal(ctx.key, instruction)
    session.metadata["nano_team_active"] = loop.team.is_active(ctx.key)
    loop.sessions.save(session)
    return OutboundMessage(
        channel=ctx.msg.channel, chat_id=ctx.msg.chat_id,
        content=content, metadata={"team_text": True},
    )


async def team_active_interceptor(ctx: CommandContext) -> OutboundMessage | None:
    """Block normal messages when team mode is active."""
    loop = ctx.loop
    session = ctx.session or loop.sessions.get_or_create(ctx.key)
    if not session.metadata.get("nano_team_active"):
        return None

    if not loop.team.is_active(ctx.key):
        session.metadata.pop("nano_team_active", None)
        loop.sessions.save(session)
        return None

    if ctx.msg.channel != "cli" and loop.team.has_pending_approval(ctx.key):
        approval_reply = loop.team.handle_approval_reply(ctx.key, ctx.raw)
        if approval_reply:
            return OutboundMessage(
                channel=ctx.msg.channel, chat_id=ctx.msg.chat_id,
                content=approval_reply, metadata={"team_text": True},
            )

    return OutboundMessage(
        channel=ctx.msg.channel, chat_id=ctx.msg.chat_id,
        content=(
            "Team mode is active. Supported input:\n"
            "- /team <instruction|status|log|approve|reject|manual|stop>"
        ),
    )


def register_team_commands(router: CommandRouter) -> None:
    """Register all team-mode commands on the given router."""
    router.exact("/team", cmd_team_exact)
    router.prefix("/team ", cmd_team_prefix)
    router.intercept(team_active_interceptor)
