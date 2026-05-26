"""Slash commands for skill evolution proposals and git history (E2 Step 3)."""

from __future__ import annotations

import difflib

from nanobot.agent.evolution.gepa_runner import GepaRunResult
from nanobot.agent.evolution.git_store import EvolutionGitStore
from nanobot.agent.evolution.gepa_status import (
    GepaRunStatus,
    GepaRunStore,
    GepaRunTrigger,
    gepa_run_in_progress,
)
from nanobot.config.schema import EvolutionConfig
from nanobot.agent.evolution.post_task import format_tool_calls_for_prompt
from nanobot.agent.evolution.proposals import ProposalMeta, ProposalStore
from nanobot.agent.evolution.trace_store import TraceStore
from nanobot.bus.events import OutboundMessage
from nanobot.command.router import CommandContext, CommandRouter
from nanobot.utils.gitstore import CommitInfo

_SKILL_MD_PREVIEW_CHARS = 4000


def _extract_changed_files(diff: str) -> list[str]:
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
        return "No tracked skill files changed."
    return ", ".join(f"`{path}`" for path in files)


def _text_reply(ctx: CommandContext, content: str) -> OutboundMessage:
    return OutboundMessage(
        channel=ctx.msg.channel,
        chat_id=ctx.msg.chat_id,
        content=content,
        metadata={"render_as": "text"},
    )


def _workspace(ctx: CommandContext):
    return ctx.loop.context.workspace


def _proposal_store(ctx: CommandContext) -> ProposalStore:
    return ProposalStore(_workspace(ctx))


def _git_store(ctx: CommandContext) -> EvolutionGitStore:
    return EvolutionGitStore(_workspace(ctx))


def _trace_store(ctx: CommandContext) -> TraceStore:
    return TraceStore(_workspace(ctx))


def _warm_skill_index(ctx: CommandContext) -> None:
    ctx.loop.context.warm_skill_index()


def _resolve_proposal_token(ctx: CommandContext) -> tuple[str | None, str | None]:
    token = ctx.args.strip().split()[0] if ctx.args.strip() else ""
    if not token:
        return None, "Usage: `{cmd} <proposal-id>`"
    proposal_id = _proposal_store(ctx).find_proposal_id(token)
    if proposal_id is None:
        return None, (
            f"Couldn't find proposal `{token}`.\n\n"
            "Use `/evolve-list` to list pending proposals."
        )
    return proposal_id, None


def _format_proposal_line(meta: ProposalMeta) -> str:
    short_id = meta.proposal_id[:8]
    return (
        f"- `{short_id}` **{meta.skill_name}** — "
        f"{meta.source}, confidence {meta.confidence:.2f}, {meta.created_at[:10]}"
    )


def _format_trace_summary(trace_store: TraceStore, trace_id: str) -> str:
    if not trace_id:
        return "(no linked trace)"
    trace = trace_store.get(trace_id)
    if trace is None:
        return f"(trace `{trace_id}` not found)"
    lines = [
        f"- Trace ID: `{trace.trace_id}`",
        f"- Session: `{trace.session_key}`",
        f"- Outcome: {trace.outcome} ({trace.stop_reason or 'n/a'})",
        f"- Tool calls: {trace.tool_call_count}",
        f"- Query: {trace.query.strip() or '(empty)'}",
        "- Tools:",
        format_tool_calls_for_prompt(trace.tool_calls),
    ]
    return "\n".join(lines)


def _format_trace_section(trace_store: TraceStore, trace_id: str) -> str:
    trace_ids = [item.strip() for item in trace_id.split(",") if item.strip()]
    if not trace_ids:
        return "(no linked trace)"
    if len(trace_ids) == 1:
        return _format_trace_summary(trace_store, trace_ids[0])
    blocks = [_format_trace_summary(trace_store, item) for item in trace_ids]
    return "\n\n".join(blocks)


