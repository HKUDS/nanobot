from __future__ import annotations

from nanobot.bus.events import OutboundMessage
from nanobot.coding_tasks.manager import CodexWorkerManager
from nanobot.coding_tasks.notifier import CodingTaskNotifier
from nanobot.coding_tasks.progress import PlanProgress, TaskProgressReport
from nanobot.coding_tasks.store import CodingTaskStore


async def _send_collector(sent: list[OutboundMessage], msg: OutboundMessage) -> None:
    sent.append(msg)


def test_notifier_sends_one_start_notification_and_throttles_duplicates(tmp_path) -> None:
    import asyncio

    store = CodingTaskStore(tmp_path / "automation" / "coding" / "tasks.json")
    manager = CodexWorkerManager(tmp_path, store)
    repo = tmp_path / "repo"
    repo.mkdir()
    task = manager.create_task(
        repo_path=str(repo),
        goal="notify",
        metadata={"origin_channel": "telegram", "origin_chat_id": "chat-1"},
    )
    task = manager.mark_starting(task.id, summary="Boot")
    report = TaskProgressReport(
        latest_note="note",
        plan_progress=PlanProgress(completed=1, remaining=1, total=2),
        live_output="Running pytest",
        branch_name="",
        recent_commit_summary="",
        summary="已完成 1/2 项，剩余 1 项 | 当前输出: Running pytest",
    )
    sent: list[OutboundMessage] = []
    notifier = CodingTaskNotifier(manager, lambda msg: _send_collector(sent, msg), throttle_s=60)

    asyncio.run(notifier.maybe_notify(task.id, report))
    asyncio.run(notifier.maybe_notify(task.id, report))

    assert len(sent) == 1
    assert "已开始编程任务" in sent[0].content
    assert f"任务ID: {task.id}" in sent[0].content
    assert "目标: notify" in sent[0].content
    assert "Running pytest" not in sent[0].content


def test_notifier_suppresses_unchanged_content_even_after_throttle_window(tmp_path) -> None:
    import asyncio
    import time

    store = CodingTaskStore(tmp_path / "automation" / "coding" / "tasks.json")
    manager = CodexWorkerManager(tmp_path, store)
    repo = tmp_path / "repo"
    repo.mkdir()
    task = manager.create_task(
        repo_path=str(repo),
        goal="notify",
        metadata={"origin_channel": "telegram", "origin_chat_id": "chat-1"},
    )
    task = manager.mark_starting(task.id, summary="Boot")
    report = TaskProgressReport(
        latest_note="note",
        plan_progress=PlanProgress(completed=1, remaining=1, total=2),
        live_output="Running pytest",
        branch_name="",
        recent_commit_summary="",
        summary="已完成 1/2 项，剩余 1 项 | 当前输出: Running pytest",
    )
    sent: list[OutboundMessage] = []
    notifier = CodingTaskNotifier(manager, lambda msg: _send_collector(sent, msg), throttle_s=1)

    asyncio.run(notifier.maybe_notify(task.id, report))
    time.sleep(1.1)
    asyncio.run(notifier.maybe_notify(task.id, report))

    assert len(sent) == 1


def test_notifier_skips_running_progress_pushes(tmp_path) -> None:
    import asyncio

    store = CodingTaskStore(tmp_path / "automation" / "coding" / "tasks.json")
    manager = CodexWorkerManager(tmp_path, store)
    repo = tmp_path / "repo"
    repo.mkdir()
    task = manager.create_task(
        repo_path=str(repo),
        goal="notify",
        metadata={"origin_channel": "telegram", "origin_chat_id": "chat-1"},
    )
    task = manager.mark_starting(task.id, summary="Boot")
    task = manager.mark_running(task.id, summary="Working")
    report = TaskProgressReport(
        latest_note="note",
        plan_progress=PlanProgress(completed=1, remaining=1, total=2),
        live_output="Running pytest",
        branch_name="",
        recent_commit_summary="",
        summary="已完成 1/2 项，剩余 1 项 | 当前输出: Running pytest",
    )
    sent: list[OutboundMessage] = []
    notifier = CodingTaskNotifier(manager, lambda msg: _send_collector(sent, msg), throttle_s=60)

    asyncio.run(notifier.maybe_notify(task.id, report))

    assert sent == []


def test_notifier_allows_new_status_with_new_content(tmp_path) -> None:
    import asyncio

    store = CodingTaskStore(tmp_path / "automation" / "coding" / "tasks.json")
    manager = CodexWorkerManager(tmp_path, store)
    repo = tmp_path / "repo"
    repo.mkdir()
    task = manager.create_task(
        repo_path=str(repo),
        goal="notify",
        metadata={"origin_channel": "telegram", "origin_chat_id": "chat-1"},
    )
    task = manager.mark_starting(task.id, summary="Boot")
    task = manager.mark_waiting_user(task.id, summary="Need choice")
    report = TaskProgressReport(
        latest_note="note",
        plan_progress=PlanProgress(completed=1, remaining=1, total=2),
        live_output="Need choice",
        branch_name="",
        recent_commit_summary="",
        summary="Need choice",
    )
    sent: list[OutboundMessage] = []
    notifier = CodingTaskNotifier(manager, lambda msg: _send_collector(sent, msg), throttle_s=60)

    asyncio.run(notifier.maybe_notify(task.id, report))

    assert len(sent) == 1
    assert (
        "等待你的确认" in sent[0].content
        or "仓库里已有未完成的 harness" in sent[0].content
        or "仓库里已有已完成的 harness" in sent[0].content
    )
