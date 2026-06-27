"""Built-in slash command handlers."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import time
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from nanobot import __version__
from nanobot.bus.events import OutboundMessage
from nanobot.command.router import CommandContext, CommandRouter
from nanobot.security.workspace_access import (
    WORKSPACE_SCOPE_METADATA_KEY,
    WorkspaceScope,
    WorkspaceScopeError,
    validate_workspace_scope_payload,
)
from nanobot.utils.helpers import build_status_content
from nanobot.utils.restart import set_restart_notice_to_env


@dataclass(frozen=True)
class BuiltinCommandSpec:
    command: str
    title: str
    description: str
    icon: str
    arg_hint: str = ""
    category: str | None = None
    danger: bool = False
    status_provider: str | None = None

    def as_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "command": self.command,
            "title": self.title,
            "description": self.description,
            "icon": self.icon,
            "arg_hint": self.arg_hint,
        }
        if self.category is not None:
            data["category"] = self.category
        if self.danger:
            data["danger"] = True
        if self.status_provider is not None:
            data["status_provider"] = self.status_provider
        return data


BUILTIN_COMMAND_SPECS: tuple[BuiltinCommandSpec, ...] = (
    BuiltinCommandSpec(
        "/new",
        "New chat",
        "Stop the current task and start a fresh conversation.",
        "square-pen",
    ),
    BuiltinCommandSpec(
        "/stop",
        "Stop current task",
        "Cancel the active agent turn for this chat.",
        "square",
    ),
    BuiltinCommandSpec(
        "/restart",
        "Restart nanobot",
        "Restart the bot process in place.",
        "rotate-cw",
    ),
    BuiltinCommandSpec(
        "/status",
        "Show status",
        "Display runtime, provider, and channel status.",
        "activity",
    ),
    BuiltinCommandSpec(
        "/model",
        "Switch model preset",
        "Show or switch the active model preset.",
        "brain",
        "[preset]",
    ),
    BuiltinCommandSpec(
        "/history",
        "Show conversation history",
        "Print the last N persisted conversation messages.",
        "history",
        "[n]",
    ),
    BuiltinCommandSpec(
        "/sessions",
        "List sessions",
        "List saved conversations you can resume.",
        "messages-square",
        "",
        "session",
    ),
    BuiltinCommandSpec(
        "/resume",
        "Resume session",
        "Switch the current chat to a saved session (CLI).",
        "rotate-ccw",
        "<id>",
        "session",
    ),
    BuiltinCommandSpec(
        "/fork",
        "Fork session",
        "Branch the current conversation into a new session (CLI).",
        "git-branch",
        "[n]",
        "session",
    ),
    BuiltinCommandSpec(
        "/goal",
        "Start long-running goal",
        "Tell the agent to treat the request as a long-running goal.",
        "activity",
        "<goal>",
    ),
    BuiltinCommandSpec(
        "/dream",
        "Run Dream",
        "Manually trigger memory consolidation.",
        "sparkles",
    ),
    BuiltinCommandSpec(
        "/dream-log",
        "Show Dream log",
        "Show what the last Dream consolidation changed.",
        "book-open",
    ),
    BuiltinCommandSpec(
        "/dream-restore",
        "Restore memory",
        "Revert memory to a previous Dream snapshot.",
        "undo-2",
    ),
    BuiltinCommandSpec(
        "/skill",
        "Skills",
        "List skills, or enable/disable one for the agent.",
        "wrench",
        "[enable|disable <name>]",
    ),
    BuiltinCommandSpec(
        "/help",
        "Show help",
        "List available slash commands.",
        "circle-help",
    ),
    BuiltinCommandSpec(
        "/pairing",
        "Manage pairing",
        "List, approve, deny or revoke pairing requests.",
        "shield",
        "[list|approve <code>|deny <code>|revoke <user_id>]",
    ),
    BuiltinCommandSpec(
        "/permissions",
        "Workspace permissions",
        "Show or switch this session's access mode.",
        "shield",
        "[restricted|full]",
        "session",
        True,
        "workspace_scope",
    ),
    BuiltinCommandSpec(
        "/workspace",
        "Workspace",
        "Show or switch this session's project path.",
        "folder",
        "[path]",
        "session",
        True,
        "workspace_scope",
    ),
    BuiltinCommandSpec(
        "/cd",
        "Change workspace",
        "Alias for /workspace.",
        "folder-symlink",
        "[path]",
        "session",
        True,
        "workspace_scope",
    ),
    BuiltinCommandSpec(
        "/context",
        "Context usage",
        "Show this session's prompt and context estimate.",
        "scan-text",
        "",
        "session",
    ),
    BuiltinCommandSpec(
        "/usage",
        "Token usage",
        "Show recent and cumulative token usage.",
        "bar-chart-3",
        "",
        "session",
    ),
    BuiltinCommandSpec(
        "/clear",
        "Clear screen",
        "Clear the CLI transcript without starting a new session.",
        "eraser",
        "",
        "session",
    ),
    BuiltinCommandSpec(
        "/copy",
        "Copy reply",
        "Copy the Nth most recent assistant reply, or print it if clipboard is unavailable.",
        "copy",
        "[n]",
        "session",
    ),
    BuiltinCommandSpec(
        "/export",
        "Export transcript",
        "Export this session transcript as Markdown or JSONL.",
        "download",
        "[path]",
        "session",
    ),
    BuiltinCommandSpec(
        "/diff",
        "Workspace diff",
        "Show git diff summary and recent file edit activity.",
        "git-compare",
        "",
        "workspace",
    ),
    BuiltinCommandSpec(
        "/mcp",
        "MCP servers",
        "Show MCP status, reload, or add/remove a server.",
        "plug",
        "[status|reload|add <name> <url|command> [args…]|remove <name>]",
        "runtime",
    ),
    BuiltinCommandSpec(
        "/tasks",
        "Active tasks",
        "Show active agent tasks, subagents, and exec sessions for this session.",
        "list-checks",
        "",
        "runtime",
    ),
    BuiltinCommandSpec(
        "/cron",
        "Cron jobs",
        "List scheduled jobs, or enable/disable/remove/run one.",
        "clock",
        "[list|enable <id>|disable <id>|remove <id>|run <id>]",
        "runtime",
    ),
    BuiltinCommandSpec(
        "/output",
        "Tool output",
        "Show recent tool calls, or the full result of the Nth most recent.",
        "terminal",
        "[n]",
        "session",
    ),
)


def builtin_command_palette() -> list[dict[str, Any]]:
    """Return structured command metadata for UI command palettes."""
    return [spec.as_dict() for spec in BUILTIN_COMMAND_SPECS]


async def cmd_stop(ctx: CommandContext) -> OutboundMessage:
    """Cancel all active tasks and subagents for the session."""
    loop = ctx.loop
    msg = ctx.msg
    total = await loop._cancel_active_tasks(ctx.key)
    content = f"Stopped {total} task(s)." if total else "No active task to stop."
    return OutboundMessage(
        channel=msg.channel, chat_id=msg.chat_id, content=content,
        metadata=dict(msg.metadata or {})
    )


async def cmd_restart(ctx: CommandContext) -> OutboundMessage:
    """Restart the process in-place via os.execv."""
    msg = ctx.msg
    set_restart_notice_to_env(
        channel=msg.channel,
        chat_id=msg.chat_id,
        metadata=dict(msg.metadata or {}),
    )

    async def _do_restart():
        await asyncio.sleep(1)
        os.execv(sys.executable, [sys.executable, "-m", "nanobot"] + sys.argv[1:])

    asyncio.create_task(_do_restart())
    return OutboundMessage(
        channel=msg.channel, chat_id=msg.chat_id, content="Restarting...",
        metadata=dict(msg.metadata or {})
    )


async def cmd_status(ctx: CommandContext) -> OutboundMessage:
    """Build an outbound status message for a session."""
    loop = ctx.loop
    session = ctx.session or loop.sessions.get_or_create(ctx.key)
    ctx_est = 0
    with suppress(Exception):
        ctx_est, _ = loop.consolidator.estimate_session_prompt_tokens(session)
    if ctx_est <= 0:
        ctx_est = loop._last_usage.get("prompt_tokens", 0)

    # Fetch web search provider usage (best-effort, never blocks the response)
    search_usage_text: str | None = None
    # Never let usage fetch break /status
    with suppress(Exception):
        from nanobot.utils.searchusage import fetch_search_usage
        web_cfg = getattr(loop, "web_config", None)
        search_cfg = getattr(web_cfg, "search", None) if web_cfg else None
        if search_cfg is not None:
            provider = getattr(search_cfg, "provider", "duckduckgo")
            api_key = getattr(search_cfg, "api_key", "") or None
            usage = await fetch_search_usage(provider=provider, api_key=api_key)
            search_usage_text = usage.format()
    active_tasks = loop._active_tasks.get(ctx.key, [])
    task_count = sum(1 for t in active_tasks if not t.done())
    with suppress(Exception):
        task_count += loop.subagents.get_running_count_by_session(ctx.key)
    return OutboundMessage(
        channel=ctx.msg.channel,
        chat_id=ctx.msg.chat_id,
        content=build_status_content(
            version=__version__, model=loop.model,
            start_time=loop._start_time, last_usage=loop._last_usage,
            context_window_tokens=loop.context_window_tokens,
            session_msg_count=len(session.get_history(max_messages=0)),
            context_tokens_estimate=ctx_est,
            search_usage_text=search_usage_text,
            active_task_count=task_count,
            max_completion_tokens=getattr(
                getattr(loop.provider, "generation", None), "max_tokens", 8192
            ),
        ),
        metadata={**dict(ctx.msg.metadata or {}), "render_as": "text"},
    )


async def cmd_new(ctx: CommandContext) -> OutboundMessage:
    """Stop active task and start a fresh session."""
    loop = ctx.loop
    await loop._cancel_active_tasks(ctx.key)
    session = ctx.session or loop.sessions.get_or_create(ctx.key)
    snapshot = session.messages[session.last_consolidated:]
    session.clear()
    loop.sessions.save(session)
    loop.sessions.invalidate(session.key)
    if snapshot:
        loop._schedule_background(loop.consolidator.archive(snapshot, session_key=ctx.key))
    return OutboundMessage(
        channel=ctx.msg.channel, chat_id=ctx.msg.chat_id,
        content="New session started.",
        metadata=dict(ctx.msg.metadata or {})
    )


def _format_preset_names(names: list[str]) -> str:
    return ", ".join(f"`{name}`" for name in names) if names else "(none configured)"


def _model_preset_names(loop) -> list[str]:
    names = set(loop.model_presets)
    names.add("default")
    return ["default", *sorted(name for name in names if name != "default")]


def _active_model_preset_name(loop) -> str:
    return loop.model_preset or "default"


def _command_error_message(exc: Exception) -> str:
    return str(exc.args[0]) if isinstance(exc, KeyError) and exc.args else str(exc)


def _model_command_status(loop) -> str:
    names = _model_preset_names(loop)
    active = _active_model_preset_name(loop)
    return "\n".join([
        "## Model",
        f"- Current model: `{loop.model}`",
        f"- Current preset: `{active}`",
        f"- Available presets: {_format_preset_names(names)}",
    ])


async def cmd_model(ctx: CommandContext) -> OutboundMessage:
    """Show or switch model presets."""
    loop = ctx.loop
    args = ctx.args.strip()
    metadata = {**dict(ctx.msg.metadata or {}), "render_as": "text"}

    if not args:
        return OutboundMessage(
            channel=ctx.msg.channel,
            chat_id=ctx.msg.chat_id,
            content=_model_command_status(loop),
            metadata=metadata,
        )

    parts = args.split()
    if len(parts) != 1:
        return OutboundMessage(
            channel=ctx.msg.channel,
            chat_id=ctx.msg.chat_id,
            content="Usage: `/model [preset]`",
            metadata=metadata,
        )

    name = parts[0]
    try:
        loop.set_model_preset(name)
    except (KeyError, ValueError) as exc:
        names = _model_preset_names(loop)
        return OutboundMessage(
            channel=ctx.msg.channel,
            chat_id=ctx.msg.chat_id,
            content=(
                f"Could not switch model preset: {_command_error_message(exc)}\n\n"
                f"Available presets: {_format_preset_names(names)}"
            ),
            metadata=metadata,
        )

    max_tokens = getattr(getattr(loop.provider, "generation", None), "max_tokens", None)
    lines = [
        f"Switched model preset to `{loop.model_preset}`.",
        f"- Model: `{loop.model}`",
        f"- Context window: {loop.context_window_tokens}",
    ]
    if max_tokens is not None:
        lines.append(f"- Max output tokens: {max_tokens}")
    return OutboundMessage(
        channel=ctx.msg.channel,
        chat_id=ctx.msg.chat_id,
        content="\n".join(lines),
        metadata=metadata,
    )


async def cmd_dream(ctx: CommandContext) -> OutboundMessage:
    """Manually trigger a Dream consolidation run."""
    import time

    loop = ctx.loop
    msg = ctx.msg

    async def _run_dream():
        async def _silent(*_args, **_kwargs):
            pass

        from nanobot.agent.memory import MemoryStore

        dream_session_key = MemoryStore.dream_session_key
        build_dream_commit_message = MemoryStore.build_dream_commit_message
        prune_dream_sessions = MemoryStore.prune_dream_sessions

        store = loop.context.memory
        content = ""
        resp = None
        t0 = time.monotonic()
        try:
            result = store.build_dream_prompt()
            if result is None:
                await loop.bus.publish_outbound(OutboundMessage(
                    channel=msg.channel, chat_id=msg.chat_id,
                    content=_format_dream_no_input_message(),
                    metadata={"render_as": "text"},
                ))
                return
            prompt, last_cursor = result
            key = dream_session_key()
            resp = await loop.process_direct(
                prompt,
                session_key=key,
                ephemeral=True,
                tools=store.build_dream_tools(),
                on_progress=_silent,
            )
            elapsed = time.monotonic() - t0
            if MemoryStore.dream_run_completed(resp):
                store.set_last_dream_cursor(last_cursor)
                content = f"Dream completed in {elapsed:.1f}s."
            else:
                content = (
                    f"Dream did not complete after {elapsed:.1f}s; "
                    "memory cursor was not advanced."
                )
        except Exception as e:
            elapsed = time.monotonic() - t0
            content = f"Dream failed after {elapsed:.1f}s: {e}"
        finally:
            from nanobot.webui.token_usage import record_response_token_usage

            record_response_token_usage(
                resp,
                source="dream",
                timezone_name=getattr(loop.context, "timezone", None),
            )
            if store.git.is_initialized():
                commit_msg = build_dream_commit_message("dream: manual run", resp)
                sha = store.git.auto_commit(commit_msg)
                if sha:
                    content += f" (commit {sha})"
            store.compact_history()
            prune_dream_sessions(loop.sessions.sessions_dir)
        await loop.bus.publish_outbound(OutboundMessage(
            channel=msg.channel, chat_id=msg.chat_id, content=content,
        ))

    asyncio.create_task(_run_dream())
    return OutboundMessage(
        channel=msg.channel, chat_id=msg.chat_id, content="Dreaming...",
    )


def _format_dream_no_input_message() -> str:
    return "\n".join([
        "Dream has no conversation history to process yet.",
        "",
        "Dream reads new entries from `memory/history.jsonl` after the current Dream cursor.",
        (
            "Short chats only reach that file after token compaction or idle auto-compact, "
            "so a fresh or short WebUI chat may leave Dream with no input."
        ),
        "",
        "Next steps:",
        "- Enable `agents.defaults.idleCompactAfterMinutes` so completed chats become Dream input automatically.",
        "- Compact the current chat into memory once that manual action is available.",
        "- If you expected history to exist, check whether `memory/history.jsonl` has new entries after the Dream cursor.",
    ])


def _extract_changed_files(diff: str) -> list[str]:
    """Extract changed file paths from a unified diff."""
    files: list[str] = []
    seen: set[str] = set()
    for line in diff.splitlines():
        if not line.startswith("diff --git "):
            continue
        parts = line.split()
        if len(parts) < 4:
            continue
        path = parts[3]
        if path.startswith("b/"):
            path = path[2:]
        if path in seen:
            continue
        seen.add(path)
        files.append(path)
    return files


def _format_changed_files(diff: str) -> str:
    files = _extract_changed_files(diff)
    if not files:
        return "No tracked memory files changed."
    return ", ".join(f"`{path}`" for path in files)


def _format_dream_log_content(commit, diff: str, *, requested_sha: str | None = None) -> str:
    files_line = _format_changed_files(diff)
    lines = [
        "## Dream Update",
        "",
        "Here is the selected Dream memory change." if requested_sha else "Here is the latest Dream memory change.",
        "",
        f"- Commit: `{commit.sha}`",
        f"- Time: {commit.timestamp}",
        f"- Changed files: {files_line}",
    ]
    if diff:
        lines.extend([
            "",
            f"Use `/dream-restore {commit.sha}` to undo this change.",
            "",
            "```diff",
            diff.rstrip(),
            "```",
        ])
    else:
        lines.extend([
            "",
            "Dream recorded this version, but there is no file diff to display.",
        ])
    return "\n".join(lines)


def _format_dream_restore_list(commits: list) -> str:
    lines = [
        "## Dream Restore",
        "",
        "Choose a Dream memory version to restore. Latest first:",
        "",
    ]
    for c in commits:
        lines.append(f"- `{c.sha}` {c.timestamp} - {c.message.splitlines()[0]}")
    lines.extend([
        "",
        "Preview a version with `/dream-log <sha>` before restoring it.",
        "Restore a version with `/dream-restore <sha>`.",
    ])
    return "\n".join(lines)


async def cmd_dream_log(ctx: CommandContext) -> OutboundMessage:
    """Show what the last Dream changed.

    Default: diff of the latest commit (HEAD~1 vs HEAD).
    With /dream-log <sha>: diff of that specific commit.
    """
    store = ctx.loop.consolidator.store
    git = store.git

    if not git.is_initialized():
        if store.get_last_dream_cursor() == 0:
            msg = "Dream has not run yet. Run `/dream`, or wait for the next scheduled Dream cycle."
        else:
            msg = "Dream history is not available because memory versioning is not initialized."
        return OutboundMessage(
            channel=ctx.msg.channel, chat_id=ctx.msg.chat_id,
            content=msg, metadata={"render_as": "text"},
        )

    args = ctx.args.strip()

    if args:
        # Show diff of a specific commit
        sha = args.split()[0]
        result = git.show_commit_diff(sha)
        if not result:
            content = (
                f"Couldn't find Dream change `{sha}`.\n\n"
                "Use `/dream-restore` to list recent versions, "
                "or `/dream-log` to inspect the latest one."
            )
        else:
            commit, diff = result
            content = _format_dream_log_content(commit, diff, requested_sha=sha)
    else:
        # Default: show the latest commit's diff
        commits = git.log(max_entries=1)
        result = git.show_commit_diff(commits[0].sha) if commits else None
        if result:
            commit, diff = result
            content = _format_dream_log_content(commit, diff)
        else:
            content = "Dream memory has no saved versions yet."

    return OutboundMessage(
        channel=ctx.msg.channel, chat_id=ctx.msg.chat_id,
        content=content, metadata={"render_as": "text"},
    )


async def cmd_dream_restore(ctx: CommandContext) -> OutboundMessage:
    """Restore memory files from a previous dream commit.

    Usage:
        /dream-restore          — list recent commits
        /dream-restore <sha>    — revert a specific commit
    """
    store = ctx.loop.consolidator.store
    git = store.git
    if not git.is_initialized():
        return OutboundMessage(
            channel=ctx.msg.channel, chat_id=ctx.msg.chat_id,
            content="Dream history is not available because memory versioning is not initialized.",
        )

    args = ctx.args.strip()
    if not args:
        # Show recent commits for the user to pick
        commits = git.log(max_entries=10)
        if not commits:
            content = "Dream memory has no saved versions to restore yet."
        else:
            content = _format_dream_restore_list(commits)
    else:
        sha = args.split()[0]
        result = git.show_commit_diff(sha)
        changed_files = _format_changed_files(result[1]) if result else "the tracked memory files"
        new_sha = git.revert(sha)
        if new_sha:
            content = (
                f"Restored Dream memory to the state before `{sha}`.\n\n"
                f"- New safety commit: `{new_sha}`\n"
                f"- Restored files: {changed_files}\n\n"
                f"Use `/dream-log {new_sha}` to inspect the restore diff."
            )
        else:
            content = (
                f"Couldn't restore Dream change `{sha}`.\n\n"
                "It may not exist, or it may be the first saved version with no earlier state to restore."
            )
    return OutboundMessage(
        channel=ctx.msg.channel, chat_id=ctx.msg.chat_id,
        content=content, metadata={"render_as": "text"},
    )


_HISTORY_DEFAULT_COUNT = 10
_HISTORY_MAX_COUNT = 50
_HISTORY_MAX_CONTENT_CHARS = 200


def _format_history_message(msg: dict) -> str | None:
    """Format a single history message for display. Returns None to skip."""
    role = msg.get("role")
    if role not in ("user", "assistant"):
        return None
    content = msg.get("content") or ""
    if isinstance(content, list):
        parts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
        content = " ".join(parts)
    content = str(content).strip()
    if not content:
        return None
    if len(content) > _HISTORY_MAX_CONTENT_CHARS:
        content = content[:_HISTORY_MAX_CONTENT_CHARS] + "…"
    label = "👤 You" if role == "user" else "🤖 Bot"
    return f"{label}: {content}"


async def cmd_history(ctx: CommandContext) -> OutboundMessage:
    """Show the last N messages of the current session (default 10, max 50).

    Usage: /history [count]
    """
    count = _HISTORY_DEFAULT_COUNT
    if ctx.args.strip():
        try:
            count = max(1, min(int(ctx.args.strip()), _HISTORY_MAX_COUNT))
        except ValueError:
            return OutboundMessage(
                channel=ctx.msg.channel, chat_id=ctx.msg.chat_id,
                content="Usage: /history [count] — e.g. /history 5 (default: 10, max: 50)",
                metadata=dict(ctx.msg.metadata or {}),
            )

    session = ctx.session or ctx.loop.sessions.get_or_create(ctx.key)
    history = session.get_history(max_messages=0)
    visible = [_format_history_message(m) for m in history]
    visible = [m for m in visible if m is not None]
    recent = visible[-count:]

    if not recent:
        return OutboundMessage(
            channel=ctx.msg.channel, chat_id=ctx.msg.chat_id,
            content="No conversation history yet.",
            metadata=dict(ctx.msg.metadata or {}),
        )

    header = f"Last {len(recent)} message(s):\n"
    return OutboundMessage(
        channel=ctx.msg.channel, chat_id=ctx.msg.chat_id,
        content=header + "\n".join(recent),
        metadata={**dict(ctx.msg.metadata or {}), "render_as": "text"},
    )


_GOAL_PROMPT_TEMPLATE = """The user declared a sustained objective for this thread.

