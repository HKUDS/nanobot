"""Built-in slash command handlers."""

from __future__ import annotations

import asyncio
import os
import sys
from typing import TYPE_CHECKING

from nanobot import __version__
from nanobot.command.router import CommandContext, CommandRouter

if TYPE_CHECKING:
    from nanobot.bus.events import OutboundMessage
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
    return ctx.make_response(content)


async def cmd_restart(ctx: CommandContext) -> OutboundMessage:
    """Restart the process in-place via os.execv."""
    msg = ctx.msg

    async def _do_restart():
        await asyncio.sleep(1)
        os.execv(sys.executable, [sys.executable, "-m", "nanobot"] + sys.argv[1:])

    asyncio.create_task(_do_restart())
    return ctx.make_response("Restarting...")


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
    return ctx.make_response(
        build_status_content(
            version=__version__, model=loop.model,
            start_time=loop._start_time, last_usage=loop._last_usage,
            context_window_tokens=loop.context_window_tokens,
            session_msg_count=len(session.get_history(max_messages=0)),
            context_tokens_estimate=ctx_est,
        ),
        metadata={"render_as": "text"},
    )


async def cmd_new(ctx: CommandContext) -> OutboundMessage:
    """Start a fresh session."""
    loop = ctx.loop
    session = ctx.session or (
        loop.sessions.get_or_create_from_layout(ctx.layout) if ctx.layout
        else loop.sessions.get_or_create(ctx.key)
    )
    snapshot = session.messages[session.last_consolidated:]
    if ctx.layout:
        # New layout path: preserve old file, create next sequence
        loop.sessions.new_session(ctx.layout)
    else:
        # Legacy path: clear in-place
        session.clear()
        loop.sessions.save(session)
        loop.sessions.invalidate(session.key)
    if snapshot:
        loop._schedule_background(loop.memory_consolidator.archive_messages(snapshot))
    return ctx.make_response("New session started.")


async def cmd_tts(ctx: CommandContext) -> OutboundMessage:
    """Toggle TTS for the current session."""
    args = ctx.args.strip().lower()
    session = ctx.session or ctx.loop.sessions.get_or_create(ctx.key)

    if args == "on":
        session.metadata["tts"] = True
        ctx.loop.sessions.save(session)
        content = "🔊 TTS enabled for this session."
    elif args == "off":
        session.metadata.pop("tts", None)
        ctx.loop.sessions.save(session)
        content = "🔇 TTS disabled for this session."
    else:
        current = session.metadata.get("tts", False)
        content = f"🔊 TTS is **{'on' if current else 'off'}**. Use `/tts on` or `/tts off` to toggle."

    return ctx.make_response(content)


async def cmd_model(ctx: CommandContext) -> OutboundMessage:
    """切换或查看当前 LLM 模型。"""
    loop = ctx.loop
    args = (ctx.args or "").strip()

    # /model（无参数）→ 显示当前状态
    if not args:
        is_override = loop.model != loop._config_model
        lines = [
            f"🧠 Current model: `{loop.model}`",
            f"📋 Config default: `{loop._config_model}`",
        ]
        if is_override:
            lines.append("⚡ Status: **overridden** (use `reset` to restore)")
        else:
            lines.append("✅ Status: using config default")

        # fallback chain 状态
        from nanobot.providers.fallback import FallbackProvider
        if isinstance(loop._config_provider, FallbackProvider):
            fb_models = [m for _, m in loop._config_provider.fallbacks]
            lines.append(f"🔄 Fallback chain: {' → '.join(fb_models)}")
            if loop._config_provider._in_cooldown():
                lines.append("⚠️ Primary in cooldown — fallback active")

        return ctx.make_response("\n".join(lines))

    # /model reset → 恢复默认
    if args.lower() == "reset":
        model = loop.reset_model()
        return ctx.make_response(f"↩️ Model reset to default: `{model}`")

    # /model <model_name> → 切换
    try:
        model = loop.switch_model(args)
        return ctx.make_response(f"✅ Model switched to: `{model}`")
    except Exception as e:
        return ctx.make_response(f"❌ Failed to switch model: {e}")


async def cmd_dream(ctx: CommandContext) -> OutboundMessage:
    """Manually trigger Dream consolidation."""
    loop = ctx.loop
    if hasattr(loop, 'dream') and loop.dream:
        asyncio.create_task(loop.dream.run_once())
        return ctx.make_response("🌙 Dream consolidation triggered.")
    return ctx.make_response("❌ Dream not available.")


async def cmd_dream_log(ctx: CommandContext) -> OutboundMessage:
    """Show what the last Dream changed."""
    # TODO: Implement dream log retrieval
    return ctx.make_response("🌙 Dream log not yet implemented.")


async def cmd_dream_restore(ctx: CommandContext) -> OutboundMessage:
    """Revert memory to a previous state."""
    # TODO: Implement dream restore
    return ctx.make_response("🌙 Dream restore not yet implemented.")


async def cmd_help(ctx: CommandContext) -> OutboundMessage:
    """Return available slash commands."""
    content = build_help_text()
    return ctx.make_response(content, metadata={"render_as": "text"})


def build_help_text() -> str:
    """Build canonical help text shared across channels."""
    lines = [
        "🐈 nanobot commands:",
        "/new — Start a new conversation",
        "/stop — Stop the current task",
        "/restart — Restart the bot",
        "/status — Show bot status",
        "/dream — Manually trigger Dream consolidation",
        "/dream-log — Show what the last Dream changed",
        "/dream-restore — Revert memory to a previous state",
        "/tts — Toggle text-to-speech (on/off)",
        "/model — View or switch the LLM model",
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
    router.exact("/dream", cmd_dream)
    router.exact("/dream-log", cmd_dream_log)
    router.prefix("/dream-log ", cmd_dream_log)
    router.exact("/dream-restore", cmd_dream_restore)
    router.prefix("/dream-restore ", cmd_dream_restore)
    router.prefix("/tts ", cmd_tts)
    router.exact("/tts", cmd_tts)
    router.prefix("/model ", cmd_model)
    router.exact("/model", cmd_model)
    router.exact("/help", cmd_help)