def _format_gepa_meta_lines(meta: ProposalMeta) -> list[str]:
    if meta.resolved_proposal_kind() != "update":
        return []

    lines = [f"- Proposal kind: {meta.resolved_proposal_kind()}"]
    base_skill = meta.base_skill or meta.skill_name
    lines.append(f"- Base skill: `{base_skill}`")
    if meta.base_sha:
        lines.append(f"- Base SHA: `{meta.base_sha}`")
    if meta.evaluation_score is not None:
        lines.append(f"- Evaluation score: {meta.evaluation_score:.3f}")
    return lines


def format_gepa_completion_message(result: GepaRunResult) -> str | None:
    """User-visible summary when GEPA created one or more proposals."""
    if not result.proposals_created:
        return None
    count = len(result.proposals_created)
    noun = "proposal" if count == 1 else "proposals"
    lines = [f"{count} GEPA {noun} ready:"]
    for proposal_id in result.proposals_created:
        short = proposal_id[:8]
        lines.append(f"- `{short}` — `/evolve-show {short}`")
    return "\n".join(lines)


def resolve_gepa_notify_delivery(
    *,
    result: GepaRunResult,
    trigger: GepaRunTrigger,
    evolution: EvolutionConfig,
    notify_to: tuple[str, str] | None = None,
) -> tuple[str, str] | None:
    """Return ``(channel, chat_id)`` when a completion outbound should be sent."""
    if not result.proposals_created:
        return None
    if trigger == "slash":
        if notify_to and notify_to[0] and notify_to[1]:
            return notify_to
        return None
    if trigger == "cron":
        gepa = evolution.gepa
        if (
            gepa.notify_on_complete
            and gepa.notify_channel
            and gepa.notify_chat_id
        ):
            return gepa.notify_channel, gepa.notify_chat_id
        return None
    return None


def format_gepa_run_status(status: GepaRunStatus) -> str:
    """Format ``gepa_run.json`` state for slash commands and CLI."""
    if status.phase == "idle" and not status.run_id:
        return "GEPA is idle — no run recorded yet."

    lines = [f"GEPA status: {status.phase}"]
    if status.run_id:
        lines.append(f"- Run: `{status.run_id[:8]}`")
    if status.trigger:
        lines.append(f"- Trigger: {status.trigger}")
    if status.skill_name:
        lines.append(f"- Skill: `{status.skill_name}`")
    if status.started_at:
        lines.append(f"- Started: {status.started_at}")
    if status.finished_at and not gepa_run_in_progress(status):
        lines.append(f"- Finished: {status.finished_at}")
    if status.message:
        lines.append(f"- Message: {status.message}")
    if status.proposals_created:
        ids = ", ".join(f"`{item[:8]}`" for item in status.proposals_created)
        lines.append(f"- Proposals: {ids}")
    if status.traces_consumed:
        lines.append(f"- Traces consumed: {len(status.traces_consumed)}")
    if status.budget_usd_spent:
        lines.append(f"- Budget spent: ${status.budget_usd_spent:.2f}")
    if status.error:
        lines.append(f"- Error: {status.error}")

    if gepa_run_in_progress(status):
        lines.append("")
        lines.append("Run in progress — check again with `/evolve-status`.")
    elif status.phase == "completed" and status.proposals_created:
        lines.append("")
        lines.append("Inspect with `/evolve-show <id>`.")
    return "\n".join(lines)


def _format_active_skill_diff_summary(
    store: ProposalStore,
    meta: ProposalMeta,
    proposed_md: str,
    *,
    max_lines: int = 20,
) -> str | None:
    if meta.resolved_proposal_kind() != "update":
        return None
    if not store.workspace_skill_exists(meta.skill_name):
        return "Active skill not found in workspace; diff unavailable."

    active_path = store.skills_root / meta.skill_name / "SKILL.md"
    try:
        base_md = active_path.read_text(encoding="utf-8")
    except OSError:
        return "Active skill unreadable; diff unavailable."

    diff_lines = list(
        difflib.unified_diff(
            base_md.splitlines(),
            proposed_md.splitlines(),
            fromfile=f"skills/{meta.skill_name}/SKILL.md",
            tofile="proposal/SKILL.md",
            lineterm="",
            n=1,
        )
    )
    if not diff_lines:
        return "No changes from the active skill."
    if len(diff_lines) > max_lines:
        diff_lines = diff_lines[:max_lines] + ["… (diff truncated)"]
    return "\n".join(diff_lines)


