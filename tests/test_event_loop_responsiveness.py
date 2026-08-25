"""Cross-cutting heartbeat regressions for synchronous persistence locks."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from pathlib import Path

from filelock import FileLock

from nanobot.agent.tools.context import RequestContext, request_context
from nanobot.agent.tools.cron import CronTool
from nanobot.config.loader import load_config, save_config
from nanobot.config.schema import Config
from nanobot.cron.service import CronService
from nanobot.session.manager import SessionManager
from nanobot.triggers.local_runner import run_local_trigger_queue
from nanobot.triggers.local_store import LocalTriggerStore
from nanobot.webui.settings_api import update_api_settings
from nanobot.webui.settings_services import WebUISettingsServices


async def _assert_10ms_heartbeat_runs_while_pending(task: asyncio.Task[object]) -> None:
    for _ in range(3):
        await asyncio.sleep(0.01)
    assert not task.done()


async def test_session_lock_contention_does_not_block_event_loop(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workspace = tmp_path / "workspace"
    sessions_root = tmp_path / "session-data"
    legacy_root = tmp_path / "legacy-sessions"
    monkeypatch.setattr(
        "nanobot.session.manager.get_legacy_sessions_dir",
        lambda: legacy_root,
    )
    manager = SessionManager(workspace, sessions_root=sessions_root)
    session = manager.get_or_create("websocket:lock-test")
    session.add_message("user", "hello")
    lock = manager._jsonl_store._session_files_lock
    assert lock.timeout == 5
    blocker = FileLock(lock.lock_file, timeout=1)
    blocker.acquire()
    task = asyncio.create_task(manager.save_async(session))
    try:
        await _assert_10ms_heartbeat_runs_while_pending(task)
    finally:
        blocker.release()

    await asyncio.wait_for(task, timeout=1)
    assert manager.read_session_file(session.key) is not None


async def test_cron_lock_contention_does_not_block_event_loop(tmp_path: Path) -> None:
    service = CronService(tmp_path / "cron" / "jobs.json")
    tool = CronTool(service)
    assert service._lock.timeout == 5
    blocker = FileLock(service._lock.lock_file, timeout=1)
    blocker.acquire()
    with request_context(
        RequestContext(
            channel="websocket",
            chat_id="lock-test",
            session_key="websocket:lock-test",
        )
    ):
        task = asyncio.create_task(
            tool.execute(action="add", message="wake up", every_seconds=60)
        )
    try:
        await _assert_10ms_heartbeat_runs_while_pending(task)
    finally:
        blocker.release()

    result = await asyncio.wait_for(task, timeout=1)
    assert result.startswith("Created job")


async def test_local_trigger_lock_contention_does_not_block_event_loop(
    tmp_path: Path,
) -> None:
    store = LocalTriggerStore(tmp_path)
    assert store._lock.timeout == 5
    blocker = FileLock(store._lock.lock_file, timeout=1)
    blocker.acquire()

    async def submit_turn(_message):
        return None

    task = asyncio.create_task(
        run_local_trigger_queue(
            store=store,
            submit_turn=submit_turn,
            is_channel_enabled=lambda _name: True,
            poll_interval_s=0.01,
        )
    )
    try:
        await _assert_10ms_heartbeat_runs_while_pending(task)
    finally:
        blocker.release()
    await asyncio.sleep(0.05)
    task.cancel()
    with suppress(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=1)


async def test_settings_lock_contention_does_not_block_event_loop(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    save_config(Config(), config_path)
    services = WebUISettingsServices.create(config_path)
    assert services.config._file_lock.timeout == 5
    blocker = FileLock(services.config._file_lock.lock_file, timeout=1)
    blocker.acquire()
    task = asyncio.create_task(
        services.mutate_async(update_api_settings, {"port": ["19001"]})
    )
    try:
        await _assert_10ms_heartbeat_runs_while_pending(task)
    finally:
        blocker.release()

    await asyncio.wait_for(task, timeout=1)
    assert load_config(config_path).api.port == 19001
