from __future__ import annotations

from pathlib import Path

from nanobot.coding_tasks.manager import CodexWorkerManager
from nanobot.coding_tasks.store import CodingTaskStore


def test_lifecycle_changes_append_structured_run_events_in_order(tmp_path: Path) -> None:
    store = CodingTaskStore(tmp_path / "automation" / "coding" / "tasks.json")
    manager = CodexWorkerManager(tmp_path, store)
    repo = tmp_path / "repo"
    repo.mkdir()
    task = manager.create_task(repo_path=str(repo), goal="Audit events")
    manager.mark_starting(task.id, summary="Boot")
    manager.mark_running(task.id, summary="Working")
    manager.mark_completed(task.id, summary="Done")

    events = store.read_run_events(task.id)

    assert [event.event for event in events] == [
        "created",
        "status_changed",
        "status_changed",
        "status_changed",
    ]
    assert events[-1].status == "completed"
    assert events[-1].message == "Done"


def test_user_controls_are_logged_separately_from_status_changes(tmp_path: Path) -> None:
    store = CodingTaskStore(tmp_path / "automation" / "coding" / "tasks.json")
    manager = CodexWorkerManager(tmp_path, store)
    repo = tmp_path / "repo"
    repo.mkdir()
    task = manager.create_task(repo_path=str(repo), goal="Audit controls")
    manager.mark_starting(task.id, summary="Boot")
    manager.record_user_control(task.id, "resume")
    manager.mark_running(task.id, summary="Working")
    manager.record_user_control(task.id, "stop")

    events = store.read_run_events(task.id)

    control_events = [event for event in events if event.event == "user_control"]
    status_events = [event for event in events if event.event == "status_changed"]
    assert [event.message for event in control_events] == ["resume", "stop"]
    assert len(status_events) == 2