def _format_evolve_log_content(
    commit: CommitInfo,
    diff: str,
    *,
    requested_sha: str | None = None,
) -> str:
    files_line = _format_changed_files(diff)
    lines = [
        "## Skill Evolution",
        "",
        "Here is the selected skill evolution change."
        if requested_sha
        else "Here is the latest skill evolution change.",
        "",
        f"- Commit: `{commit.sha}`",
        f"- Time: {commit.timestamp}",
        f"- Message: {commit.message.splitlines()[0]}",
        f"- Changed files: {files_line}",
    ]
    if diff:
        lines.extend([
            "",
            f"Use `/evolve-restore {commit.sha}` to undo this change.",
            "",
            "```diff",
            diff.rstrip(),
            "```",
        ])
    else:
        lines.extend([
            "",
            "This evolve commit has no file diff to display.",
        ])
    return "\n".join(lines)


def _format_evolve_restore_list(commits: list[CommitInfo]) -> str:
    lines = [
        "## Evolve Restore",
        "",
        "Choose a skill evolution version to restore. Latest first:",
        "",
    ]
    for commit in commits:
        lines.append(f"- `{commit.sha}` {commit.timestamp} - {commit.message.splitlines()[0]}")
    lines.extend([
        "",
        "Preview a version with `/evolve-log <sha>` before restoring it.",
        "Restore a version with `/evolve-restore <sha>`.",
    ])
    return "\n".join(lines)


async def cmd_evolve_list(ctx: CommandContext) -> OutboundMessage:
    """List pending skill proposals."""
    pending = _proposal_store(ctx).list_pending()
    if not pending:
        return _text_reply(
            ctx,
            "No pending skill proposals.\n\n"
            "PostTask will add proposals here when `auto_apply` is disabled.",
        )

    lines = [
        "## Pending Skill Proposals",
        "",
        f"{len(pending)} proposal(s) awaiting review:",
        "",
    ]
    lines.extend(_format_proposal_line(meta) for meta in pending)
    lines.extend([
        "",
        "Inspect one with `/evolve-show <id>`.",
        "Apply with `/evolve-apply <id>` or reject with `/evolve-reject <id>`.",
    ])
    return _text_reply(ctx, "\n".join(lines))


async def cmd_evolve_show(ctx: CommandContext) -> OutboundMessage:
    """Show proposal details and linked trace summary."""
    proposal_id, error = _resolve_proposal_token(ctx)
    if error:
        cmd = ctx.raw.split()[0]
        return _text_reply(ctx, error.format(cmd=cmd))

    detail = _proposal_store(ctx).get(proposal_id)
    if detail is None:
        return _text_reply(ctx, f"Couldn't load proposal `{proposal_id}`.")

    meta = detail.meta
    store = _proposal_store(ctx)
    skill_preview = detail.skill_md
    if len(skill_preview) > _SKILL_MD_PREVIEW_CHARS:
        skill_preview = skill_preview[:_SKILL_MD_PREVIEW_CHARS] + "\n\n… (truncated)"

    lines = [
        f"## Proposal `{meta.skill_name}`",
        "",
        f"- ID: `{meta.proposal_id}`",
        f"- Status: {meta.status}",
        f"- Source: {meta.source}",
        f"- Confidence: {meta.confidence:.2f}",
        f"- Created: {meta.created_at}",
    ]
    gepa_lines = _format_gepa_meta_lines(meta)
    if gepa_lines:
        lines.extend(gepa_lines)
    if meta.applied_at:
        lines.append(f"- Applied: {meta.applied_at}")
    if meta.rejected_at:
        lines.append(f"- Rejected: {meta.rejected_at}")
    if meta.rationale:
        lines.extend(["", "### Rationale", meta.rationale])
    diff_summary = _format_active_skill_diff_summary(store, meta, detail.skill_md)
    if diff_summary is not None:
        lines.extend(["", "### Active skill diff", "```diff", diff_summary, "```"])
    lines.extend([
        "",
        "### Trace",
        _format_trace_section(_trace_store(ctx), meta.trace_id),
        "",
        "### SKILL.md",
        "```markdown",
        skill_preview.rstrip(),
        "```",
    ])
    if meta.status == "pending":
        lines.extend([
            "",
            f"Apply with `/evolve-apply {meta.proposal_id[:8]}`.",
            f"Reject with `/evolve-reject {meta.proposal_id[:8]}`.",
        ])
    return _text_reply(ctx, "\n".join(lines))


