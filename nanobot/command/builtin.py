from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from contextlib import suppress
from dataclasses import replace
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from loguru import logger

from nanobot import __version__
from nanobot.agent.model_presets import UnknownModelPresetError
from nanobot.bus.events import INBOUND_META_MODEL_CONTROL, OutboundMessage
from nanobot.bus.outbound_events import CommandLine
from nanobot.command.results import command_reply, line, render
from nanobot.command.router import CommandContext, CommandRouter
from nanobot.command.spec import BuiltinCommandSpec
from nanobot.command.spec import CommandLifecycle as CommandLifecycle
from nanobot.command.status import status_lines
from nanobot.command.user_shell import cmd_user_shell
from nanobot.providers.base import LLMUsage
from nanobot.utils.cancellation import shield_and_drain
from nanobot.utils.gitstore import GitStoreDirtyError
from nanobot.utils.restart import set_restart_notice_to_env
from nanobot.utils.workspace_prompts import initialize_workspace_prompt

if TYPE_CHECKING:
    from nanobot.agent.loop import AgentLoop

_RESTART_ACK_TIMEOUT_S = 10.0
USER_SHELL_COMMAND = "/__shell"
# Both graphical and terminal chat composers provide the $ skill picker.
CHAT_UI_COMMAND_REPLACEMENTS = {"/skill": "$"}


CORE_COMMAND_SPECS: tuple[BuiltinCommandSpec, ...] = (
    BuiltinCommandSpec.localized(
        "/new", "square-pen",
        lifecycle="finalize_active_turn",
    ),
    BuiltinCommandSpec.localized("/compact", "archive"),
    BuiltinCommandSpec.localized(
        "/stop", "square",
        lifecycle="stop_active_turn",
    ),
    BuiltinCommandSpec.localized("/restart", "rotate-cw"),
    BuiltinCommandSpec.localized("/status", "activity"),
    BuiltinCommandSpec.localized(
        "/model", "brain",
        "[preset]",
        accepts_args=True,
    ),
    BuiltinCommandSpec.localized(
        "/trigger", "zap",
        "<name>",
        accepts_args=True,
    ),
    BuiltinCommandSpec.localized("/dream", "sparkles"),
    BuiltinCommandSpec.localized(
        "/dream-log", "book-open",
        accepts_args=True,
    ),
    BuiltinCommandSpec.localized(
        "/dream-restore", "undo-2",
        accepts_args=True,
    ),
    BuiltinCommandSpec.localized(
        "/dream-prompt", "file-text",
        "[init]",
        accepts_args=True,
    ),
    BuiltinCommandSpec.localized(
        "/evaluator-prompt", "file-text",
        "[init]",
        accepts_args=True,
    ),
    BuiltinCommandSpec.localized("/skill", "wrench"),
    BuiltinCommandSpec.localized("/help", "circle-help"),
    BuiltinCommandSpec.localized(
        "/pairing", "shield",
        "[list|approve <code>|deny <code>|revoke <user_id>]",
        accepts_args=True,
    ),
)


async def cmd_stop(ctx: CommandContext) -> OutboundMessage:
    """Cancel all active tasks and subagents for the session."""
    loop = ctx.loop
    msg = ctx.msg
    await loop._cancel_active_tasks(ctx.key)  # pyright: ignore[reportPrivateUsage]
    return command_reply(msg, "/stop", line("stop.done"), outcome="stopped")


async def cmd_restart(ctx: CommandContext) -> OutboundMessage:
    """Restart the process."""
    msg = ctx.msg

    def _do_restart(confirmed: bool) -> None:
        if deadline.cancelled():
            return
        deadline.cancel()
        if not confirmed:
            logger.warning("Restarting without send confirmation after {}s", _RESTART_ACK_TIMEOUT_S)
        set_restart_notice_to_env(channel=msg.channel, chat_id=msg.chat_id, metadata=msg.metadata)
        argv = [sys.executable, "-m", "nanobot"] + sys.argv[1:]
        mode = ctx.loop.restart_mode or "auto"
        if mode == "auto":
            mode = "spawn" if sys.platform == "win32" else "exec"
        if mode == "exec":
            os.execv(sys.executable, argv)
            return
        if mode == "spawn":
            kwargs: dict[str, Any] = {}
            if sys.platform == "win32":
                kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
            subprocess.Popen(argv, **kwargs)
        os._exit(0)

    def on_confirmation(sent: asyncio.Future[None]) -> None:
        if not sent.cancelled() and sent.exception() is None:
            _do_restart(True)

    loop = asyncio.get_running_loop()
    deadline = loop.call_later(_RESTART_ACK_TIMEOUT_S, _do_restart, False)
    reply = command_reply(msg, "/restart", line("restart.started"))
    reply.sent = loop.create_future()
    reply.sent.add_done_callback(on_confirmation)
    return reply


