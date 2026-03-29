from pathlib import Path

from nanobot.coding_tasks.manager import CodexWorkerManager
from nanobot.coding_tasks.store import CodingTaskStore


def test_multiple_queued_tasks_survive_store_reload(tmp_path: Path) -> None:
    store_path = tmp_path / "automation" / "coding" / "tasks.json"
    store = CodingTaskStore(store_path)
    manager = CodexWorkerManager(tmp_path, store)
    repo_a = tmp_path / "repo-a"
    repo_b = tmp_path / "repo-b"
    repo_c = tmp_path / "repo-c"
    repo_a.mkdir()
    repo_b.mkdir()
    repo_c.mkdir()

    task_a = manager.create_task(repo_path=str(repo_a), goal="Queue A")
    task_b = manager.create_task(repo_path=str(repo_b), goal="Queue B")
    task_c = manager.create_task(repo_path=str(repo_c), goal="Queue C")

    reloaded = CodingTaskStore(store_path).list_tasks()

    assert [task.id for task in reloaded] == [task_a.id, task_b.id, task_c.id]
    assert all(task.status == "queued" for task in reloaded)