async def cmd_evolve_apply(ctx: CommandContext) -> OutboundMessage:
    """Apply a pending proposal, commit to git, and rebuild the skill index."""
    proposal_id, error = _resolve_proposal_token(ctx)
    if error:
        cmd = ctx.raw.split()[0]
        return _text_reply(ctx, error.format(cmd=cmd))

    store = _proposal_store(ctx)
    git = _git_store(ctx)
    meta = store.read_meta(proposal_id)
    if meta is None:
        return _text_reply(
            ctx,
            f"Couldn't apply proposal `{proposal_id[:8]}`: proposal not found",
        )

    if meta.resolved_proposal_kind() == "update":
        result = store.apply_update(proposal_id, git_store=git)
    else:
        result = store.apply_and_commit(proposal_id, git_store=git)
    if not result.ok:
        return _text_reply(
            ctx,
            f"Couldn't apply proposal `{proposal_id[:8]}`: {result.skip_reason}",
        )

    _warm_skill_index(ctx)
    lines = [
        f"Applied skill **{result.skill_name}** to `{result.skill_path}`.",
        f"- Proposal: `{result.proposal_id[:8]}`",
    ]
    if result.commit_sha:
        lines.append(f"- Git commit: `{result.commit_sha}`")
    lines.extend([
        "",
        "The skill index has been refreshed.",
        "Use `/evolve-log` to inspect the git change.",
    ])
    return _text_reply(ctx, "\n".join(lines))


async def cmd_evolve_reject(ctx: CommandContext) -> OutboundMessage:
    """Reject a pending proposal."""
    proposal_id, error = _resolve_proposal_token(ctx)
    if error:
        cmd = ctx.raw.split()[0]
        return _text_reply(ctx, error.format(cmd=cmd))

    result = _proposal_store(ctx).reject(proposal_id)
    if not result.ok:
        return _text_reply(
            ctx,
            f"Couldn't reject proposal `{proposal_id[:8]}`: {result.skip_reason}",
        )

    return _text_reply(
        ctx,
        f"Rejected proposal **{result.skill_name}** (`{result.proposal_id[:8]}`).\n\n"
        f"Moved to `{result.skill_path}`.",
    )


async def cmd_evolve_log(ctx: CommandContext) -> OutboundMessage:
    """Show evolve git history or a specific commit diff."""
    git = _git_store(ctx)
    if not git.is_initialized():
        return _text_reply(
            ctx,
            "Evolution git history is not available because versioning is not initialized.",
        )

    args = ctx.args.strip()
    if args:
        sha = args.split()[0]
        result = git.show_commit_diff(sha)
        if not result:
            return _text_reply(
                ctx,
                f"Couldn't find evolve change `{sha}`.\n\n"
                "Use `/evolve-restore` to list recent versions, "
                "or `/evolve-log` to inspect the latest one.",
            )
        commit, diff = result
        content = _format_evolve_log_content(commit, diff, requested_sha=sha)
    else:
        commits = git.log(max_entries=1)
        if not commits:
            return _text_reply(ctx, "No skill evolution commits yet.")
        result = git.show_commit_diff(commits[0].sha)
        if not result:
            return _text_reply(ctx, "No skill evolution commits yet.")
        commit, diff = result
        content = _format_evolve_log_content(commit, diff)

    return _text_reply(ctx, content)


