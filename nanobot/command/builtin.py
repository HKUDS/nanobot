"""Built-in slash command handlers."""

from __future__ import annotations

import asyncio
import os
import sys

from nanobot import __version__
from nanobot.bus.events import OutboundMessage
from nanobot.command.router import CommandContext, CommandRouter
from nanobot.utils.helpers import build_status_content


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
    running_session = loop.subagents.get_running_count_for_session(ctx.key)
    running_total = loop.subagents.get_running_count()
    running_labels = loop.subagents.list_running_for_session(ctx.key, limit=3)
    session_usage = session.metadata.get("usage", {}) if isinstance(session.metadata, dict) else {}
    return OutboundMessage(
        channel=ctx.msg.channel,
        chat_id=ctx.msg.chat_id,
        content=build_status_content(
            version=__version__, model=loop.model,
            start_time=loop._start_time, last_usage=loop._last_usage,
            context_window_tokens=loop.context_window_tokens,
            session_msg_count=len(session.get_history(max_messages=0)),
            context_tokens_estimate=ctx_est,
            running_subagents=running_session,
            total_running_subagents=running_total,
            running_subagent_labels=running_labels,
            session_usage=session_usage,
        ),
        metadata={"render_as": "text"},
    )


async def cmd_new(ctx: CommandContext) -> OutboundMessage:
    """Start a fresh session."""
    loop = ctx.loop
    session = ctx.session or loop.sessions.get_or_create(ctx.key)
    snapshot = session.messages[session.last_consolidated:]
    session.clear()
    loop.sessions.save(session)
    loop.sessions.invalidate(session.key)
    if snapshot:
        loop._schedule_background(loop.memory_consolidator.archive_messages(snapshot))
    return OutboundMessage(
        channel=ctx.msg.channel, chat_id=ctx.msg.chat_id,
        content="New session started.",
    )


async def cmd_help(ctx: CommandContext) -> OutboundMessage:
    """Return available slash commands."""
    return OutboundMessage(
        channel=ctx.msg.channel,
        chat_id=ctx.msg.chat_id,
        content=build_help_text(),
        metadata={"render_as": "text"},
    )


async def cmd_tasks(ctx: CommandContext) -> OutboundMessage:
    """List running subagent tasks for the current chat/session."""
    running = ctx.loop.subagents.list_running_for_session(ctx.key, limit=10)
    if not running:
        content = "No active subagent tasks in this chat."
    else:
        lines = ["Active subagent tasks:"]
        lines.extend(f"- {item}" for item in running)
        content = "\n".join(lines)
    return OutboundMessage(channel=ctx.msg.channel, chat_id=ctx.msg.chat_id, content=content)


async def cmd_task(ctx: CommandContext) -> OutboundMessage:
    """Show status for one subagent task id in this chat/session."""
    task_id = (ctx.args or "").strip()
    if not task_id:
        content = "Usage: /task <task_id>"
    else:
        info = ctx.loop.subagents.get_task_info_for_session(ctx.key, task_id)
        if info is None:
            content = f"Task '{task_id}' not found in this chat."
        else:
            content = (
                f"Task '{task_id}'\n"
                f"- label: {info['label']}\n"
                f"- status: {info['status']}"
            )
    return OutboundMessage(channel=ctx.msg.channel, chat_id=ctx.msg.chat_id, content=content)


async def cmd_task_stop(ctx: CommandContext) -> OutboundMessage:
    """Stop one running subagent task by id."""
    task_id = (ctx.args or "").strip()
    if not task_id:
        content = "Usage: /taskstop <task_id>"
    else:
        stopped = await ctx.loop.subagents.stop_task_for_session(ctx.key, task_id)
        content = (
            f"Task '{task_id}' stopped."
            if stopped
            else f"Task '{task_id}' is not running or not found in this chat."
        )
    return OutboundMessage(channel=ctx.msg.channel, chat_id=ctx.msg.chat_id, content=content)


async def cmd_task_label(ctx: CommandContext) -> OutboundMessage:
    """Update one task label by id."""
    raw = (ctx.args or "").strip()
    if not raw:
        content = "Usage: /tasklabel <task_id> <new_label>"
    else:
        parts = raw.split(maxsplit=1)
        if len(parts) < 2:
            content = "Usage: /tasklabel <task_id> <new_label>"
        else:
            task_id, label = parts[0], parts[1]
            updated = ctx.loop.subagents.update_task_label_for_session(ctx.key, task_id, label)
            content = (
                f"Task '{task_id}' label updated to: {label}"
                if updated
                else f"Task '{task_id}' not found in this chat."
            )
    return OutboundMessage(channel=ctx.msg.channel, chat_id=ctx.msg.chat_id, content=content)


def build_help_text() -> str:
    """Build canonical help text shared across channels."""
    lines = [
        "🐈 nanobot commands:",
        "/new — Start a new conversation",
        "/stop — Stop the current task",
        "/restart — Restart the bot",
        "/status — Show bot status",
        "/tasks — List active background tasks",
        "/task <id> — Show one background task status",
        "/taskstop <id> — Stop one background task",
        "/tasklabel <id> <label> — Rename a background task",
        "/help — Show available commands",
    ]
    return "\n".join(lines)


def register_builtin_commands(router: CommandRouter) -> None:
    """Register the default set of slash commands."""
    router.priority("/stop", cmd_stop)
    router.priority("/restart", cmd_restart)
    router.priority("/status", cmd_status)
    router.exact("/new", cmd_new)
    router.exact("/status", cmd_status)
    router.exact("/tasks", cmd_tasks)
    router.exact("/help", cmd_help)
    router.prefix("/task ", cmd_task)
    router.prefix("/taskstop ", cmd_task_stop)
    router.prefix("/tasklabel ", cmd_task_label)
