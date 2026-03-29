from __future__ import annotations

from pathlib import Path
import subprocess

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


def _init_git_repo(repo: Path) -> None:
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True, capture_output=True)
    (repo / "tracked.txt").write_text("tracked\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "seed repo"], cwd=repo, check=True, capture_output=True)


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


def test_build_task_progress_report_summarizes_codex_json_events(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _prepare_repo(repo)

    pane_output = (
        '{"type":"thread.started","thread_id":"abc"}\n'
        '{"type":"item.completed","item":{"id":"item_4","type":"command_execution",'
        '"command":"/bin/zsh -lc \\"cat /tmp/example/SKILL.md\\"","aggregated_output":"very long output"}}\n'
    )

    report = build_task_progress_report(repo, pane_output)

    assert "当前输出: 执行命令: /bin/zsh -lc" in report.summary
    assert "aggregated_output" not in report.summary


def test_build_task_report_is_read_only_for_task_metadata(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    store = CodingTaskStore(workspace / "automation" / "coding" / "tasks.json")
    manager = CodexWorkerManager(workspace, store)
    repo = tmp_path / "repo"
    _prepare_repo(repo)
    _init_git_repo(repo)
    task = manager.create_task(repo_path=str(repo), goal="Read only")
    task = manager.mark_starting(task.id, summary="Launching")
    task = manager.mark_running(task.id, summary="Working")

    class _FakeLauncher:
        def capture_pane(self, session: str) -> str:
            assert session == task.tmux_session
            return "Running pytest\n"

    monitor = CodexProgressMonitor(manager, _FakeLauncher())  # type: ignore[arg-type]
    report = monitor.build_task_report(task.id)

    refreshed = store.get_task(task.id)
    assert refreshed is not None
    assert refreshed.branch_name is None
    assert refreshed.metadata.get("recent_commit_summary") is None
    assert report.branch_name == "main"
    assert "seed repo" in report.recent_commit_summary


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


@pytest.mark.asyncio
async def test_poll_task_marks_waiting_user_when_live_output_requests_confirmation(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    store = CodingTaskStore(workspace / "automation" / "coding" / "tasks.json")
    manager = CodexWorkerManager(workspace, store)
    repo = tmp_path / "repo"
    _prepare_repo(repo)
    task = manager.create_task(repo_path=str(repo), goal="Need confirmation")
    task = manager.mark_starting(task.id, summary="Launching")
    task = manager.mark_running(task.id, summary="Working")

    class _FakeLauncher:
        def capture_pane(self, session: str) -> str:
            assert session == task.tmux_session
            return "Need plan confirmation before edits\n"

    monitor = CodexProgressMonitor(manager, _FakeLauncher())  # type: ignore[arg-type]
    await monitor.poll_task(task.id)

    refreshed = store.get_task(task.id)
    assert refreshed is not None
    assert refreshed.status == "waiting_user"
    assert "Need plan confirmation" in refreshed.last_progress_summary


@pytest.mark.asyncio
async def test_poll_task_persists_branch_and_recent_commit_metadata(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    store = CodingTaskStore(workspace / "automation" / "coding" / "tasks.json")
    manager = CodexWorkerManager(workspace, store)
    repo = tmp_path / "repo"
    _prepare_repo(repo)
    _init_git_repo(repo)
    task = manager.create_task(repo_path=str(repo), goal="Track metadata")
    task = manager.mark_starting(task.id, summary="Launching")
    task = manager.mark_running(task.id, summary="Working")

    class _FakeLauncher:
        def capture_pane(self, session: str) -> str:
            assert session == task.tmux_session
            return "Running pytest\n"

    monitor = CodexProgressMonitor(manager, _FakeLauncher())  # type: ignore[arg-type]
    await monitor.poll_task(task.id)

    refreshed = store.get_task(task.id)
    assert refreshed is not None
    assert refreshed.branch_name == "main"
    assert "seed repo" in refreshed.metadata.get("recent_commit_summary", "")


def test_refresh_task_persists_repo_metadata_without_status_view_side_effects(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    store = CodingTaskStore(workspace / "automation" / "coding" / "tasks.json")
    manager = CodexWorkerManager(workspace, store)
    repo = tmp_path / "repo"
    _prepare_repo(repo)
    _init_git_repo(repo)
    task = manager.create_task(repo_path=str(repo), goal="Refresh metadata")
    task = manager.mark_starting(task.id, summary="Launching")
    task = manager.mark_running(task.id, summary="Working")

    monitor = CodexProgressMonitor(manager, type("L", (), {})())  # type: ignore[arg-type]
    report = monitor.refresh_task(task.id, pane_output="Running pytest\n")

    refreshed = store.get_task(task.id)
    assert refreshed is not None
    assert refreshed.branch_name == "main"
    assert "seed repo" in refreshed.metadata.get("recent_commit_summary", "")
    assert refreshed.last_progress_summary == report.summary
