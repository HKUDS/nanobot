from __future__ import annotations

import subprocess
from pathlib import Path

from nanobot.coding_tasks.manager import CodexWorkerManager
from nanobot.coding_tasks.store import CodingTaskStore
from nanobot.coding_tasks.worker import CodexWorkerLauncher


class _FakeRunner:
    def __init__(self, *, has_session: bool, capture_output: str = "") -> None:
        self.has_session = has_session
        self.capture_output = capture_output
        self.commands: list[list[str]] = []

    def __call__(self, cmd: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
        self.commands.append(cmd)
        if "has-session" in cmd:
            return subprocess.CompletedProcess(cmd, 0 if self.has_session else 1, "", "")
        if "capture-pane" in cmd:
            return subprocess.CompletedProcess(cmd, 0, self.capture_output, "")
        return subprocess.CompletedProcess(cmd, 0, "", "")


def _make_launcher(tmp_path: Path, *, has_session: bool, capture_output: str = ""):
    store = CodingTaskStore(tmp_path / "automation" / "coding" / "tasks.json")
    manager = CodexWorkerManager(tmp_path, store)
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "PLAN.json").write_text('[{"id": 1, "passes": false}]', encoding="utf-8")
    (repo / "PROGRESS.md").write_text("## Session update\n- Continue old task\n", encoding="utf-8")
    (repo / "init.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    task = manager.create_task(repo_path=str(repo), goal="Implement worker launch")
    fake_runner = _FakeRunner(has_session=has_session, capture_output=capture_output)
    launcher = CodexWorkerLauncher(tmp_path, manager, runner=fake_runner)
    return launcher, task, fake_runner


def test_launch_task_creates_tmux_session_and_marks_task_starting(tmp_path: Path) -> None:
    launcher, task, fake_runner = _make_launcher(
        tmp_path,
        has_session=False,
        capture_output='{"session_id":"sess-123"}\n',
    )

    result = launcher.launch_task(task.id)

    assert result.task.status == "starting"
    assert result.task.harness_state == "active"
    assert result.session_reused is False
    assert result.session_hint == "sess-123"
    assert Path(result.prompt_path).exists()
    assert Path(result.launch_script_path).exists()
    assert any("new-session" in cmd for cmd in fake_runner.commands)
    assert any("/bin/sh" in part for cmd in fake_runner.commands if "new-session" in cmd for part in cmd)
    assert any(tmp_path.as_posix() == part for cmd in fake_runner.commands if "new-session" in cmd for part in cmd)
    assert not any("respawn-pane" in cmd for cmd in fake_runner.commands)


def test_launch_task_reuses_existing_tmux_session_without_new_session(tmp_path: Path) -> None:
    launcher, task, fake_runner = _make_launcher(tmp_path, has_session=True)

    result = launcher.launch_task(task.id)

    assert result.session_reused is True
    assert not any("new-session" in cmd for cmd in fake_runner.commands)
    assert any("respawn-pane" in cmd for cmd in fake_runner.commands)
    assert any(tmp_path.as_posix() == part for cmd in fake_runner.commands if "respawn-pane" in cmd for part in cmd)


def test_build_exec_command_uses_task_launch_script(tmp_path: Path) -> None:
    launcher, task, _fake_runner = _make_launcher(tmp_path, has_session=False)
    launch_script_path = Path(tmp_path / "task.launch.sh")

    command = launcher.build_exec_command(task, launch_script_path)

    assert command == f"/bin/sh {launch_script_path}"


def test_launcher_defaults_to_workspace_scoped_tmux_socket(tmp_path: Path) -> None:
    launcher, _task, _fake_runner = _make_launcher(tmp_path, has_session=False)

    assert launcher.socket_path == str(tmp_path / "automation" / "coding" / "tmux.sock")


def test_build_launch_script_wraps_codex_with_isolated_shell_and_log_capture(tmp_path: Path) -> None:
    launcher, task, _fake_runner = _make_launcher(tmp_path, has_session=False)
    prompt_path = Path(tmp_path / "prompt.txt")
    log_path = Path(tmp_path / "task.log")

    script = launcher.build_launch_script(task, prompt_path, log_path)

    assert script.startswith("#!/bin/sh")
    assert "env -i" in script
    assert "/bin/sh -c" in script
    assert "codex" in script
    assert "exec --json --full-auto" in script
    assert 'model_reasoning_summary="detailed"' in script
    assert str(prompt_path) in script
    assert str(log_path) in script
    assert str(Path(task.repo_path)) in script
    assert "2>&1 | tee -a" in script


def test_extract_session_hint_accepts_multiple_formats() -> None:
    assert CodexWorkerLauncher.extract_session_hint('{"session_id":"abc-1"}') == "abc-1"
    assert CodexWorkerLauncher.extract_session_hint("sessionId = sess-2") == "sess-2"
    assert CodexWorkerLauncher.extract_session_hint("no session here") is None


def test_launch_task_writes_missing_harness_bootstrap_prompt(tmp_path: Path) -> None:
    store = CodingTaskStore(tmp_path / "automation" / "coding" / "tasks.json")
    manager = CodexWorkerManager(tmp_path, store)
    repo = tmp_path / "repo-missing"
    repo.mkdir()
    task = manager.create_task(repo_path=str(repo), goal="Initialize harness first")
    fake_runner = _FakeRunner(has_session=False)
    launcher = CodexWorkerLauncher(tmp_path, manager, runner=fake_runner)

    result = launcher.launch_task(task.id)
    prompt = Path(result.prompt_path).read_text(encoding="utf-8")

    assert "Harness mode: no complete harness detected." in prompt
    assert "Create a granular PLAN.json" in prompt


def test_launch_task_writes_existing_harness_recovery_prompt(tmp_path: Path) -> None:
    launcher, task, _fake_runner = _make_launcher(tmp_path, has_session=False)

    result = launcher.launch_task(task.id)
    prompt = Path(result.prompt_path).read_text(encoding="utf-8")

    assert task.approval_policy == "local_only"
    assert "Approval policy: local_only" in prompt
    assert "Harness mode: existing harness detected." in prompt
    assert "Read PROGRESS.md." in prompt
    assert "Existing harness summary: Continue old task" in prompt


def test_launch_task_writes_new_goal_override_prompt_for_conflict_resolution(tmp_path: Path) -> None:
    launcher, task, _fake_runner = _make_launcher(tmp_path, has_session=False)
    launcher.manager.update_metadata(
        task.id,
        updates={"harness_conflict_resolution": "start_new_goal"},
    )

    result = launcher.launch_task(task.id)
    prompt = Path(result.prompt_path).read_text(encoding="utf-8")

    assert "user explicitly chose to start a new goal" in prompt
    assert "Do not continue the old unfinished harness features as the primary task." in prompt


def test_launch_task_writes_completed_harness_prompt_for_conflict_resolution(tmp_path: Path) -> None:
    store = CodingTaskStore(tmp_path / "automation" / "coding" / "tasks.json")
    manager = CodexWorkerManager(tmp_path, store)
    repo = tmp_path / "repo-completed"
    repo.mkdir()
    (repo / "PLAN.json").write_text(
        '[{"id": 1, "passes": true}, {"id": 2, "passes": true}]',
        encoding="utf-8",
    )
    (repo / "PROGRESS.md").write_text("## Session update\n- Finish the prior plan\n", encoding="utf-8")
    (repo / "init.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    task = manager.create_task(repo_path=str(repo), goal="Replace icon")
    manager.update_metadata(
        task.id,
        updates={"harness_conflict_resolution": "resume_existing"},
    )
    launcher = CodexWorkerLauncher(tmp_path, manager, runner=_FakeRunner(has_session=False))

    result = launcher.launch_task(task.id)
    prompt = Path(result.prompt_path).read_text(encoding="utf-8")

    assert "Harness mode: completed harness detected." in prompt
    assert "completed background context" in prompt


def test_launch_task_reports_startup_diagnostic_when_pane_output_contains_shell_failure(tmp_path: Path) -> None:
    launcher, task, _fake_runner = _make_launcher(
        tmp_path,
        has_session=False,
        capture_output="Error: The current working directory must be readable to miau to run brew.\n",
    )

    result = launcher.launch_task(task.id)

    assert "Worker shell bootstrap failed before Codex launch" in result.task.last_progress_summary


def test_worker_artifacts_are_namespaced_by_task_id(tmp_path: Path) -> None:
    store = CodingTaskStore(tmp_path / "automation" / "coding" / "tasks.json")
    manager = CodexWorkerManager(tmp_path, store)
    repo_a = tmp_path / "repo-a"
    repo_b = tmp_path / "repo-b"
    repo_a.mkdir()
    repo_b.mkdir()
    task_a = manager.create_task(repo_path=str(repo_a), goal="Task A")
    task_b = manager.create_task(repo_path=str(repo_b), goal="Task B")

    launcher = CodexWorkerLauncher(tmp_path, manager, runner=_FakeRunner(has_session=False))
    result_a = launcher.launch_task(task_a.id)
    result_b = launcher.launch_task(task_b.id)

    assert result_a.prompt_path != result_b.prompt_path
    assert Path(result_a.prompt_path).name.startswith(task_a.id)
    assert Path(result_b.prompt_path).name.startswith(task_b.id)
