from __future__ import annotations

import time

from nanobot.coding_tasks.manager import CodexWorkerManager
from nanobot.coding_tasks.policy import CodingTaskPolicy
from nanobot.coding_tasks.store import CodingTaskStore


def test_policy_preserves_workspace_single_active_selection(tmp_path) -> None:
    store = CodingTaskStore(tmp_path / "automation" / "coding" / "tasks.json")
    manager = CodexWorkerManager(tmp_path, store)
    repo_a = tmp_path / "repo-a"
    repo_b = tmp_path / "repo-b"
    repo_a.mkdir()
    repo_b.mkdir()
    first = manager.create_task(
        repo_path=str(repo_a),
        goal="First",
        metadata={"origin_channel": "telegram", "origin_chat_id": "chat-a"},
    )
    second = manager.create_task(
        repo_path=str(repo_b),
        goal="Second",
        metadata={"origin_channel": "telegram", "origin_chat_id": "chat-b"},
    )
    time.sleep(0.01)
    manager.mark_starting(second.id, summary="Boot")

    policy = CodingTaskPolicy(manager)

    assert policy.blocking_active_task() is not None
    assert policy.blocking_active_task().id == second.id
    assert first.id != second.id


def test_policy_preserves_origin_chat_task_selection(tmp_path) -> None:
    store = CodingTaskStore(tmp_path / "automation" / "coding" / "tasks.json")
    manager = CodexWorkerManager(tmp_path, store)
    repo_a = tmp_path / "repo-a"
    repo_b = tmp_path / "repo-b"
    repo_a.mkdir()
    repo_b.mkdir()

    older = manager.create_task(
        repo_path=str(repo_a),
        goal="Older",
        metadata={"origin_channel": "telegram", "origin_chat_id": "chat-a"},
    )
    manager.mark_starting(older.id, summary="Boot")
    manager.mark_waiting_user(older.id, summary="Waiting")
    newer = manager.create_task(
        repo_path=str(repo_b),
        goal="Newer",
        metadata={"origin_channel": "telegram", "origin_chat_id": "chat-a"},
    )
    time.sleep(0.01)
    manager.mark_starting(newer.id, summary="Boot")
    manager.mark_running(newer.id, summary="Working")

    policy = CodingTaskPolicy(manager)

    assert policy.latest_origin_task("telegram", "chat-a") is not None
    assert policy.latest_origin_task("telegram", "chat-a").id == newer.id
    assert policy.select_control_task("telegram", "chat-a") is not None
    assert policy.select_control_task("telegram", "chat-a").id == newer.id