Inspect or clarify if needed, then call `long_task` with the refined objective (and optional short ui_summary). Work proceeds as normal assistant turns using your usual tools. When the objective is fully done and verified, call `complete_goal` with a brief recap. If the user later cancels or changes direction, still call `complete_goal` with an honest recap (then `long_task` again only after there is no active goal). Do not use `long_task` / `complete_goal` for trivial one-shot answers.

Goal:
{goal}
"""


async def cmd_goal(ctx: CommandContext) -> OutboundMessage | None:
    """Rewrite /goal into a normal agent turn that nudges long_task use."""
    goal = ctx.args.strip()
    if not goal:
        return OutboundMessage(
            channel=ctx.msg.channel,
            chat_id=ctx.msg.chat_id,
            content="Usage: /goal <long-running task description>",
            metadata={**dict(ctx.msg.metadata or {}), "render_as": "text"},
        )
    if ctx.session is None:
        return OutboundMessage(
            channel=ctx.msg.channel,
            chat_id=ctx.msg.chat_id,
            content=(
                "A task is already running for this chat. "
                "Use `/stop` first, then send `/goal <long-running task description>` again."
            ),
            metadata={**dict(ctx.msg.metadata or {}), "render_as": "text"},
        )

    ctx.msg.metadata = {
        **dict(ctx.msg.metadata or {}),
        "original_command": "/goal",
        "original_content": ctx.raw,
        "goal_started_at": time.time(),
    }
    ctx.msg.content = _GOAL_PROMPT_TEMPLATE.format(goal=goal)
    return None


async def cmd_pairing(ctx: CommandContext) -> OutboundMessage:
    """List, approve, deny or revoke pairing requests."""
    from nanobot.pairing import PAIRING_COMMAND_META_KEY, handle_pairing_command

    reply = handle_pairing_command(ctx.msg.channel, ctx.args)
    return OutboundMessage(
        channel=ctx.msg.channel,
        chat_id=ctx.msg.chat_id,
        content=reply,
        metadata={PAIRING_COMMAND_META_KEY: True},
    )


def _text_reply(
    ctx: CommandContext,
    content: str,
    **metadata: Any,
) -> OutboundMessage:
    """Build a plain-text outbound reply that preserves newlines across channels."""
    return OutboundMessage(
        channel=ctx.msg.channel,
        chat_id=ctx.msg.chat_id,
        content=content,
        metadata={**dict(ctx.msg.metadata or {}), "render_as": "text", **metadata},
    )


def _persist_disabled_skills(disabled: set[str]) -> None:
    """Mirror a runtime skill toggle into the on-disk config (best effort)."""
    from nanobot.config.loader import load_config, save_config

    with suppress(Exception):
        config = load_config()
        config.agents.defaults.disabled_skills = sorted(disabled)
        save_config(config)


def _toggle_skill(ctx: CommandContext, *, enable: bool, name: str) -> OutboundMessage:
    verb = "enable" if enable else "disable"
    loader = ctx.loop.context.skills
    if not name:
        return _text_reply(ctx, f"Usage: `/skill {verb} <name>`")
    known = {entry["name"] for entry in loader.list_skills(filter_unavailable=False)}
    if name not in known:
        return _text_reply(ctx, f"Unknown skill `{name}`. Run `/skill` to list available skills.")
    disabled = set(getattr(loader, "disabled_skills", None) or set())
    if enable:
        disabled.discard(name)
    else:
        disabled.add(name)
    loader.disabled_skills = disabled  # affects subsequent turns in this process
    _persist_disabled_skills(disabled)
    return _text_reply(ctx, f"Skill `{name}` {verb}d. Saved to config; applies to new turns.")


async def cmd_skill(ctx: CommandContext) -> OutboundMessage:
    """List skills, or enable/disable one."""
    loop = ctx.loop
    parts = ctx.args.strip().split()
    if parts and parts[0].lower() in {"enable", "disable"}:
        return _toggle_skill(ctx, enable=parts[0].lower() == "enable", name=" ".join(parts[1:]).strip())

    skills = loop.context.skills.list_skills(filter_unavailable=False)
    disabled = set(getattr(loop.context.skills, "disabled_skills", None) or set())
    if not skills and not disabled:
        content = "No skills available."
    else:
        lines = [f"Available skills ({len(skills)}):", ""]
        for entry in skills:
            desc = loop.context.skills._get_skill_description(entry["name"])
            lines.append(f"- **{entry['name']}** — {desc}")
        if disabled:
            lines.extend(["", f"Disabled: {', '.join(sorted(disabled))}"])
        lines.append("\nToggle with `/skill enable <name>` or `/skill disable <name>`.")
        content = "\n".join(lines)
    return OutboundMessage(
        channel=ctx.msg.channel,
        chat_id=ctx.msg.chat_id,
        content=content,
        metadata=dict(ctx.msg.metadata or {}),
    )


def _session_chat_id(ctx: CommandContext, raw: str) -> str:
    """Normalize a /resume argument to a chat_id within the current channel."""
    prefix = f"{ctx.msg.channel}:"
    return raw[len(prefix):] if raw.startswith(prefix) else raw


async def cmd_sessions(ctx: CommandContext) -> OutboundMessage:
    """List saved sessions the user can resume."""
    sessions = sorted(
        ctx.loop.sessions.list_sessions(),
        key=lambda item: item.get("updated_at") or "",
        reverse=True,
    )
    if not sessions:
        return _text_reply(ctx, "No saved sessions yet.")
    lines = ["## Sessions", ""]
    for item in sessions[:30]:
        key = str(item.get("key") or "")
        marker = "→" if key == ctx.key else " "
        title = (item.get("title") or item.get("preview") or "(empty)").strip().replace("\n", " ")
        if len(title) > 60:
            title = title[:59] + "…"
        updated = (item.get("updated_at") or "")[:16].replace("T", " ")
        lines.append(f"{marker} `{key}` — {title}  ({updated})")
    if len(sessions) > 30:
        lines.append(f"\n… {len(sessions) - 30} more")
    lines.append("\nResume with `/resume <id>` (the part after the colon), fork with `/fork`.")
    return _text_reply(ctx, "\n".join(lines))


async def cmd_resume(ctx: CommandContext) -> OutboundMessage:
    """Switch the CLI chat to a saved session."""
    arg = ctx.args.strip()
    if not arg:
        return _text_reply(ctx, "Usage: `/resume <id>` — run `/sessions` to list ids.")
    chat_id = _session_chat_id(ctx, arg)
    target_key = f"{ctx.msg.channel}:{chat_id}"
    payload = ctx.loop.sessions.read_session_file(target_key)
    if payload is None:
        return _text_reply(ctx, f"No session `{target_key}` found. Run `/sessions` to list them.")
    count = sum(
        1 for m in payload.get("messages", []) if m.get("role") in ("user", "assistant")
    )
    return _text_reply(
        ctx,
        f"Resumed `{target_key}` ({count} message(s)). Type to continue this conversation.",
        cli_resume_session=chat_id,
    )


async def cmd_fork(ctx: CommandContext) -> OutboundMessage:
    """Branch the current conversation into a new session and switch to it."""
    session = ctx.session or ctx.loop.sessions.get_or_create(ctx.key)
    user_total = sum(1 for m in session.messages if m.get("role") == "user")
    before = user_total
    arg = ctx.args.strip()
    if arg:
        try:
            before = max(0, min(int(arg), user_total))
        except ValueError:
            return _text_reply(ctx, "Usage: `/fork [n]` — n = number of user turns to keep.")
    new_chat_id = f"fork-{int(time.time())}"
    target_key = f"{ctx.msg.channel}:{new_chat_id}"
    forked = ctx.loop.sessions.fork_session_before_user_index(ctx.key, target_key, before)
    if forked is None:
        return _text_reply(ctx, "Couldn't fork this session (nothing to copy yet).")
    kept = sum(1 for m in forked.messages if m.get("role") in ("user", "assistant"))
    return _text_reply(
        ctx,
        f"Forked into `{target_key}` ({kept} message(s) copied). Switched to the new branch.",
        cli_resume_session=new_chat_id,
    )


def _format_cron_ts(ms: int | None) -> str:
    if not ms:
        return "—"
    from datetime import datetime

    try:
        return datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d %H:%M")
    except (ValueError, OSError, OverflowError):
        return str(ms)


def _format_cron_schedule(schedule: Any) -> str:
    kind = getattr(schedule, "kind", "")
    if kind == "cron" and getattr(schedule, "expr", None):
        tz = getattr(schedule, "tz", None)
        return f"cron `{schedule.expr}`" + (f" ({tz})" if tz else "")
    if kind == "every" and getattr(schedule, "every_ms", None):
        return f"every {schedule.every_ms // 1000}s"
    if kind == "at" and getattr(schedule, "at_ms", None):
        return f"at {_format_cron_ts(schedule.at_ms)}"
    return str(kind or "?")


def _format_cron_list(service: Any) -> str:
    jobs = service.list_jobs(include_disabled=True)
    if not jobs:
        return "No cron jobs scheduled."
    lines = ["## Cron Jobs", ""]
    for job in jobs:
        status = "on" if job.enabled else "off"
        next_run = _format_cron_ts(job.state.next_run_at_ms) if job.enabled else "—"
        lines.append(f"- `{job.id}` [{status}] {job.name or '(unnamed)'}")
        lines.append(f"    {_format_cron_schedule(job.schedule)} · next: {next_run}")
        if job.state.last_status:
            tail = f" ({job.state.last_error})" if job.state.last_error else ""
            lines.append(f"    last: {job.state.last_status}{tail}")
    lines.append("\nManage with `/cron enable|disable|remove|run <id>`.")
    return "\n".join(lines)


async def cmd_cron(ctx: CommandContext) -> OutboundMessage:
    """List or manage scheduled cron jobs."""
    service = getattr(ctx.loop, "cron_service", None)
    if service is None:
        return _text_reply(ctx, "Cron service is not available in this runtime.")
    parts = ctx.args.strip().split()
    action = parts[0].lower() if parts else "list"
    job_id = parts[1] if len(parts) > 1 else ""

    if action in {"list", "ls"}:
        return _text_reply(ctx, _format_cron_list(service))
    if action in {"enable", "disable"}:
        if not job_id:
            return _text_reply(ctx, f"Usage: `/cron {action} <id>`")
        job = service.enable_job(job_id, action == "enable")
        if job is None:
            return _text_reply(ctx, f"No cron job `{job_id}`.")
        return _text_reply(ctx, f"Cron job `{job_id}` {action}d.")
    if action in {"remove", "delete", "rm"}:
        if not job_id:
            return _text_reply(ctx, "Usage: `/cron remove <id>`")
        result = service.remove_job(job_id)
        messages = {
            "removed": f"Removed cron job `{job_id}`.",
            "protected": f"Cron job `{job_id}` is protected and cannot be removed.",
            "not_found": f"No cron job `{job_id}`.",
        }
        return _text_reply(ctx, messages.get(result, f"Cron job `{job_id}`: {result}"))
    if action == "run":
        if not job_id:
            return _text_reply(ctx, "Usage: `/cron run <id>`")
        ok = await service.run_job(job_id, force=True)
        return _text_reply(
            ctx, f"Triggered cron job `{job_id}`." if ok else f"Couldn't run cron job `{job_id}`."
        )
    return _text_reply(ctx, "Usage: `/cron [list|enable <id>|disable <id>|remove <id>|run <id>]`")


def _current_workspace_scope(ctx: CommandContext) -> WorkspaceScope:
    return ctx.loop.workspace_scopes.for_turn(
        channel=ctx.msg.channel,
        message_metadata=ctx.msg.metadata,
        session_metadata=ctx.session.metadata if ctx.session is not None else None,
    )


def _persist_workspace_scope(ctx: CommandContext, scope: WorkspaceScope) -> None:
    if ctx.session is not None:
        ctx.session.metadata[WORKSPACE_SCOPE_METADATA_KEY] = scope.metadata()
    ctx.msg.metadata = {
        **dict(ctx.msg.metadata or {}),
        WORKSPACE_SCOPE_METADATA_KEY: scope.metadata(),
    }


def _scope_status_text(scope: WorkspaceScope) -> str:
    lines = [
        "## Workspace Scope",
        f"- Project: `{scope.project_path}`",
        f"- Access mode: `{scope.access_mode}`",
        f"- Guard: {scope.sandbox_status.summary}",
    ]
    if scope.access_mode == "full":
        lines.append("- Warning: full access disables workspace path restriction for this session.")
    return "\n".join(lines)


async def cmd_permissions(ctx: CommandContext) -> OutboundMessage:
    """Show or switch current session workspace access mode."""
    current = _current_workspace_scope(ctx)
    args = ctx.args.strip().lower()
    if not args:
        content = _scope_status_text(current)
    elif args in {"restricted", "restrict", "full", "full-access"}:
        try:
            scope = validate_workspace_scope_payload(
                {
                    "project_path": str(current.project_path),
                    "access_mode": args,
                },
                default_workspace=ctx.loop.workspace_scopes.default_workspace,
                default_restrict_to_workspace=ctx.loop.workspace_scopes.default_restrict_to_workspace,
                source_channel=ctx.msg.channel,
            )
        except WorkspaceScopeError as exc:
            content = f"Could not update permissions: {exc.message}"
        else:
            _persist_workspace_scope(ctx, scope)
            content = "Updated permissions for this session.\n\n" + _scope_status_text(scope)
    else:
        content = "Usage: `/permissions [restricted|full]`"
    return _text_reply(ctx, content)


def _resolve_workspace_arg(raw: str, base: Path) -> Path:
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = base / path
    return path.resolve(strict=False)


async def cmd_workspace(ctx: CommandContext) -> OutboundMessage:
    """Show or switch current session project path."""
    current = _current_workspace_scope(ctx)
    args = ctx.args.strip()
    if not args:
        content = _scope_status_text(current)
    else:
        project = _resolve_workspace_arg(args, current.project_path)
        try:
            scope = validate_workspace_scope_payload(
                {
                    "project_path": str(project),
                    "access_mode": current.access_mode,
                },
                default_workspace=ctx.loop.workspace_scopes.default_workspace,
                default_restrict_to_workspace=ctx.loop.workspace_scopes.default_restrict_to_workspace,
                source_channel=ctx.msg.channel,
            )
        except WorkspaceScopeError as exc:
            content = f"Could not update workspace: {exc.message}"
        else:
            _persist_workspace_scope(ctx, scope)
            content = "Updated workspace for this session.\n\n" + _scope_status_text(scope)
    return _text_reply(ctx, content)


async def cmd_context(ctx: CommandContext) -> OutboundMessage:
    """Show prompt/context estimate for the current session."""
    session = ctx.session or ctx.loop.sessions.get_or_create(ctx.key)
    estimate = 0
    with suppress(Exception):
        estimate, _ = ctx.loop.consolidator.estimate_session_prompt_tokens(session)
    max_output = getattr(getattr(ctx.loop.provider, "generation", None), "max_tokens", None)
    lines = [
        "## Context",
        f"- Session messages: {len(session.get_history(max_messages=0))}",
        f"- Prompt tokens estimate: {estimate or 'unknown'}",
        f"- Context window: {ctx.loop.context_window_tokens or 'unknown'}",
    ]
    if max_output is not None:
        lines.append(f"- Max output tokens: {max_output}")
    return _text_reply(ctx, "\n".join(lines))


def _format_usage_map(usage: dict[str, Any]) -> str:
    if not usage:
        return "No token usage has been recorded for this runtime yet."
    keys = [
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "cached_tokens",
        "estimated_tokens",
        "provider_tokens",
    ]
    lines = ["## Usage", "", "Recent turn:"]
    for key in keys:
        value = usage.get(key)
        if value:
            lines.append(f"- {key}: {value}")
    return "\n".join(lines)


def _format_cumulative_usage() -> str:
    """Aggregate persisted token usage by source (matches the WebUI heatmap data)."""
    try:
        from nanobot.webui.token_usage import read_token_usage_state

        state = read_token_usage_state()
    except Exception:
        return ""
    days = state.get("days", {}) if isinstance(state, dict) else {}
    if not days:
        return ""
    total = 0
    requests = 0
    by_source: dict[str, int] = {}
    for row in days.values():
        if not isinstance(row, dict):
            continue
        total += int(row.get("total_tokens") or 0)
        requests += int(row.get("requests") or 0)
        for source, srow in (row.get("sources") or {}).items():
            if isinstance(srow, dict):
                by_source[source] = by_source.get(source, 0) + int(srow.get("total_tokens") or 0)
    if total <= 0:
        return ""
    lines = ["", "Cumulative:", f"- total: {total:,} tokens over {requests} request(s)"]
    if by_source:
        lines.append("- by source:")
        for source, tokens in sorted(by_source.items(), key=lambda kv: kv[1], reverse=True):
            pct = (tokens * 100 // total) if total else 0
            lines.append(f"    - {source}: {tokens:,} ({pct}%)")
    return "\n".join(lines)


async def cmd_usage(ctx: CommandContext) -> OutboundMessage:
    """Show recent and cumulative (by-source) token usage."""
    content = _format_usage_map(dict(getattr(ctx.loop, "_last_usage", {}) or {}))
    content += _format_cumulative_usage()
    return _text_reply(ctx, content)


async def cmd_clear(ctx: CommandContext) -> OutboundMessage:
    """Ask terminal clients to clear their transcript."""
    return _text_reply(ctx, "Screen cleared.", cli_clear=True)


def _assistant_reply_texts(ctx: CommandContext) -> list[str]:
    session = ctx.session or ctx.loop.sessions.get_or_create(ctx.key)
    replies: list[str] = []
    for message in reversed(session.messages):
        if message.get("role") != "assistant" or message.get("_command"):
            continue
        content = message.get("content")
        if isinstance(content, str) and content.strip():
            replies.append(content.strip())
    return replies


async def _copy_to_clipboard(text: str) -> bool:
    if sys.platform == "darwin" and shutil.which("pbcopy"):
        proc = await asyncio.create_subprocess_exec(
            "pbcopy",
            stdin=asyncio.subprocess.PIPE,
        )
        assert proc.stdin is not None
        proc.stdin.write(text.encode("utf-8"))
        await proc.stdin.drain()
        proc.stdin.close()
        await proc.wait()
        return proc.returncode == 0
    return False


async def cmd_copy(ctx: CommandContext) -> OutboundMessage:
    """Copy a recent assistant reply when a clipboard command is available."""
    idx = 1
    if ctx.args.strip():
        try:
            idx = max(1, int(ctx.args.strip()))
        except ValueError:
            return _text_reply(ctx, "Usage: `/copy [n]`")
    replies = _assistant_reply_texts(ctx)
    if idx > len(replies):
        content = "No assistant reply found to copy."
    else:
        text = replies[idx - 1]
        if await _copy_to_clipboard(text):
            content = f"Copied assistant reply {idx} to clipboard."
        else:
            content = "Clipboard is unavailable. Here is the reply:\n\n" + text
    return _text_reply(ctx, content)


def _export_path(ctx: CommandContext, raw: str) -> Path:
    scope = _current_workspace_scope(ctx)
    if raw.strip():
        path = Path(raw.strip()).expanduser()
    else:
        safe_key = ctx.key.replace("/", "_").replace(":", "_")
        path = Path(f"{safe_key}-transcript.md")
    if not path.is_absolute():
        path = scope.project_path / path
    resolved = path.resolve(strict=False)
    if scope.restrict_to_workspace:
        try:
            resolved.relative_to(scope.project_path)
        except ValueError as exc:
            raise WorkspaceScopeError("export path must stay inside the workspace") from exc
    return resolved


def _session_messages(ctx: CommandContext) -> list[dict[str, Any]]:
    session = ctx.session or ctx.loop.sessions.get_or_create(ctx.key)
    return list(session.messages)


def _transcript_markdown(messages: list[dict[str, Any]]) -> str:
    parts = ["# nanobot Transcript", ""]
    for message in messages:
        role = str(message.get("role") or "message").title()
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            continue
        parts.extend([f"## {role}", "", content.strip(), ""])
    return "\n".join(parts).rstrip() + "\n"


async def cmd_export(ctx: CommandContext) -> OutboundMessage:
    """Export current session transcript to Markdown or JSONL."""
    try:
        path = _export_path(ctx, ctx.args)
        path.parent.mkdir(parents=True, exist_ok=True)
        messages = _session_messages(ctx)
        if path.suffix.lower() == ".jsonl":
            content = "\n".join(json.dumps(m, ensure_ascii=False) for m in messages) + "\n"
        else:
            content = _transcript_markdown(messages)
        path.write_text(content, encoding="utf-8")
        text = f"Exported {len(messages)} message(s) to `{path}`."
    except (OSError, WorkspaceScopeError) as exc:
        text = f"Export failed: {getattr(exc, 'message', str(exc))}"
    return _text_reply(ctx, text)


async def _git_lines(cwd: Path, *args: str) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        "git",
        *args,
        cwd=str(cwd),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    text = (stdout or stderr).decode("utf-8", errors="replace").strip()
    return int(proc.returncode or 0), text


async def cmd_diff(ctx: CommandContext) -> OutboundMessage:
    """Show workspace git diff summary."""
    scope = _current_workspace_scope(ctx)
    if not shutil.which("git"):
        content = "git is not available on PATH."
    else:
        code, inside = await _git_lines(scope.project_path, "rev-parse", "--is-inside-work-tree")
        if code != 0 or inside.strip() != "true":
            content = f"`{scope.project_path}` is not a git repository."
        else:
            _, status = await _git_lines(scope.project_path, "status", "--short")
            _, stat = await _git_lines(scope.project_path, "diff", "--stat")
            sections = ["## Diff", status or "No changed files."]
            if stat:
                sections.extend(["", "```", stat, "```"])
            content = "\n".join(sections)
    return _text_reply(ctx, content)


async def _mcp_apply_config(ctx: CommandContext, mutate) -> dict[str, Any]:
    """Load config, apply *mutate* to ``tools.mcp_servers``, save, and hot reload."""
    from nanobot.agent.tools.mcp import reload_servers
    from nanobot.config.loader import load_config, save_config

    config = load_config()
    mutate(config.tools.mcp_servers)
    save_config(config)
    return await reload_servers(ctx.loop, ctx.loop.tools)


async def _mcp_add(ctx: CommandContext, rest: list[str]) -> str:
    if len(rest) < 2:
        return "Usage: `/mcp add <name> <url|command> [args…]`"
    from nanobot.config.schema import MCPServerConfig

    name, target, *extra = rest
    if target.startswith(("http://", "https://")):
        server = MCPServerConfig(url=target)
    else:
        server = MCPServerConfig(command=target, args=list(extra))
    result = await _mcp_apply_config(ctx, lambda servers: servers.__setitem__(name, server))
    connected = name in (result.get("connected") or [])
    status = "connected" if connected else "configured (not connected yet)"
    return f"Added MCP server `{name}` ({status}).\n{result.get('message', '')}".strip()


async def _mcp_remove(ctx: CommandContext, rest: list[str]) -> str:
    if not rest:
        return "Usage: `/mcp remove <name>`"
    from nanobot.config.loader import load_config

    name = rest[0]
    if name not in load_config().tools.mcp_servers:
        return f"No MCP server `{name}` in config."
    result = await _mcp_apply_config(ctx, lambda servers: servers.pop(name, None))
    return f"Removed MCP server `{name}`.\n{result.get('message', '')}".strip()


async def cmd_mcp(ctx: CommandContext) -> OutboundMessage:
    """Show MCP status, hot reload, or add/remove a server."""
    parts = ctx.args.strip().split()
    action = parts[0].lower() if parts else "status"
    if action == "status":
        configured = sorted(getattr(ctx.loop, "_mcp_servers", {}) or {})
        connected = sorted(getattr(ctx.loop, "_mcp_stacks", {}) or {})
        lines = [
            "## MCP",
            f"- Configured: {', '.join(configured) if configured else '(none)'}",
            f"- Connected: {', '.join(connected) if connected else '(none)'}",
            f"- Connecting: {bool(getattr(ctx.loop, '_mcp_connecting', False))}",
        ]
        content = "\n".join(lines)
    elif action == "reload":
        from nanobot.agent.tools.mcp import reload_servers

        result = await reload_servers(ctx.loop, ctx.loop.tools)
        content = str(result.get("message") or "MCP reload complete.")
    elif action == "add":
        content = await _mcp_add(ctx, parts[1:])
    elif action in {"remove", "rm", "delete"}:
        content = await _mcp_remove(ctx, parts[1:])
    else:
        content = "Usage: `/mcp [status|reload|add <name> <url|command> [args…]|remove <name>]`"
    return _text_reply(ctx, content)


async def cmd_tasks(ctx: CommandContext) -> OutboundMessage:
    """Show active runtime tasks for this session."""
    active_tasks = getattr(ctx.loop, "_active_tasks", {}).get(ctx.key, [])
    active_count = sum(1 for task in active_tasks if not task.done())
    subagents = 0
    with suppress(Exception):
        subagents = ctx.loop.subagents.get_running_count_by_session(ctx.key)
    lines = [
        "## Tasks",
        f"- Agent turns: {active_count}",
        f"- Subagents: {subagents}",
    ]
    if active_count == 0 and subagents == 0:
        lines.append("- No active tasks for this session.")
    return _text_reply(ctx, "\n".join(lines))


def _tool_result_messages(ctx: CommandContext) -> list[dict[str, Any]]:
    session = ctx.session or ctx.loop.sessions.get_or_create(ctx.key)
    return [m for m in session.messages if m.get("role") == "tool"]


def _stringify_tool_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                parts.append(str(item.get("text") or item.get("content") or json.dumps(item, ensure_ascii=False)))
            else:
                parts.append(str(item))
        return "\n".join(parts)
    return json.dumps(content, ensure_ascii=False) if content is not None else ""


async def cmd_output(ctx: CommandContext) -> OutboundMessage:
    """Show recent tool calls, or the full result of the Nth most recent one."""
    tool_messages = _tool_result_messages(ctx)
    arg = ctx.args.strip()
    if not tool_messages:
        content = "No tool output recorded for this session yet."
    elif not arg:
        recent = list(reversed(tool_messages))[:10]
        lines = ["## Recent tool output", "", "Run `/output <n>` to see the full result.", ""]
        for idx, message in enumerate(recent, start=1):
            name = str(message.get("name") or "tool")
            preview = " ".join(_stringify_tool_content(message.get("content")).split())
            if len(preview) > 80:
                preview = preview[:79] + "…"
            lines.append(f"{idx}. `{name}` — {preview or '(empty)'}")
        content = "\n".join(lines)
    else:
        try:
            idx = max(1, int(arg))
        except ValueError:
            idx = 1
        recent = list(reversed(tool_messages))
        if idx > len(recent):
            content = f"Only {len(recent)} tool result(s) available."
        else:
            message = recent[idx - 1]
            name = str(message.get("name") or "tool")
            body = _stringify_tool_content(message.get("content")) or "(empty result)"
            content = f"## Tool output {idx}: `{name}`\n\n```\n{body}\n```"
    return _text_reply(ctx, content)


async def cmd_help(ctx: CommandContext) -> OutboundMessage:
    """Return available slash commands."""
    return _text_reply(ctx, build_help_text())


def build_help_text() -> str:
    """Build canonical help text shared across channels."""
    lines = ["nanobot commands:"]
    for spec in BUILTIN_COMMAND_SPECS:
        command = spec.command
        if spec.arg_hint:
            command = f"{command} {spec.arg_hint}"
        lines.append(f"{command} — {spec.description}")
    return "\n".join(lines)


def register_builtin_commands(router: CommandRouter) -> None:
    """Register the default set of slash commands."""
    router.priority("/stop", cmd_stop)
    router.priority("/restart", cmd_restart)
    router.priority("/status", cmd_status)
    router.exact("/new", cmd_new)
    router.exact("/status", cmd_status)
    router.exact("/model", cmd_model)
    router.prefix("/model ", cmd_model)
    router.exact("/history", cmd_history)
    router.prefix("/history ", cmd_history)
    router.exact("/goal", cmd_goal)
    router.prefix("/goal ", cmd_goal)
    router.exact("/dream", cmd_dream)
    router.exact("/dream-log", cmd_dream_log)
    router.prefix("/dream-log ", cmd_dream_log)
    router.exact("/dream-restore", cmd_dream_restore)
    router.prefix("/dream-restore ", cmd_dream_restore)
    router.exact("/skill", cmd_skill)
    router.prefix("/skill ", cmd_skill)
    router.exact("/sessions", cmd_sessions)
    router.exact("/resume", cmd_resume)
    router.prefix("/resume ", cmd_resume)
    router.exact("/fork", cmd_fork)
    router.prefix("/fork ", cmd_fork)
    router.exact("/cron", cmd_cron)
    router.prefix("/cron ", cmd_cron)
    router.exact("/help", cmd_help)
    router.exact("/pairing", cmd_pairing)
    router.prefix("/pairing ", cmd_pairing)
    router.exact("/permissions", cmd_permissions)
    router.prefix("/permissions ", cmd_permissions)
    router.exact("/workspace", cmd_workspace)
    router.prefix("/workspace ", cmd_workspace)
    router.exact("/cd", cmd_workspace)
    router.prefix("/cd ", cmd_workspace)
    router.exact("/context", cmd_context)
    router.exact("/usage", cmd_usage)
    router.exact("/clear", cmd_clear)
    router.exact("/copy", cmd_copy)
    router.prefix("/copy ", cmd_copy)
    router.exact("/export", cmd_export)
    router.prefix("/export ", cmd_export)
    router.exact("/diff", cmd_diff)
    router.exact("/mcp", cmd_mcp)
    router.prefix("/mcp ", cmd_mcp)
    router.exact("/tasks", cmd_tasks)
    router.exact("/output", cmd_output)
    router.prefix("/output ", cmd_output)
