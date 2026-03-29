from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.coding_tasks.manager import CodexWorkerManager
from nanobot.coding_tasks.runtime import build_coding_task_runtime
from nanobot.coding_tasks.store import CodingTaskStore


class _FakeLauncher:
    def __init__(self, manager: CodexWorkerManager, *, fail_on_launch: bool = False) -> None:
        self.manager = manager
        self.fail_on_launch = fail_on_launch
        self.launched_ids: list[str] = []

    def launch_task(self, task_id: str):
        self.launched_ids.append(task_id)
        if self.fail_on_launch:
            raise RuntimeError("tmux unavailable")
        launched = self.manager.mark_starting(task_id, harness_state="missing", summary="Launching Codex worker")

        class _Result:
            task = launched
            session_reused = False
            session_hint = None

        return _Result()

    def capture_pane(self, _session: str) -> str:
        return ""

    def has_session(self, _session: str) -> bool:
        return False

    def interrupt_task(self, task_id: str):
        return self.manager.require_task(task_id)


def _make_loop(
    tmp_path: Path,
    *,
    attach_launcher: bool = True,
    fail_on_launch: bool = False,
    repo_aliases: dict[str, str] | None = None,
):
    from nanobot.agent.loop import AgentLoop

    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    store = CodingTaskStore(tmp_path / "automation" / "coding_tasks.json")
    manager = CodexWorkerManager(tmp_path, store)
    runtime = None
    launcher = None
    if attach_launcher:
        launcher = _FakeLauncher(manager, fail_on_launch=fail_on_launch)
        runtime = build_coding_task_runtime(
            tmp_path,
            manager=manager,
            launcher=launcher,
            repo_aliases=repo_aliases,
        )

    with patch("nanobot.agent.loop.ContextBuilder"), \
         patch("nanobot.agent.loop.SessionManager"), \
         patch("nanobot.agent.loop.SubagentManager"):
        loop = AgentLoop(
            bus=bus,
            provider=provider,
            workspace=tmp_path,
            coding_task_runtime=runtime,
            coding_task_manager=manager,
        )
    return loop, store, manager, launcher


def _create_origin_task(store: CodingTaskStore, tmp_path: Path, *, status: str = "queued", summary: str = ""):
    manager = CodexWorkerManager(tmp_path, store)
    repo_path = tmp_path / "demo-repo"
    repo_path.mkdir(exist_ok=True)
    task = manager.create_task(
        repo_path=str(repo_path),
        goal="修复登录回调",
        metadata={
            "origin_channel": "telegram",
            "origin_chat_id": "chat-1",
            "requested_via": "telegram_private_chat",
        },
    )
    if status == "running":
        task = manager.mark_starting(task.id, summary="Launching Codex")
        task = manager.mark_running(task.id, summary=summary or "正在修改登录逻辑")
    elif status == "failed":
        task = manager.mark_starting(task.id, summary="Launching Codex")
        task = manager.mark_failed(task.id, summary=summary or "等待恢复")
    elif status == "waiting_user":
        task = manager.mark_starting(task.id, summary="Launching Codex")
        task = manager.mark_waiting_user(task.id, summary=summary or "等待继续")
    return manager, task


def _init_active_harness(repo_path: Path, *, note: str = "Continue old task") -> None:
    repo_path.mkdir(exist_ok=True)
    (repo_path / "PLAN.json").write_text('[{"id": 1, "passes": false}]', encoding="utf-8")
    (repo_path / "PROGRESS.md").write_text(f"## Session update\n- {note}\n", encoding="utf-8")
    (repo_path / "init.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")


def _init_completed_harness(repo_path: Path, *, note: str = "Finish the prior plan") -> None:
    repo_path.mkdir(exist_ok=True)
    (repo_path / "PLAN.json").write_text(
        '[{"id": 1, "passes": true}, {"id": 2, "passes": true}]',
        encoding="utf-8",
    )
    (repo_path / "PROGRESS.md").write_text(f"## Session update\n- {note}\n", encoding="utf-8")
    (repo_path / "init.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")


