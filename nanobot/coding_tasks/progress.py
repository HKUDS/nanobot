"""Live progress polling and summarization for coding tasks."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path

from nanobot.coding_tasks.manager import CodexWorkerManager
from nanobot.coding_tasks.reporting import detect_waiting_reason, inspect_repo_snapshot
from nanobot.coding_tasks.worker import CodexWorkerLauncher

_PROMPT_LINES = {"❯", "$", "%", "#", "sh-3.2$", "zsh%"}
_ERROR_HINTS = (
    "error:",
    "unsupported value",
    "operation not permitted",
    "must be readable",
)


@dataclass(slots=True)
class PlanProgress:
    """Completed vs remaining feature counts from PLAN.json."""

    completed: int
    remaining: int
    total: int

    @property
    def is_complete(self) -> bool:
        return self.total > 0 and self.remaining == 0


@dataclass(slots=True)
class TaskProgressReport:
    """Condensed task progress assembled from harness files and live worker output."""

    latest_note: str
    plan_progress: PlanProgress
    live_output: str
    branch_name: str
    recent_commit_summary: str
    summary: str


def build_notification_progress(report: TaskProgressReport, *, last_progress_summary: str = "") -> str:
    """Build a short proactive-notification summary from detailed task progress."""
    if waiting_reason := detect_waiting_reason(report.live_output):
        return _trim_summary(waiting_reason, limit=96)
    if live_output := _normalize_notification_candidate(report.live_output):
        return live_output
    if summary_progress := _extract_progress_from_summary(last_progress_summary):
        return summary_progress
    return ""


def extract_latest_progress_note(repo_path: str | Path) -> str:
    """Read PROGRESS.md and return the newest non-empty session note."""
    path = Path(repo_path) / "PROGRESS.md"
    if not path.exists():
        return ""

    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    if not text:
        return ""

    sections = [section.strip() for section in text.split("\n## ") if section.strip()]
    latest = sections[-1]
    lines = [line.strip("- ").strip() for line in latest.splitlines() if line.strip()]
    if len(lines) >= 2:
        return lines[1]
    return lines[0] if lines else ""


def summarize_plan_progress(repo_path: str | Path) -> PlanProgress:
    """Read PLAN.json and compute completed vs remaining counts."""
    path = Path(repo_path) / "PLAN.json"
    if not path.exists():
        return PlanProgress(completed=0, remaining=0, total=0)

    try:
        items = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return PlanProgress(completed=0, remaining=0, total=0)
    completed = sum(1 for item in items if item.get("passes"))
    total = len(items)
    return PlanProgress(completed=completed, remaining=max(total - completed, 0), total=total)


def build_task_progress_report(repo_path: str | Path, pane_output: str) -> TaskProgressReport:
    """Combine harness state and live pane output into a concise task report."""
    latest_note = extract_latest_progress_note(repo_path)
    plan_progress = summarize_plan_progress(repo_path)
    live_output = _extract_live_output(pane_output)
    repo_snapshot = inspect_repo_snapshot(repo_path)

    segments: list[str] = []
    if plan_progress.total:
        segments.append(
            f"已完成 {plan_progress.completed}/{plan_progress.total} 项，剩余 {plan_progress.remaining} 项"
        )
    if latest_note:
        segments.append(f"最近记录: {latest_note}")
    if live_output:
        segments.append(f"当前输出: {live_output}")
    summary = " | ".join(segments)

    return TaskProgressReport(
        latest_note=latest_note,
        plan_progress=plan_progress,
        live_output=live_output,
        branch_name=repo_snapshot.branch_name,
        recent_commit_summary=repo_snapshot.recent_commit_summary,
        summary=summary,
    )


class CodexProgressMonitor:
    """Poll tmux-backed Codex sessions and refresh persisted task summaries."""

    def __init__(self, manager: CodexWorkerManager, launcher: CodexWorkerLauncher) -> None:
        self.manager = manager
        self.launcher = launcher

    async def poll_task(self, task_id: str) -> TaskProgressReport:
        """Capture recent pane output and update the task progress summary."""
        task = self.manager.require_task(task_id)
        if self._should_close_missing_session(task):
            return self.refresh_task(task_id, pane_output="", session_missing=True)
        pane_output = ""
        if task.tmux_session:
            pane_output = await asyncio.to_thread(self.launcher.capture_pane, task.tmux_session)
        return self.refresh_task(task_id, pane_output=pane_output)

    def build_task_report(self, task_id: str) -> TaskProgressReport:
        """Build a report synchronously for status views and diagnostics."""
        task = self.manager.require_task(task_id)
        pane_output = ""
        if task.tmux_session:
            try:
                pane_output = self.launcher.capture_pane(task.tmux_session)
            except Exception:
                pane_output = ""
        return build_task_progress_report(task.repo_path, pane_output)

    def refresh_task(
        self,
        task_id: str,
        *,
        pane_output: str | None = None,
        session_missing: bool = False,
    ) -> TaskProgressReport:
        """Persist repo metadata and visible progress for lifecycle code paths."""
        task = self.manager.require_task(task_id)
        current_output = pane_output
        if current_output is None and task.tmux_session and not session_missing:
            try:
                current_output = self.launcher.capture_pane(task.tmux_session)
            except Exception:
                current_output = ""
        if session_missing:
            current_output = self._read_recent_log_output(task.id)
        report = build_task_progress_report(task.repo_path, current_output or "")
        self.manager.update_repo_metadata(
            task_id,
            branch_name=report.branch_name or None,
            recent_commit_summary=report.recent_commit_summary or None,
            latest_note=report.latest_note or None,
        )
        if report.plan_progress.is_complete and task.status in {"starting", "running", "waiting_user"}:
            completion_summary = report.latest_note or report.summary or "Repo harness completed"
            self.manager.mark_completed(task_id, summary=completion_summary)
            return report
        if session_missing and task.status in {"starting", "running", "waiting_user"}:
            failure_summary = self._build_missing_session_summary(task, report)
            self.manager.mark_failed(task_id, summary=failure_summary)
            return report
        if waiting_reason := detect_waiting_reason(report.live_output):
            self.manager.mark_waiting_user(task_id, summary=waiting_reason)
        if report.summary:
            self.manager.update_progress(task_id, report.summary)
        return report

    def _should_close_missing_session(self, task) -> bool:
        if task.status not in {"starting", "running", "waiting_user"}:
            return False
        if task.status == "waiting_user" and task.metadata.get("harness_conflict_reason"):
            return False
        if not task.tmux_session:
            return True
        has_session = getattr(self.launcher, "has_session", None)
        if not callable(has_session):
            return False
        return not has_session(task.tmux_session)

    def _read_recent_log_output(self, task_id: str, *, limit: int = 200) -> str:
        path = self.manager.workspace / "automation" / "coding" / "artifacts" / f"{task_id}.codex.log"
        if not path.exists():
            return ""
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return ""
        return "\n".join(lines[-limit:])

    def _build_missing_session_summary(self, task, report: TaskProgressReport) -> str:
        recent = build_notification_progress(report, last_progress_summary=task.last_progress_summary)
        if recent:
            return f"Worker session disappeared after launch; last known progress: {recent}"
        if report.latest_note:
            return f"Worker session disappeared after launch; latest repo note: {report.latest_note}"
        return "Worker session disappeared after launch; send `继续` or `/coding resume` to relaunch."


def _extract_live_output(pane_output: str) -> str:
    lines = [line.strip() for line in pane_output.splitlines() if line.strip()]
    if not lines:
        return ""
    for line in reversed(lines):
        if summary := _summarize_codex_event_line(line):
            return summary
    for line in reversed(lines):
        if _is_shell_noise_line(line):
            continue
        return _trim_summary(line)
    return ""


def _extract_progress_from_summary(summary: str) -> str:
    if not summary:
        return ""
    parts = [part.strip() for part in summary.split(" | ") if part.strip()]
    for part in parts:
        if part.startswith("当前输出:"):
            if live_output := _normalize_notification_candidate(part.removeprefix("当前输出:").strip()):
                return live_output
    for part in parts:
        if part.startswith("最近记录:"):
            if note := _normalize_notification_candidate(part.removeprefix("最近记录:").strip(), prefer_clause=True):
                return note
    if len(parts) == 1 and not summary.startswith("已完成 "):
        return _normalize_notification_candidate(summary, prefer_clause=True)
    return ""


def _summarize_codex_event_line(line: str) -> str:
    try:
        payload = json.loads(line)
    except json.JSONDecodeError:
        return ""

    item = payload.get("item")
    if not isinstance(item, dict):
        return ""

    item_type = item.get("type")
    if item_type == "agent_message":
        return _trim_summary(str(item.get("text") or ""))
    if item_type == "command_execution":
        command = str(item.get("command") or "").strip()
        if command:
            return _trim_summary(f"执行命令: {command}")
    return ""


def _is_shell_noise_line(line: str) -> bool:
    if line in _PROMPT_LINES:
        return True
    if (line.startswith("~/") or line.startswith("/Users/")) and " " not in line:
        return True
    return False


def _normalize_notification_candidate(text: str, *, prefer_clause: bool = False) -> str:
    compact = " ".join(text.split())
    if not compact or _is_shell_noise_line(compact):
        return ""
    if compact.startswith("已完成 ") and "最近记录:" not in compact and "当前输出:" not in compact:
        return ""
    if prefer_clause:
        compact = _first_clause(compact)
    return _trim_summary(compact, limit=96)


def _first_clause(text: str) -> str:
    for separator in ("：", ":", "。", ";", "；", "!", "！", "?", "？"):
        head, found, _tail = text.partition(separator)
        if found and head.strip():
            return head.strip()
    return text


def _trim_summary(text: str, limit: int = 160) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3] + "..."
