"""Built-in slash command handlers."""

from __future__ import annotations

import asyncio
import os
import re
import sys

from nanobot import __version__
from nanobot.bus.events import OutboundMessage
from nanobot.command.router import CommandContext, CommandRouter
from nanobot.utils.helpers import build_status_content

# Pattern to match $skill-name tokens (word chars + hyphens)
_SKILL_REF = re.compile(r"\$([A-Za-z][A-Za-z0-9_-]*)")


async def cmd_stop(ctx: CommandContext) -> OutboundMessage:
    """Cancel all active tasks and subagents for the session."""
    loop = ctx.loop
    msg = ctx.msg
    tasks = loop._active_tasks.pop(msg.session_key, [])
    cancelled = sum(1 for t in tasks if not t.done() and t.cancel())
    for t in tasks:
        try:
            await t
        except (asyncio.CancelledError, Exception):
            pass
    sub_cancelled = await loop.subagents.cancel_by_session(msg.session_key)
    total = cancelled + sub_cancelled
    content = f"Stopped {total} task(s)." if total else "No active task to stop."
    return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id, content=content)


async def cmd_restart(ctx: CommandContext) -> OutboundMessage:
    """Restart the process in-place via os.execv."""
    msg = ctx.msg

    async def _do_restart():
        await asyncio.sleep(1)
        os.execv(sys.executable, [sys.executable, "-m", "nanobot"] + sys.argv[1:])

    asyncio.create_task(_do_restart())
    return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id, content="Restarting...")


async def cmd_status(ctx: CommandContext) -> OutboundMessage:
    """Build an outbound status message for a session."""
    loop = ctx.loop
    session = ctx.session or loop.sessions.get_or_create(ctx.key)
    ctx_est = 0
    try:
        ctx_est, _ = loop.memory_consolidator.estimate_session_prompt_tokens(session)
    except Exception:
        pass
    if ctx_est <= 0:
        ctx_est = loop._last_usage.get("prompt_tokens", 0)
    return OutboundMessage(
        channel=ctx.msg.channel,
        chat_id=ctx.msg.chat_id,
        content=build_status_content(
            version=__version__,
            model=loop.model,
            start_time=loop._start_time,
            last_usage=loop._last_usage,
            context_window_tokens=loop.context_window_tokens,
            session_msg_count=len(session.get_history(max_messages=0)),
            context_tokens_estimate=ctx_est,
        ),
        metadata={"render_as": "text"},
    )


async def cmd_new(ctx: CommandContext) -> OutboundMessage:
    """Start a fresh session."""
    loop = ctx.loop
    session = ctx.session or loop.sessions.get_or_create(ctx.key)
    snapshot = session.messages[session.last_consolidated :]
    session.clear()
    loop.sessions.save(session)
    loop.sessions.invalidate(session.key)
    if snapshot:
        loop._schedule_background(loop.memory_consolidator.archive_messages(snapshot))
    return OutboundMessage(
        channel=ctx.msg.channel,
        chat_id=ctx.msg.chat_id,
        content="New session started.",
    )


async def cmd_skill_list(ctx: CommandContext) -> OutboundMessage:
    """List all available skills."""
    loader = ctx.loop.context.skills
    skills = loader.list_skills(filter_unavailable=False)
    if not skills:
        return OutboundMessage(
            channel=ctx.msg.channel,
            chat_id=ctx.msg.chat_id,
            content="No skills found.",
        )
    lines = ["Available skills (use $<name> to activate):"]
    for s in skills:
        desc = loader._get_skill_description(s["name"])
        available = loader._check_requirements(loader._get_skill_meta(s["name"]))
        mark = "✓" if available else "✗"
        lines.append(f"  {mark} {s['name']} — {desc}")
    return OutboundMessage(
        channel=ctx.msg.channel,
        chat_id=ctx.msg.chat_id,
        content="\n".join(lines),
        metadata={"render_as": "text"},
    )


async def intercept_skill_refs(ctx: CommandContext) -> OutboundMessage | None:
    """Scan message for $skill-name references and inject matching skills."""
    refs = _SKILL_REF.findall(ctx.msg.content)
    if not refs:
        return None
    loader = ctx.loop.context.skills
    skill_names = {s["name"] for s in loader.list_skills(filter_unavailable=True)}
    matched = []
    for name in dict.fromkeys(refs):  # deduplicate, preserve order
        if name in skill_names:
            matched.append(name)
    if not matched:
        return None
    # Strip matched $refs from the message
    message = ctx.msg.content
    for name in matched:
        message = re.sub(rf"\${re.escape(name)}\b", "", message)
    message = message.strip()
    # Build injected content
    skill_blocks = []
    for name in matched:
        content = loader.load_skill(name)
        if content:
            stripped = loader._strip_frontmatter(content)
            skill_blocks.append(f'<skill-content name="{name}">\n{stripped}\n</skill-content>')
    if not skill_blocks:
        return None
    names = ", ".join(f"'{n}'" for n in matched)
    injected = (
        f"<system-reminder>\n"
        f"The user activated skill(s) {names} via $-reference. "
        f"The following skill content was auto-appended by the system.\n"
        + "\n".join(skill_blocks)
        + "\n</system-reminder>"
    )
    ctx.msg.content = f"{injected}\n\n{message}" if message else injected
    return None  # fall through to LLM


async def cmd_help(ctx: CommandContext) -> OutboundMessage:
    """Return available slash commands."""
    lines = [
        "🐈 nanobot commands:",
        "/new — Start a new conversation",
        "/stop — Stop the current task",
        "/restart — Restart the bot",
        "/status — Show bot status",
        "/skills — List available skills",
        "$<name> — Activate a skill inline (e.g. $weather what's the forecast)",
        "/help — Show available commands",
    ]
    return OutboundMessage(
        channel=ctx.msg.channel,
        chat_id=ctx.msg.chat_id,
        content="\n".join(lines),
        metadata={"render_as": "text"},
    )


def register_builtin_commands(router: CommandRouter) -> None:
    """Register the default set of slash commands."""
    router.priority("/stop", cmd_stop)
    router.priority("/restart", cmd_restart)
    router.priority("/status", cmd_status)
    router.exact("/new", cmd_new)
    router.exact("/status", cmd_status)
    router.exact("/help", cmd_help)
    router.exact("/skills", cmd_skill_list)
    router.intercept(intercept_skill_refs)