@pytest.mark.asyncio
async def test_private_telegram_start_coding_creates_task_and_acknowledges(tmp_path: Path) -> None:
    loop, store, _manager, launcher = _make_loop(tmp_path, attach_launcher=True)
    repo_path = tmp_path / "demo-repo"
    repo_path.mkdir()

    response = await loop._process_message(
        InboundMessage(
            channel="telegram",
            sender_id="u1",
            chat_id="chat-1",
            content=f"开始编程 {repo_path} 修复登录回调",
            metadata={"is_group": False, "message_id": 42},
        )
    )

    assert response is not None
    assert "已创建并启动编程任务" in response.content
    assert "状态: starting" in response.content

    tasks = store.list_tasks()
    assert len(tasks) == 1
    assert launcher.launched_ids == [tasks[0].id]
    assert tasks[0].repo_path == str(repo_path)
    assert tasks[0].goal == "修复登录回调"
    assert tasks[0].status == "starting"
    assert tasks[0].metadata["origin_channel"] == "telegram"
    assert tasks[0].metadata["origin_chat_id"] == "chat-1"
    assert tasks[0].metadata["requested_via"] == "telegram_private_chat"


@pytest.mark.asyncio
async def test_private_telegram_start_coding_waits_for_confirmation_when_repo_has_active_harness(tmp_path: Path) -> None:
    loop, store, _manager, launcher = _make_loop(tmp_path, attach_launcher=True)
    repo_path = tmp_path / "demo-repo"
    _init_active_harness(repo_path, note="Continue old task")

    response = await loop._process_message(
        InboundMessage(
            channel="telegram",
            sender_id="u1",
            chat_id="chat-1",
            content=f"开始编程 {repo_path} 修复登录回调",
            metadata={"is_group": False, "message_id": 41},
        )
    )

    assert response is not None
    assert "仓库里已有未完成的 harness" in response.content
    assert "旧任务摘要: Continue old task" in response.content
    assert "按新任务开始" in response.content
    tasks = store.list_tasks()
    assert len(tasks) == 1
    assert launcher.launched_ids == []
    assert tasks[0].status == "waiting_user"
    assert tasks[0].metadata["harness_conflict_reason"] == "repo_active_harness"


@pytest.mark.asyncio
async def test_private_telegram_start_coding_waits_for_confirmation_when_repo_has_completed_harness(tmp_path: Path) -> None:
    loop, store, _manager, launcher = _make_loop(tmp_path, attach_launcher=True)
    repo_path = tmp_path / "demo-repo"
    _init_completed_harness(repo_path, note="Finish the prior plan")

    response = await loop._process_message(
        InboundMessage(
            channel="telegram",
            sender_id="u1",
            chat_id="chat-1",
            content=f"开始编程 {repo_path} 替换设置图标",
            metadata={"is_group": False, "message_id": 46},
        )
    )

    assert response is not None
    assert "已创建并启动编程任务" in response.content
    tasks = store.list_tasks()
    assert len(tasks) == 1
    assert launcher.launched_ids == [tasks[0].id]
    assert tasks[0].status == "starting"
    assert tasks[0].metadata.get("harness_conflict_reason") is None


