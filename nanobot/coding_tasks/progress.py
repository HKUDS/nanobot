"""Live progress polling and summarization for coding tasks."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path

from nanobot.coding_tasks.manager import CodexWorkerManager
from nanobot.coding_tasks.reporting import detect_waiting_reason, inspect_repo_snapshot
from nanobot.coding_tasks.worker import CodexWorkerLauncher


@dataclass(slots=True)
class PlanProgress:
    """Completed vs remaining feature counts from PLAN.json."""

    completed: int
    remaining: int
    total: int


@dataclass(slots=True)
class TaskProgressReport:
    """Condensed task progress assembled from harness files and live worker output."""

    latest_note: str
    plan_progress: PlanProgress
    live_output: str
    branch_name: str
    recent_commit_summary: str
    summary: str


def extract_latest_progress_note(repo_path: str | Path) -> str:
    """Read PROGRESS.md and return the newest non-empty session note."""
    path = Path(repo_path) / "PROGRESS.md"
    if not path.exists():
        return ""

    text = path.read_text(encoding="utf-8").strip()
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

    items = json.loads(path.read_text(encoding="utf-8"))
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

    def refresh_task(self, task_id: str, *, pane_output: str | None = None) -> TaskProgressReport:
        """Persist repo metadata and visible progress for lifecycle code paths."""
        task = self.manager.require_task(task_id)
        current_output = pane_output
        if current_output is None and task.tmux_session:
            try:
                current_output = self.launcher.capture_pane(task.tmux_session)
            except Exception:
                current_output = ""
        report = build_task_progress_report(task.repo_path, current_output or "")
        self.manager.update_repo_metadata(
            task_id,
            branch_name=report.branch_name or None,
            recent_commit_summary=report.recent_commit_summary or None,
            latest_note=report.latest_note or None,
        )
        if waiting_reason := detect_waiting_reason(report.live_output):
            self.manager.mark_waiting_user(task_id, summary=waiting_reason)
        if report.summary:
            self.manager.update_progress(task_id, report.summary)
        return report


def _extract_live_output(pane_output: str) -> str:
    lines = [line.strip() for line in pane_output.splitlines() if line.strip()]
    if not lines:
        return ""
    for line in reversed(lines):
        if summary := _summarize_codex_event_line(line):
            return summary
    return _trim_summary(lines[-1])


def _summarize_codex_event_line(line: str) -> str:
    try:
        payload = json.loads(line)
    except json.JSONDecodeError:
        return _trim_summary(line)

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


def _trim_summary(text: str, limit: int = 160) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3] + "..."
