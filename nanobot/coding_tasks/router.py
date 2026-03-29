"""Routing helpers for coding-task chat commands."""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from pathlib import Path

from nanobot.bus.events import OutboundMessage
from nanobot.command.router import CommandContext, CommandRouter
from nanobot.coding_tasks.manager import CodexWorkerManager
from nanobot.coding_tasks.progress import CodexProgressMonitor
from nanobot.coding_tasks.worker import CodexWorkerLauncher

_START_PREFIX = "开始编程"
_STATUS_COMMANDS = {"状态"}
_RESUME_COMMANDS = {"继续"}
_CANCEL_COMMANDS = {"取消"}
_STOP_COMMANDS = {"停止"}

_FIELD_PATTERNS = {
    "repo_path": re.compile(r"^(?:仓库|repo|repo_path|路径)\s*[:：=]\s*(.+)$", re.IGNORECASE),
    "goal": re.compile(r"^(?:目标|goal|需求|任务)\s*[:：=]\s*(.+)$", re.IGNORECASE),
    "title": re.compile(r"^(?:标题|title|名称|name)\s*[:：=]\s*(.+)$", re.IGNORECASE),
}


@dataclass(slots=True)
class ParsedCodingTaskRequest:
    """Structured request extracted from a natural-language chat message."""

    repo_path: str
    goal: str
    title: str | None = None


def is_start_coding_request(text: str) -> bool:
    """Return True when a message asks nanobot to start a coding task."""
    return text.strip().startswith(_START_PREFIX)


def parse_start_coding_request(text: str) -> ParsedCodingTaskRequest | None:
    """Parse a natural-language start request into repo path and goal."""
    body = text.strip()
    if not body.startswith(_START_PREFIX):
        return None

    body = body[len(_START_PREFIX) :].strip()
    body = body.lstrip(":：").strip()
    if not body:
        return None

    fields: dict[str, str] = {}
    for line in (line.strip() for line in body.splitlines()):
        if not line:
            continue
        for key, pattern in _FIELD_PATTERNS.items():
            match = pattern.match(line)
            if match:
                fields[key] = match.group(1).strip()
                break

    repo_path = fields.get("repo_path")
    goal = fields.get("goal")
    title = fields.get("title") or None

    if repo_path and goal:
        return ParsedCodingTaskRequest(repo_path=repo_path, goal=goal, title=title)

    try:
        tokens = shlex.split(body)
    except ValueError:
        tokens = body.split()

    if not tokens:
        return None

    candidate_repo = tokens[0].strip()
    if not _looks_like_repo_path(candidate_repo):
        return None

    goal = " ".join(tokens[1:]).strip()
    if not goal:
        return None

    return ParsedCodingTaskRequest(repo_path=candidate_repo, goal=goal, title=title)


def validate_repo_path(repo_path: str) -> tuple[str | None, str | None]:
    """Validate a local repository path before creating a coding task."""
    raw = repo_path.strip()
    if not raw:
        return None, "仓库路径不能为空。"
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", raw):
        return None, "当前只支持本地仓库路径，不支持 URL。"

    resolved = Path(raw).expanduser()
    if not resolved.exists():
        return None, f"仓库路径不存在: {resolved}"
    if not resolved.is_dir():
        return None, f"仓库路径不是目录: {resolved}"
    return str(resolved), None


def register_coding_task_commands(
    router: CommandRouter,
    manager: CodexWorkerManager,
    *,
    launcher: CodexWorkerLauncher | None = None,
    monitor: CodexProgressMonitor | None = None,
) -> None:
    """Register chat-level interceptors for coding-task lifecycle actions."""
    router.intercept(_make_start_coding_handler(manager))
    router.intercept(_make_control_handler(manager, launcher=launcher, monitor=monitor))


def _make_start_coding_handler(manager: CodexWorkerManager):
    async def _handle_start_coding(ctx: CommandContext) -> OutboundMessage | None:
        msg = ctx.msg
        if msg.channel != "telegram":
            return None
        if msg.metadata.get("is_group", True):
            return None
        if not is_start_coding_request(ctx.raw):
            return None

        parsed = parse_start_coding_request(ctx.raw)
        if parsed is None:
            return OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content=(
                    "请用以下格式创建编程任务：\n"
                    "开始编程 仓库路径 任务目标\n\n"
                    "或：\n"
                    "开始编程\n"
                    "仓库: /path/to/repo\n"
                    "目标: 修复某个问题"
                ),
                metadata={"render_as": "text"},
            )

        if active_task := manager.latest_active_task():
            return OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content=(
                    "当前已有一个活跃的编程任务，MVP 模式下一次只支持一个。\n"
                    f"任务ID: {active_task.id}\n"
                    f"状态: {active_task.status}\n"
                    f"仓库: {active_task.repo_path}\n"
                    "请先发送“状态”查看进度，或发送“取消”结束当前任务。"
                ),
                metadata={"render_as": "text"},
            )

        repo_path, validation_error = validate_repo_path(parsed.repo_path)
        if validation_error:
            return OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content=validation_error,
                metadata={"render_as": "text"},
            )

        task = manager.create_task(
            repo_path=repo_path,
            goal=parsed.goal,
            title=parsed.title,
            metadata={
                "origin_channel": msg.channel,
                "origin_chat_id": msg.chat_id,
                "origin_session_key": msg.session_key,
                "requested_via": "telegram_private_chat",
                "message_id": msg.metadata.get("message_id"),
            },
        )
        return OutboundMessage(
            channel=msg.channel,
            chat_id=msg.chat_id,
            content=(
                "已创建编程任务\n"
                f"任务ID: {task.id}\n"
                f"状态: {task.status}\n"
                f"仓库: {task.repo_path}\n"
                f"目标: {task.goal}"
            ),
            metadata={"render_as": "text"},
        )

    return _handle_start_coding