@pytest.mark.asyncio
async def test_private_telegram_start_coding_with_repo_alias_and_natural_language_goal(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    loop, store, _manager, launcher = _make_loop(tmp_path, attach_launcher=True)
    repo_path = tmp_path / "Documents" / "codex-remote"
    repo_path.mkdir(parents=True)

    response = await loop._process_message(
        InboundMessage(
            channel="telegram",
            sender_id="u1",
            chat_id="chat-1",
            content="开始编程 codex-remote 的 设置 icon 换一个",
            metadata={"is_group": False, "message_id": 43},
        )
    )

    assert response is not None
    assert "已创建并启动编程任务" in response.content
    tasks = store.list_tasks()
    assert len(tasks) == 1
    assert launcher.launched_ids == [tasks[0].id]
    assert tasks[0].repo_path == str(repo_path)
    assert tasks[0].goal == "设置 icon 换一个"


@pytest.mark.asyncio
async def test_private_telegram_slash_coding_command_uses_repo_alias(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    loop, store, _manager, launcher = _make_loop(tmp_path, attach_launcher=True)
    repo_path = tmp_path / "Documents" / "codex-remote"
    repo_path.mkdir(parents=True)

    response = await loop._process_message(
        InboundMessage(
            channel="telegram",
            sender_id="u1",
            chat_id="chat-1",
            content="/coding codex-remote 的 设置 icon 换一个",
            metadata={"is_group": False, "message_id": 44},
        )
    )

    assert response is not None
    assert "已创建并启动编程任务" in response.content
    tasks = store.list_tasks()
    assert len(tasks) == 1
    assert launcher.launched_ids == [tasks[0].id]
    assert tasks[0].repo_path == str(repo_path)
    assert tasks[0].goal == "设置 icon 换一个"


@pytest.mark.asyncio
async def test_private_telegram_start_coding_with_repo_alias_without_particle(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    loop, store, _manager, launcher = _make_loop(tmp_path, attach_launcher=True)
    repo_path = tmp_path / "Documents" / "codex-remote"
    repo_path.mkdir(parents=True)

    response = await loop._process_message(
        InboundMessage(
            channel="telegram",
            sender_id="u1",
            chat_id="chat-1",
            content="开始编程 codex-remote 底部tab的设置icon换一个",
            metadata={"is_group": False, "message_id": 45},
        )
    )

    assert response is not None
    assert "已创建并启动编程任务" in response.content
    tasks = store.list_tasks()
    assert len(tasks) == 1
    assert launcher.launched_ids == [tasks[0].id]
    assert tasks[0].repo_path == str(repo_path)
    assert tasks[0].goal == "底部tab的设置icon换一个"


@pytest.mark.asyncio
async def test_private_telegram_start_coding_prefers_runtime_repo_alias_map(tmp_path: Path) -> None:
    alias_repo = tmp_path / "repos" / "codex-remote"
    alias_repo.mkdir(parents=True)
    fallback_repo = tmp_path / "Documents" / "codex-remote"
    fallback_repo.mkdir(parents=True)
    loop, store, _manager, launcher = _make_loop(
        tmp_path,
        attach_launcher=True,
        repo_aliases={"codex-remote": str(alias_repo)},
    )

    response = await loop._process_message(
        InboundMessage(
            channel="telegram",
            sender_id="u1",
            chat_id="chat-1",
            content="开始编程 codex-remote 设置 icon 换一个",
            metadata={"is_group": False, "message_id": 46},
        )
    )

    assert response is not None
    assert "已创建并启动编程任务" in response.content
    tasks = store.list_tasks()
    assert len(tasks) == 1
    assert launcher.launched_ids == [tasks[0].id]
    assert tasks[0].repo_path == str(alias_repo)
    assert tasks[0].goal == "设置 icon 换一个"


@pytest.mark.asyncio
async def test_private_telegram_start_coding_without_repo_or_goal_returns_usage(tmp_path: Path) -> None:
    loop, store, _manager, _launcher = _make_loop(tmp_path)

    response = await loop._process_message(
        InboundMessage(
            channel="telegram",
            sender_id="u1",
            chat_id="chat-1",
            content="开始编程",
            metadata={"is_group": False},
        )
    )

    assert response is not None
    assert "请用以下格式创建编程任务" in response.content
    assert store.list_tasks() == []


@pytest.mark.asyncio
async def test_private_telegram_status_routes_to_latest_origin_task(tmp_path: Path) -> None:
    loop, store, _manager, _launcher = _make_loop(tmp_path)
    _manager, task = _create_origin_task(store, tmp_path, status="running", summary="正在修改登录逻辑")

    response = await loop._process_message(
        InboundMessage(
            channel="telegram",
            sender_id="u1",
            chat_id="chat-1",
            content="状态",
            metadata={"is_group": False},
        )
    )

    assert response is not None
    assert "当前编程任务状态" in response.content
    assert f"任务ID: {task.id}" in response.content
    assert "状态: running" in response.content
    assert "最近进展: 正在修改登录逻辑" in response.content
    assert "可恢复: yes" in response.content


@pytest.mark.asyncio
async def test_private_telegram_slash_coding_status_routes_to_latest_origin_task(tmp_path: Path) -> None:
    loop, store, _manager, _launcher = _make_loop(tmp_path)
    _manager, task = _create_origin_task(store, tmp_path, status="running", summary="正在修改登录逻辑")

    response = await loop._process_message(
        InboundMessage(
            channel="telegram",
            sender_id="u1",
            chat_id="chat-1",
            content="/coding status",
            metadata={"is_group": False},
        )
    )

    assert response is not None
    assert "当前编程任务状态" in response.content
    assert f"任务ID: {task.id}" in response.content
    assert "状态: running" in response.content
    assert "最近进展: 正在修改登录逻辑" in response.content


@pytest.mark.asyncio
async def test_private_telegram_cancel_routes_to_origin_task(tmp_path: Path) -> None:
    loop, store, _manager, _launcher = _make_loop(tmp_path)
    _manager, task = _create_origin_task(store, tmp_path)

    response = await loop._process_message(
        InboundMessage(
            channel="telegram",
            sender_id="u1",
            chat_id="chat-1",
            content="取消",
            metadata={"is_group": False},
        )
    )

    assert response is not None
    assert "已取消编程任务" in response.content
    updated = store.get_task(task.id)
    assert updated is not None
    assert updated.status == "cancelled"
    assert updated.last_user_control == "cancel"


@pytest.mark.asyncio
async def test_private_telegram_continue_rejects_cancelled_task(tmp_path: Path) -> None:
    loop, store, _manager, _launcher = _make_loop(tmp_path)
    _manager, task = _create_origin_task(store, tmp_path)

    await loop._process_message(
        InboundMessage(
            channel="telegram",
            sender_id="u1",
            chat_id="chat-1",
            content="取消",
            metadata={"is_group": False},
        )
    )

    response = await loop._process_message(
        InboundMessage(
            channel="telegram",
            sender_id="u1",
            chat_id="chat-1",
            content="继续",
            metadata={"is_group": False},
        )
    )

    assert response is not None
    assert f"任务ID: {task.id}" in response.content
    assert "已经取消" in response.content


@pytest.mark.asyncio
async def test_private_telegram_resume_routes_to_failed_origin_task(tmp_path: Path) -> None:
    loop, store, _manager, _launcher = _make_loop(tmp_path)
    _manager, task = _create_origin_task(store, tmp_path, status="failed")

    response = await loop._process_message(
        InboundMessage(
            channel="telegram",
            sender_id="u1",
            chat_id="chat-1",
            content="继续",
            metadata={"is_group": False},
        )
    )

    assert response is not None
    assert "已继续编程任务" in response.content
    updated = store.get_task(task.id)
    assert updated is not None
    assert updated.status == "starting"
    assert updated.last_user_control == "resume"


@pytest.mark.asyncio
async def test_private_telegram_resume_requires_explicit_choice_for_harness_conflict(tmp_path: Path) -> None:
    loop, store, _manager, _launcher = _make_loop(tmp_path, attach_launcher=True)
    repo_path = tmp_path / "demo-repo"
    _init_active_harness(repo_path, note="Continue old task")

    await loop._process_message(
        InboundMessage(
            channel="telegram",
            sender_id="u1",
            chat_id="chat-1",
            content=f"开始编程 {repo_path} 修复登录回调",
            metadata={"is_group": False, "message_id": 47},
        )
    )

    response = await loop._process_message(
        InboundMessage(
            channel="telegram",
            sender_id="u1",
            chat_id="chat-1",
            content="继续",
            metadata={"is_group": False},
        )
    )

    assert response is not None
    assert "继续旧任务" in response.content
    task = store.list_tasks()[0]
    assert task.status == "waiting_user"


@pytest.mark.asyncio
async def test_private_telegram_continue_old_harness_launches_conflict_task(tmp_path: Path) -> None:
    loop, store, _manager, launcher = _make_loop(tmp_path, attach_launcher=True)
    repo_path = tmp_path / "demo-repo"
    _init_active_harness(repo_path, note="Continue old task")

    await loop._process_message(
        InboundMessage(
            channel="telegram",
            sender_id="u1",
            chat_id="chat-1",
            content=f"开始编程 {repo_path} 修复登录回调",
            metadata={"is_group": False, "message_id": 48},
        )
    )

    response = await loop._process_message(
        InboundMessage(
            channel="telegram",
            sender_id="u1",
            chat_id="chat-1",
            content="继续旧任务",
            metadata={"is_group": False},
        )
    )

    assert response is not None
    assert "已继续旧任务" in response.content
    task = store.list_tasks()[0]
    assert launcher.launched_ids == [task.id]
    assert task.status == "starting"
    assert task.last_user_control == "resume_existing"
    assert task.metadata["harness_conflict_resolution"] == "resume_existing"


@pytest.mark.asyncio
async def test_private_telegram_start_new_goal_launches_conflict_task_with_override(tmp_path: Path) -> None:
    loop, store, _manager, launcher = _make_loop(tmp_path, attach_launcher=True)
    repo_path = tmp_path / "demo-repo"
    _init_active_harness(repo_path, note="Continue old task")

    await loop._process_message(
        InboundMessage(
            channel="telegram",
            sender_id="u1",
            chat_id="chat-1",
            content=f"开始编程 {repo_path} 修复登录回调",
            metadata={"is_group": False, "message_id": 49},
        )
    )

    response = await loop._process_message(
        InboundMessage(
            channel="telegram",
            sender_id="u1",
            chat_id="chat-1",
            content="按新任务开始",
            metadata={"is_group": False},
        )
    )

    assert response is not None
    assert "已按新任务启动编程任务" in response.content
    task = store.list_tasks()[0]
    assert launcher.launched_ids == [task.id]
    assert task.status == "starting"
    assert task.last_user_control == "start_new_goal"
    assert task.metadata["harness_conflict_resolution"] == "start_new_goal"


@pytest.mark.asyncio
async def test_private_telegram_resume_reuses_live_tmux_worker_session(tmp_path: Path) -> None:
    loop, store, _manager, _launcher = _make_loop(tmp_path)
    manager, task = _create_origin_task(store, tmp_path, status="failed")

    class _FakeLauncher:
        def launch_task(self, task_id: str):
            assert task_id == task.id
            launched = manager.mark_starting(task.id, summary="Launching Codex worker")

            class _Result:
                task = launched
                session_reused = True

            return _Result()

    from nanobot.coding_tasks.progress import CodexProgressMonitor
    from nanobot.coding_tasks.router import register_coding_task_commands
    loop.commands = loop.commands.__class__()
    from nanobot.command import register_builtin_commands
    register_builtin_commands(loop.commands)
    register_coding_task_commands(
        loop.commands,
        manager,
        launcher=_FakeLauncher(),  # type: ignore[arg-type]
        monitor=CodexProgressMonitor(manager, _FakeLauncher()),  # type: ignore[arg-type]
    )

    response = await loop._process_message(
        InboundMessage(
            channel="telegram",
            sender_id="u1",
            chat_id="chat-1",
            content="继续",
            metadata={"is_group": False},
        )
    )

    assert response is not None
    assert "已继续编程任务" in response.content
    assert "复用 tmux: yes" in response.content


@pytest.mark.asyncio
async def test_private_telegram_stop_interrupts_live_worker_and_marks_waiting(tmp_path: Path) -> None:
    loop, store, _manager, _launcher = _make_loop(tmp_path)
    manager, task = _create_origin_task(store, tmp_path, status="running")

    class _FakeLauncher:
        def interrupt_task(self, task_id: str):
            assert task_id == task.id
            return manager.require_task(task_id)

        def capture_pane(self, _session: str) -> str:
            return "still running\n"

    from nanobot.coding_tasks.progress import CodexProgressMonitor
    from nanobot.coding_tasks.router import register_coding_task_commands
    loop.commands = loop.commands.__class__()
    from nanobot.command import register_builtin_commands
    register_builtin_commands(loop.commands)
    register_coding_task_commands(
        loop.commands,
        manager,
        launcher=_FakeLauncher(),  # type: ignore[arg-type]
        monitor=CodexProgressMonitor(manager, _FakeLauncher()),  # type: ignore[arg-type]
    )

    response = await loop._process_message(
        InboundMessage(
            channel="telegram",
            sender_id="u1",
            chat_id="chat-1",
            content="停止",
            metadata={"is_group": False},
        )
    )

    assert response is not None
    assert "已停止编程任务" in response.content
    updated = store.get_task(task.id)
    assert updated is not None
    assert updated.status == "waiting_user"
    assert updated.last_user_control == "stop"


@pytest.mark.asyncio
async def test_private_telegram_rejects_second_active_coding_task(tmp_path: Path) -> None:
    loop, store, _manager, _launcher = _make_loop(tmp_path, attach_launcher=True)
    repo_path = tmp_path / "demo-repo"
    repo_path.mkdir()
    other_repo_path = tmp_path / "other-repo"
    other_repo_path.mkdir()

    first = await loop._process_message(
        InboundMessage(
            channel="telegram",
            sender_id="u1",
            chat_id="chat-1",
            content=f"开始编程 {repo_path} 修复登录回调",
            metadata={"is_group": False, "message_id": 42},
        )
    )
    assert first is not None
    created = store.list_tasks()
    assert len(created) == 1

    response = await loop._process_message(
        InboundMessage(
            channel="telegram",
            sender_id="u1",
            chat_id="chat-1",
            content=f"开始编程 {other_repo_path} 实现新的同步逻辑",
            metadata={"is_group": False, "message_id": 43},
        )
    )

    assert response is not None
    assert "当前已有一个活跃的编程任务" in response.content
    assert len(store.list_tasks()) == 1


@pytest.mark.asyncio
async def test_private_telegram_rejects_missing_repo_path_before_task_creation(tmp_path: Path) -> None:
    loop, store, _manager, _launcher = _make_loop(tmp_path)
    missing_repo = tmp_path / "missing-repo"

    response = await loop._process_message(
        InboundMessage(
            channel="telegram",
            sender_id="u1",
            chat_id="chat-1",
            content=f"开始编程 {missing_repo} 修复登录回调",
            metadata={"is_group": False},
        )
    )

    assert response is not None
    assert "仓库路径不存在" in response.content
    assert store.list_tasks() == []


@pytest.mark.asyncio
async def test_private_telegram_start_coding_without_launcher_falls_back_to_create_only(tmp_path: Path) -> None:
    loop, store, manager, _launcher = _make_loop(tmp_path)
    repo_path = tmp_path / "demo-repo"
    repo_path.mkdir()

    from nanobot.coding_tasks.router import register_coding_task_commands
    loop.commands = loop.commands.__class__()
    from nanobot.command import register_builtin_commands
    register_builtin_commands(loop.commands)
    register_coding_task_commands(
        loop.commands,
        manager,
        launcher=None,
        monitor=None,
    )

    response = await loop._process_message(
        InboundMessage(
            channel="telegram",
            sender_id="u1",
            chat_id="chat-1",
            content=f"开始编程 {repo_path} 修复登录回调",
            metadata={"is_group": False, "message_id": 42},
        )
    )

    assert response is not None
    assert "已创建编程任务" in response.content
    assert "状态: queued" in response.content
    tasks = store.list_tasks()
    assert len(tasks) == 1
    assert tasks[0].status == "queued"


@pytest.mark.asyncio
async def test_private_telegram_start_coding_reports_launch_failure_and_keeps_task(tmp_path: Path) -> None:
    loop, store, _manager, launcher = _make_loop(tmp_path, attach_launcher=True, fail_on_launch=True)
    repo_path = tmp_path / "demo-repo"
    repo_path.mkdir()

    response = await loop._process_message(
        InboundMessage(
            channel="telegram",
            sender_id="u1",
            chat_id="chat-1",
            content=f"开始编程 {repo_path} 修复登录回调",
            metadata={"is_group": False, "message_id": 42},
        )
    )

    assert response is not None
    assert "已创建编程任务，但自动启动失败" in response.content
    assert "tmux unavailable" in response.content
    tasks = store.list_tasks()
    assert len(tasks) == 1
    assert tasks[0].status == "failed"