async def cmd_status(ctx: CommandContext) -> OutboundMessage:
    """Build an outbound status message for a session."""
    loop = ctx.loop
    session = ctx.session or await loop.sessions.state.get(ctx.key)
    runtime = ctx.runtime or await loop.runtime_for_session(session)
    last_usage = LLMUsage.from_dict(session.metadata.get("_last_usage"))
    snapshot = await loop.sessions.state.project_history(
        ctx.key, lambda history: history.latest_context_usage(session.generation),
    )
    if snapshot is not None:
        context_tokens, window, estimated = snapshot
        recorded = not estimated
    else:
        recorded = False
        window = runtime.context_window_tokens
        context_tokens = None
        with suppress(Exception):
            estimate, _ = loop.consolidator.estimate_session_prompt_tokens(session, runtime=runtime)
            if estimate > 0:
                context_tokens = estimate

    # Await web search provider usage; network requests have a bounded timeout.
    usage = None
    # Never let usage fetch break /status
    with suppress(Exception):
        from nanobot.utils.searchusage import fetch_search_usage
        search_cfg = loop.web_config.search
        usage = await fetch_search_usage(
            provider=search_cfg.provider,
            api_key=search_cfg.api_key or None,
        )
    active_tasks = loop._active_tasks.get(ctx.key, [])  # pyright: ignore[reportPrivateUsage]
    task_count = sum(1 for t in active_tasks if not t.done())
    with suppress(Exception):
        task_count += loop.subagents.get_running_count_by_session(ctx.key)
    return command_reply(ctx.msg, "/status", *status_lines(
        version=__version__, model=runtime.model, start_time=loop._start_time,  # pyright: ignore[reportPrivateUsage]
        last_usage=last_usage, context_window_tokens=window,
        session_msg_count=len(session.get_text_history()), context_tokens=context_tokens,
        recorded_context=recorded, search_usage=usage, active_task_count=task_count,
    ))


async def cmd_new(ctx: CommandContext) -> OutboundMessage:
    """Stop active task and start a fresh session."""
    loop = ctx.loop
    await loop._cancel_active_tasks(ctx.key)  # pyright: ignore[reportPrivateUsage]
    loop.discard_session_file_state(ctx.key)
    session = ctx.session or await loop.sessions.state.get(ctx.key)
    snapshot = list(session.messages)
    archive_snapshot = None
    runtime = None
    if session.last_archived < len(snapshot):
        runtime = ctx.runtime or await loop.runtime_for_session(session)
        archive_snapshot = replace(
            session,
            messages=snapshot,
            metadata=dict(session.metadata),
            provider_state=None,
        )

    async def reset_and_schedule_archive() -> None:
        await loop.sessions.state.reset(session.key)
        if archive_snapshot is not None and runtime is not None:
            loop.schedule_background(
                loop.consolidator.archive_session(  # pyright: ignore[reportUnknownMemberType]
                    archive_snapshot,
                    archive_end=len(snapshot),
                    runtime=runtime,
                )
            )

    await shield_and_drain(reset_and_schedule_archive())
    ctx.record_exchange = False
    return command_reply(ctx.msg, "/new", line("new.done"), outcome="session_reset")


async def cmd_compact(ctx: CommandContext) -> OutboundMessage | None:
    """Compact the current session without resetting the conversation."""
    loop = ctx.loop
    session = ctx.session or await loop.sessions.state.get(ctx.key)
    runtime = ctx.runtime or await loop.runtime_for_session(session)
    delivery = loop.turn_delivery_factory.create(ctx.msg, ctx.key)

    try:
        summary = await loop.consolidator.compact_idle_session(
            ctx.key,
            runtime=runtime,
            events=delivery.events,
            notify=True,
            reason="manual",
        )
    except Exception:
        logger.exception("Manual context compaction failed for {}", ctx.key)
        return None
    if summary == "":
        # A no-op should not create new history or reset the archive's idle timer.
        ctx.record_exchange = False
        return command_reply(ctx.msg, "/compact", line("compact.empty"))
    return None


def _format_preset_names(names: list[str]) -> str:
    return ", ".join(f"`{name}`" for name in names)


def _model_preset_names(loop: AgentLoop) -> list[str]:
    names = set(loop.model_presets)
    names.add("default")
    return ["default", *sorted(name for name in names if name != "default")]