def _make_control_handler(
    manager: CodexWorkerManager,
    *,
    launcher: CodexWorkerLauncher | None = None,
    monitor: CodexProgressMonitor | None = None,
):
    async def _handle_control(ctx: CommandContext) -> OutboundMessage | None:
        msg = ctx.msg
        if msg.channel != "telegram":
            return None
        if msg.metadata.get("is_group", True):
            return None

        command = ctx.raw.strip()
        if command not in _STATUS_COMMANDS | _RESUME_COMMANDS | _CANCEL_COMMANDS | _STOP_COMMANDS:
            return None

        task = manager.latest_active_task_for_origin(msg.channel, msg.chat_id)
        if task is None:
            latest_origin_tasks = manager.tasks_for_origin(msg.channel, msg.chat_id)
            latest_origin = latest_origin_tasks[0] if latest_origin_tasks else None
            if command in _RESUME_COMMANDS and latest_origin and latest_origin.status == "cancelled":
                return OutboundMessage(
                    channel=msg.channel,
                    chat_id=msg.chat_id,
                    content=(
                        "最近的编程任务已经取消，不能直接继续。\n"
                        f"任务ID: {latest_origin.id}\n"
                        "请重新发送“开始编程 ...”显式创建新任务。"
                    ),
                    metadata={"render_as": "text"},
                )
            return OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content="当前私聊里还没有可控制的编程任务。先发送“开始编程 ...”创建一个任务。",
                metadata={"render_as": "text"},
            )

        if command in _STATUS_COMMANDS:
            report = monitor.build_task_report(task.id) if monitor else None
            return OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content=_format_task_status(
                    task,
                    report_summary=report.summary if report else "",
                    recoverable=task.id in {item.id for item in manager.recoverable_tasks()},
                ),
                metadata={"render_as": "text"},
            )

        if command in _CANCEL_COMMANDS:
            manager.record_user_control(task.id, "cancel")
            if launcher:
                try:
                    launcher.interrupt_task(task.id)
                except Exception:
                    pass
            updated = manager.cancel_task(task.id, summary="Cancelled from Telegram private chat")
            return OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content=(
                    "已取消编程任务\n"
                    f"任务ID: {updated.id}\n"
                    f"状态: {updated.status}\n"
                    f"仓库: {updated.repo_path}"
                ),
                metadata={"render_as": "text"},
            )

        if command in _STOP_COMMANDS:
            if launcher:
                launcher.interrupt_task(task.id)
            manager.record_user_control(task.id, "stop")
            updated = manager.mark_waiting_user(task.id, summary="Stopped from Telegram private chat")
            return OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content=(
                    "已停止编程任务\n"
                    f"任务ID: {updated.id}\n"
                    f"状态: {updated.status}\n"
                    f"仓库: {updated.repo_path}"
                ),
                metadata={"render_as": "text"},
            )

        if task.status in {"waiting_user", "failed"}:
            manager.record_user_control(task.id, "resume")
            if launcher:
                launched = launcher.launch_task(task.id)
                updated = launched.task
                reused_text = "yes" if launched.session_reused else "no"
                session_note = f"\n复用 tmux: {reused_text}"
            else:
                updated = manager.mark_starting(task.id, summary="Resumed from Telegram private chat")
                session_note = ""
            return OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content=(
                    "已继续编程任务\n"
                    f"任务ID: {updated.id}\n"
                    f"状态: {updated.status}\n"
                    f"仓库: {updated.repo_path}"
                    f"{session_note}"
                ),
                metadata={"render_as": "text"},
            )

        return OutboundMessage(
            channel=msg.channel,
            chat_id=msg.chat_id,
            content=_format_task_status(
                task,
                note="当前编程任务不需要继续操作",
                recoverable=task.id in {item.id for item in manager.recoverable_tasks()},
            ),
            metadata={"render_as": "text"},
        )

    return _handle_control


def _format_task_status(task, *, report_summary: str = "", note: str = "当前编程任务状态", recoverable: bool | None = None) -> str:
    lines = [
        note,
        f"任务ID: {task.id}",
        f"状态: {task.status}",
        f"仓库: {task.repo_path}",
        f"目标: {task.goal}",
    ]
    if recoverable is not None:
        lines.append(f"可恢复: {'yes' if recoverable else 'no'}")
    if task.last_progress_summary:
        lines.append(f"最近进展: {task.last_progress_summary}")
    if report_summary:
        lines.append(f"Live report: {report_summary}")
    if task.tmux_session:
        lines.append(f"tmux: {task.tmux_session}")
    return "\n".join(lines)


def _looks_like_repo_path(token: str) -> bool:
    return token.startswith(("/", "~", "./", "../")) or "/" in token
