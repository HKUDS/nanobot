"""Repo metadata inspection and user-facing coding task reports."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from nanobot.coding_tasks.types import CodingTask

_WAITING_PATTERNS = (
    "waiting for user",
    "waiting for approval",
    "need approval",
    "need plan confirmation",
    "waiting for confirmation",
)


@dataclass(slots=True)
class RepoSnapshot:
    """Recent repo metadata useful for status and completion reporting."""

    branch_name: str = ""
    recent_commit_summary: str = ""


def inspect_repo_snapshot(repo_path: str | Path) -> RepoSnapshot:
    """Inspect git branch and latest commit summary when available."""
    root = Path(repo_path)
    branch = _run_git(root, ["rev-parse", "--abbrev-ref", "HEAD"])
    commit = _run_git(root, ["log", "--oneline", "-1"])
    return RepoSnapshot(branch_name=branch, recent_commit_summary=commit)


def detect_waiting_reason(text: str) -> str:
    """Extract a human-facing waiting reason from live output when present."""
    lowered = text.lower()
    for pattern in _WAITING_PATTERNS:
        if pattern in lowered:
            return text.strip()
    return ""


def build_completion_report(task: CodingTask) -> str:
    """Build a completion summary for CLI or Telegram delivery."""
    lines = [
        "编程任务已完成",
        f"任务ID: {task.id}",
        f"结果: {task.last_progress_summary or 'Completed'}",
    ]
    if task.branch_name:
        lines.append(f"分支: {task.branch_name}")
    if recent_commit := task.metadata.get("recent_commit_summary"):
        lines.append(f"最近提交: {recent_commit}")
    return "\n".join(lines)


def build_failure_report(task: CodingTask) -> str:
    """Build a failure summary with resume guidance."""
    lines = [
        "编程任务失败",
        f"任务ID: {task.id}",
        f"最近成功步骤: {task.metadata.get('latest_note') or task.last_progress_summary or '-'}",
        f"当前阻塞: {task.last_progress_summary or '-'}",
        f"恢复建议: 发送“继续”或运行 `nanobot coding-task run {task.id}`",
    ]
    return "\n".join(lines)


def build_waiting_user_report(task: CodingTask) -> str:
    """Build a report for tasks waiting on explicit human input."""
    if task.metadata.get("harness_conflict_reason") == "repo_active_harness":
        lines = [
            "仓库里已有未完成的 harness",
            f"任务ID: {task.id}",
        ]
        if existing := task.metadata.get("existing_harness_summary"):
            lines.append(f"旧任务摘要: {existing}")
        lines.append(f"你的新目标: {task.goal}")
        lines.append("下一步: 回复“继续旧任务”继续原来的 harness，回复“按新任务开始”按这次的新目标启动，或回复“取消”终止。")
        return "\n".join(lines)

    lines = [
        "编程任务等待你的确认",
        f"任务ID: {task.id}",
        f"等待原因: {task.last_progress_summary or '-'}",
        "下一步: 回复“继续”恢复，或回复“取消”终止。",
    ]
    return "\n".join(lines)


def _run_git(repo_path: Path, args: list[str]) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=True,
        )
    except Exception:
        return ""
    return (result.stdout or "").strip()