def _command_error_message(exc: Exception) -> str:
    return str(exc.args[0]) if isinstance(exc, KeyError) and exc.args else str(exc)


async def cmd_model(ctx: CommandContext) -> OutboundMessage:
    if ctx.msg.metadata.get(INBOUND_META_MODEL_CONTROL) is True:
        ctx.record_exchange = False
    loop = ctx.loop
    name = ctx.args.strip()
    available = line("model.options", names=_format_preset_names(_model_preset_names(loop)))
    parts: list[str | CommandLine]
    switched_preset = None
    if not name:
        session = ctx.session or await loop.sessions.state.get(ctx.key)
        try:
            runtime = await loop.runtime_for_session(session, recover_removed=False)
        except UnknownModelPresetError as exc:
            parts = [line("model.notFound", preset=exc.name), available, line("model.hint")]
        except (KeyError, ValueError) as exc:
            parts = [line("model.invalid", error=_command_error_message(exc)), available, line("model.hint")]
        else:
            parts = [line("model.current", model=runtime.model), line("model.preset", preset=runtime.model_preset or "default"), available]
    else:
        try:
            runtime = await loop.set_session_model_preset(ctx.key, name)
        except UnknownModelPresetError as exc:
            parts = [line("model.notFound", preset=exc.name), available]
        except (KeyError, ValueError) as exc:
            parts = [line("model.failed", error=_command_error_message(exc)), "", available]
        else:
            switched_preset = runtime.model_preset or "default"
            parts = [line("model.switched", preset=switched_preset), line("model.scope"),
                     line("model.name", model=runtime.model), line("model.window", tokens=runtime.context_window_tokens),
                     line("model.max", tokens=runtime.generation.max_tokens)]
    return command_reply(ctx.msg, "/model", *parts, switched_preset=switched_preset)


async def cmd_dream(ctx: CommandContext) -> OutboundMessage:
    """Manually trigger a Dream consolidation run."""
    import time

    loop = ctx.loop
    msg = replace(ctx.msg, metadata=dict(ctx.msg.metadata))

    async def _run_dream() -> None:
        from nanobot.agent.dream import run_dream

        t0 = time.monotonic()
        result = await run_dream(loop, commit_prefix="dream: manual run")
        elapsed = f"{time.monotonic() - t0:.1f}"
        if result.error:
            outcome = line("dream.failed", elapsed=elapsed, error=result.error)
        elif not result.had_input:
            outcome = line("dream.no_input")
        elif result.changed:
            outcome = line("dream.completed", elapsed=elapsed)
        else:
            outcome = line("dream.unchanged", elapsed=elapsed)
        parts = [outcome]
        if result.commit_sha:
            parts.append(line("dream.commit", sha=result.commit_sha))
        await loop.bus.publish_outbound(command_reply(
            msg, "/dream", *parts,
            notification_id=f"command-result:{uuid4().hex}",
        ))

    ctx.after_reply = lambda: loop.schedule_background(_run_dream())
    return command_reply(msg, "/dream", line("dream.started"))


async def cmd_dream_prompt(ctx: CommandContext) -> OutboundMessage:
    """Show or set up the workspace Dream memory instructions."""
    store = ctx.loop.context.memory
    path = store.dream_prompt_file
    display_path = path.relative_to(store.workspace).as_posix()
    args = ctx.args.strip().lower()

    if args == "init":
        if initialize_workspace_prompt(path, store.default_dream_prompt()):
            result = line("dream.prompt.created", path=display_path)
        else:
            result = line("dream.prompt.exists", path=display_path)
    elif args:
        result = line("dream.prompt.usage", command="/dream-prompt")
    elif store.has_dream_prompt_override():
        result = line("dream.prompt.custom", path=display_path)
    else:
        result = line("dream.prompt.default", path=display_path)
    return command_reply(ctx.msg, "/dream-prompt", result)


async def cmd_evaluator_prompt(ctx: CommandContext) -> OutboundMessage:
    """Show or set up the workspace heartbeat evaluator prompt."""
    from nanobot.utils.evaluator import (
        default_evaluator_prompt,
        evaluator_prompt_file,
        has_evaluator_prompt_override,
    )

    workspace = ctx.loop.context.memory.workspace
    path = evaluator_prompt_file(workspace)
    display_path = path.relative_to(workspace).as_posix()
    args = ctx.args.strip().lower()

    if args == "init":
        if initialize_workspace_prompt(path, default_evaluator_prompt()):
            result = line("evaluator.prompt.created", path=display_path)
        else:
            result = line("evaluator.prompt.exists", path=display_path)
    elif args:
        result = line("dream.prompt.usage", command="/evaluator-prompt")
    elif has_evaluator_prompt_override(workspace):
        result = line("evaluator.prompt.custom", path=display_path)
    else:
        result = line("evaluator.prompt.default", path=display_path)
    return command_reply(ctx.msg, "/evaluator-prompt", result)


