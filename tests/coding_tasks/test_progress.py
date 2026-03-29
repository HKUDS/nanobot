from __future__ import annotations

from pathlib import Path

import pytest

from nanobot.coding_tasks.manager import CodexWorkerManager
from nanobot.coding_tasks.progress import (
    CodexProgressMonitor,
    build_task_progress_report,
    extract_latest_progress_note,
    summarize_plan_progress,
)
from nanobot.coding_tasks.store import CodingTaskStore


def _prepare_repo(repo: Path) -> None:
    repo.mkdir()
    (repo / "PROGRESS.md").write_text(
        "## Session update - 1\n- Did first thing\n\n## Session update - 2\n- Fixed second thing\n",
        encoding="utf-8",
    )
    (repo / "PLAN.json").write_text(
        '[{"id": 1, "passes": true}, {"id": 2, "passes": false}, {"id": 3, "passes": true}]',
        encoding="utf-8",
    )


def test_extract_latest_progress_note_returns_newest_session_note(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _prepare_repo(repo)

    latest = extract_latest_progress_note(repo)

    assert latest == "Fixed second thing"


def test_summarize_plan_progress_counts_completed_and_remaining(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _prepare_repo(repo)

    progress = summarize_plan_progress(repo)

    assert progress.completed == 2
    assert progress.remaining == 1
    assert progress.total == 3


def test_build_task_progress_report_combines_harness_and_pane_output(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _prepare_repo(repo)

    report = build_task_progress_report(repo, "line one\nRunning pytest tests/coding_tasks\n")

    assert "已完成 2/3 项，剩余 1 项" in report.summary
    assert "最近记录: Fixed second thing" in report.summary
    assert "当前输出: Running pytest tests/coding_tasks" in report.summary


@pytest.mark.asyncio
async def test_poll_task_updates_progress_summary_and_timestamp(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    store = CodingTaskStore(workspace / "automation" / "coding" / "tasks.json")
    manager = CodexWorkerManager(workspace, store)
    repo = tmp_path / "repo"
    _prepare_repo(repo)
    task = manager.create_task(repo_path=str(repo), goal="Summarize progress")
    task = manager.mark_starting(task.id, summary="Launching")
    task = manager.mark_running(task.id, summary="Working")

    class _FakeLauncher:
        def capture_pane(self, session: str) -> str:
            assert session == task.tmux_session
            return "still running\nWaiting for user confirmation\n"

    monitor = CodexProgressMonitor(manager, _FakeLauncher())  # type: ignore[arg-type]
    report = await monitor.poll_task(task.id)

    refreshed = store.get_task(task.id)
    assert refreshed is not None
    assert refreshed.last_progress_summary == report.summary
    assert refreshed.last_progress_at_ms is not None
    assert "Waiting for user confirmation" in refreshed.last_progress_summary