async def cmd_evolve_restore(ctx: CommandContext) -> OutboundMessage:
    """List or restore evolve git commits."""
    git = _git_store(ctx)
    if not git.is_initialized():
        return _text_reply(
            ctx,
            "Evolution git history is not available because versioning is not initialized.",
        )

    args = ctx.args.strip()
    if not args:
        commits = git.log(max_entries=10)
        if not commits:
            content = "No skill evolution commits to restore yet."
        else:
            content = _format_evolve_restore_list(commits)
        return _text_reply(ctx, content)

    sha = args.split()[0]
    result = git.show_commit_diff(sha)
    changed_files = _format_changed_files(result[1]) if result else "the tracked skill files"
    new_sha = git.restore(sha)
    if not new_sha:
        return _text_reply(
            ctx,
            f"Couldn't restore evolve change `{sha}`.\n\n"
            "It may not exist, may not be an evolve commit, "
            "or may be the first saved version with no earlier state to restore.",
        )

    _warm_skill_index(ctx)
    content = (
        f"Restored workspace skills to the state before `{sha}`.\n\n"
        f"- New safety commit: `{new_sha}`\n"
        f"- Restored files: {changed_files}\n\n"
        "The skill index has been refreshed.\n"
        f"Use `/evolve-log {new_sha}` to inspect the restore diff."
    )
    return _text_reply(ctx, content)


async def cmd_evolve_run(ctx: CommandContext) -> OutboundMessage:
    """Start a background GEPA optimization run."""
    loop = ctx.loop
    evolution = getattr(loop, "_evolution", None)
    if evolution is None or not evolution.gepa_enabled():
        return _text_reply(
            ctx,
            "GEPA is disabled in config (`agents.defaults.evolution.gepa.enable`).",
        )

    if gepa_run_in_progress(GepaRunStore(_workspace(ctx)).get()):
        return _text_reply(
            ctx,
            "GEPA is already running. Check `/evolve-status`.",
        )

    skill_name = ctx.args.strip().split()[0] if ctx.args.strip() else None
    schedule = getattr(loop, "_schedule_gepa_run", None)
    if schedule is None:
        return _text_reply(ctx, "GEPA runner is not available on this agent loop.")

    schedule(
        skill_name=skill_name,
        trigger="slash",
        notify_to=(ctx.msg.channel, ctx.msg.chat_id),
    )
    return _text_reply(ctx, "GEPA run started. Check `/evolve-status`.")


async def cmd_evolve_status(ctx: CommandContext) -> OutboundMessage:
    """Show the latest GEPA run status."""
    status = GepaRunStore(_workspace(ctx)).get()
    return _text_reply(ctx, format_gepa_run_status(status))


def register_evolve_commands(router: CommandRouter) -> None:
    """Register `/evolve-*` slash commands."""
    router.exact("/evolve-list", cmd_evolve_list)
    router.exact("/evolve-show", cmd_evolve_show)
    router.prefix("/evolve-show ", cmd_evolve_show)
    router.exact("/evolve-apply", cmd_evolve_apply)
    router.prefix("/evolve-apply ", cmd_evolve_apply)
    router.exact("/evolve-reject", cmd_evolve_reject)
    router.prefix("/evolve-reject ", cmd_evolve_reject)
    router.exact("/evolve-log", cmd_evolve_log)
    router.prefix("/evolve-log ", cmd_evolve_log)
    router.exact("/evolve-restore", cmd_evolve_restore)
    router.prefix("/evolve-restore ", cmd_evolve_restore)
    router.exact("/evolve-run", cmd_evolve_run)
    router.prefix("/evolve-run ", cmd_evolve_run)
    router.exact("/evolve-status", cmd_evolve_status)