def _extract_changed_files(diff: str) -> list[str]:
    files: list[str] = []
    seen: set[str] = set()
    for diff_line in diff.splitlines():
        if not diff_line.startswith("diff --git "):
            continue
        parts = diff_line.split()
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


_DREAM_COMMIT_PREFIX = "dream:"


async def cmd_dream_log(ctx: CommandContext) -> OutboundMessage:
    """Show the diff for the latest Dream commit, or for the requested SHA."""
    store = ctx.loop.consolidator.store
    git = store.git
    if not git.is_initialized():
        result = line("dream.log.not_run") if store.get_last_dream_cursor() == 0 else line("dream.history_unavailable")
        return command_reply(ctx.msg, "/dream-log", result)

    args = ctx.args.split()
    if args:
        change = git.show_commit_diff(args[0])
        if not change:
            return command_reply(ctx.msg, "/dream-log", line("dream.log.not_found", sha=args[0]))
    else:
        commits = git.log(max_entries=1, message_prefix=_DREAM_COMMIT_PREFIX)
        change = (
            git.show_commit_diff(commits[0].sha, max_entries=1, message_prefix=_DREAM_COMMIT_PREFIX)
            if commits else None
        )
        if not change:
            return command_reply(ctx.msg, "/dream-log", line("dream.log.empty"))

    commit, diff = change
    files = ", ".join(f"`{path}`" for path in _extract_changed_files(diff))
    parts: list[str | CommandLine] = [
        line("dream.log.selected") if args else line("dream.log.latest"), "",
        line("dream.log.details", sha=commit.sha, timestamp=commit.timestamp),
        line("dream.log.files", files=files) if files else line("dream.log.no_files"), "",
    ]
    if diff:
        fenced_diff = "```diff\n" + diff + ("" if diff.endswith("\n") else "\n") + "```"
        parts.extend([line("dream.log.undo", sha=commit.sha), "", fenced_diff])
    else:
        parts.append(line("dream.log.no_diff"))
    return command_reply(ctx.msg, "/dream-log", *parts)


async def cmd_dream_restore(ctx: CommandContext) -> OutboundMessage:
    """List recent Dream versions or revert the selected Dream change."""
    store = ctx.loop.consolidator.store
    git = store.git
    if not git.is_initialized():
        return command_reply(ctx.msg, "/dream-restore", line("dream.history_unavailable"))

    args = ctx.args.split()
    parts: list[str | CommandLine]
    if not args:
        commits = git.log(max_entries=10, message_prefix=_DREAM_COMMIT_PREFIX)
        if commits:
            parts = [
                line("dream.restore.list"), "",
                *(f"- `{c.sha}` {c.timestamp} - {c.subject()}" for c in commits),
                "", line("dream.restore.guide"),
            ]
        else:
            parts = [line("dream.restore.empty")]
    else:
        sha = args[0]
        change = git.show_commit_diff(sha, message_prefix=_DREAM_COMMIT_PREFIX)
        if not change:
            parts = [line("dream.restore.not_found", sha=sha)]
        else:
            try:
                async with store.dream_lock:
                    new_sha = git.revert(sha, message_prefix=_DREAM_COMMIT_PREFIX)
            except GitStoreDirtyError as exc:
                reason = (line("dream.restore.dirty_file", sha=sha, path=exc.path) if exc.path is not None
                          else line("dream.restore.staged", sha=sha))
                parts = [reason, "", line("dream.restore.retry")]
            else:
                if new_sha:
                    files = ", ".join(f"`{path}`" for path in _extract_changed_files(change[1]))
                    parts = [
                        line("dream.restore.done", sha=sha, new_sha=new_sha),
                        line("dream.restore.files", files=files) if files else line("dream.restore.no_files"),
                        "", line("dream.restore.inspect", sha=new_sha),
                    ]
                else:
                    parts = [line("dream.restore.no_parent", sha=sha)]
    return command_reply(ctx.msg, "/dream-restore", *parts)


