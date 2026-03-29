import pytest

from nanobot.coding_tasks.manager import CodexWorkerManager
from nanobot.coding_tasks.store import CodingTaskStore


def test_create_task_assigns_tmux_session_and_logs_creation(tmp_path) -> None:
    store = CodingTaskStore(tmp_path / "automation" / "coding" / "tasks.json")
    manager = CodexWorkerManager(tmp_path, store)

    task = manager.create_task(
        repo_path="/Users/miau/Documents/nanobot",
        goal="Wire Codex worker",
        title="Codex worker",
    )

    assert task.status == "queued"
    assert task.tmux_session is not None
    assert task.tmux_session.startswith("codex-task-nanobot-")

    events = store.read_run_events(task.id)
    assert len(events) == 1
    assert events[0].event == "created"
    assert events[0].status == "queued"

    reloaded = store.get_task(task.id)
    assert reloaded is not None
    assert reloaded.id == task.id
    assert reloaded.tmux_session == task.tmux_session


def test_lifecycle_transitions_update_task_and_recoverable_view(tmp_path) -> None:
    store = CodingTaskStore(tmp_path / "automation" / "coding" / "tasks.json")
    manager = CodexWorkerManager(tmp_path, store)
    task = manager.create_task(repo_path="/tmp/repo", goal="Do work")

    manager.mark_starting(task.id, codex_session_hint="session-1", harness_state="active", summary="Restoring harness")
    running = manager.mark_running(task.id, summary="Applying patch")
    recoverable = manager.recoverable_tasks()

    assert running.status == "running"
    assert running.codex_session_hint == "session-1"
    assert running.harness_state == "active"
    assert running.last_progress_summary == "Applying patch"
    assert [task.id for task in recoverable] == [task.id]

    done = manager.mark_completed(task.id, summary="Tests passed")
    assert done.status == "completed"
    assert manager.recoverable_tasks() == []


def test_invalid_transition_is_rejected(tmp_path) -> None:
    store = CodingTaskStore(tmp_path / "automation" / "coding" / "tasks.json")
    manager = CodexWorkerManager(tmp_path, store)
    task = manager.create_task(repo_path="/tmp/repo", goal="Do work")
    manager.mark_starting(task.id, summary="Boot")
    manager.mark_running(task.id, summary="Running")
    manager.mark_completed(task.id, summary="Done")

    with pytest.raises(ValueError, match="Cannot transition"):
        manager.mark_running(task.id, summary="Should fail")