async def cmd_pairing(ctx: CommandContext) -> OutboundMessage:
    """List, approve, deny or revoke pairing requests."""
    from nanobot.pairing import PAIRING_COMMAND_META_KEY
    from nanobot.pairing.command import pairing_command_lines
    from nanobot.pairing.events import PairingChanged

    def changed() -> None:
        ctx.loop.bus.publish_nowait(PairingChanged())

    parts = pairing_command_lines(ctx.msg.channel, ctx.args, on_change=changed)
    return command_reply(ctx.msg, "/pairing", *parts, metadata={PAIRING_COMMAND_META_KEY: True})


async def cmd_skill(ctx: CommandContext) -> OutboundMessage:
    """List all enabled skills (name and description only)."""
    loop = ctx.loop
    skills = loop.context.skills.list_skills(filter_unavailable=False)
    if not skills:
        return command_reply(ctx.msg, "/skill", line("skill.empty"))
    return command_reply(ctx.msg, "/skill", line("skill.list", count=len(skills)), "", *(
        line("skill.item", name=entry["name"], description=loop.context.skills.get_skill_description(entry["name"]))
        for entry in skills
    ))


async def cmd_trigger(ctx: CommandContext) -> OutboundMessage:
    """Create a local trigger bound to the current session."""
    name = ctx.args.strip()
    if not name:
        return command_reply(ctx.msg, "/trigger", line("trigger.usage"), "", line("palette.trigger.description"))

    from nanobot.triggers.local_store import LocalTriggerStore

    loop = ctx.loop
    store = loop.local_trigger_store
    if store is None:
        store = LocalTriggerStore(loop.workspace)

    trigger = store.create(
        name=name,
        channel=ctx.msg.channel,
        chat_id=ctx.msg.chat_id,
        session_key=ctx.key,
        sender_id="trigger",
        origin_metadata=dict(ctx.msg.metadata or {}),
    )
    return command_reply(ctx.msg, "/trigger", line("trigger.created", name=trigger.name),
                         line("trigger.id", id=trigger.id), "", line("trigger.command"),
                         f'nanobot trigger {trigger.id} "message"')


def _help_parts(specs: tuple[BuiltinCommandSpec, ...]) -> list[CommandLine | str]:
    parts: list[CommandLine | str] = [line("help.title")]
    for spec in specs:
        syntax = f"{spec.command} {spec.arg_hint}" if spec.arg_hint else spec.command
        prefix = f"{syntax} — "
        parts.append(
            CommandLine(prefix=prefix, key=spec.description_key, values={})
            if spec.description_key else prefix + spec.description
        )
    return parts


async def cmd_help(ctx: CommandContext) -> OutboundMessage:
    specs = ctx.loop.commands.specs
    if ctx.msg.channel == "websocket" and ctx.msg.metadata.get("webui") is True:
        specs = tuple(spec for spec in specs if spec.command not in CHAT_UI_COMMAND_REPLACEMENTS)
    return command_reply(ctx.msg, "/help", *_help_parts(specs))


def build_help_text(specs: tuple[BuiltinCommandSpec, ...] = CORE_COMMAND_SPECS, *, locale: object = None) -> str:
    return render(tuple({"text": p} if isinstance(p, str) else p for p in _help_parts(specs)), locale)


def register_core_commands(router: CommandRouter) -> None:
    """Register slash commands owned by the core runtime."""
    for spec in CORE_COMMAND_SPECS:
        router.add_spec(spec)
    router.priority("/stop", cmd_stop)
    router.priority("/restart", cmd_restart)
    router.priority("/status", cmd_status)
    router.exact("/new", cmd_new)
    router.exact("/compact", cmd_compact, session_queue=True)
    router.exact("/status", cmd_status)
    router.exact("/model", cmd_model)
    router.prefix("/model ", cmd_model)
    router.exact("/trigger", cmd_trigger)
    router.prefix("/trigger ", cmd_trigger)
    router.exact("/dream", cmd_dream)
    router.exact("/dream-log", cmd_dream_log)
    router.prefix("/dream-log ", cmd_dream_log)
    router.exact("/dream-restore", cmd_dream_restore)
    router.prefix("/dream-restore ", cmd_dream_restore)
    router.exact("/dream-prompt", cmd_dream_prompt)
    router.prefix("/dream-prompt ", cmd_dream_prompt)
    router.exact("/evaluator-prompt", cmd_evaluator_prompt)
    router.prefix("/evaluator-prompt ", cmd_evaluator_prompt)
    router.exact("/skill", cmd_skill)
    router.exact("/help", cmd_help)
    router.exact("/pairing", cmd_pairing)
    router.prefix("/pairing ", cmd_pairing)
    router.exact(USER_SHELL_COMMAND, cmd_user_shell)
    router.prefix(f"{USER_SHELL_COMMAND} ", cmd_user_shell)
