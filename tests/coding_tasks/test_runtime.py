from __future__ import annotations

from pathlib import Path

from nanobot.bus.events import OutboundMessage
from nanobot.coding_tasks.runtime import build_coding_task_runtime


async def _noop(_msg: OutboundMessage) -> None:
    return None


def test_build_runtime_assembles_shared_workspace_collaborators(tmp_path: Path) -> None:
    runtime = build_coding_task_runtime(tmp_path)

    expected_store = tmp_path / "automation" / "coding" / "tasks.json"
    assert runtime.workspace == tmp_path
    assert runtime.store.store_path == expected_store
    assert runtime.manager.workspace == tmp_path
    assert runtime.manager.store is runtime.store
    assert runtime.launcher.workspace == tmp_path
    assert runtime.launcher.manager is runtime.manager
    assert runtime.monitor.manager is runtime.manager
    assert runtime.monitor.launcher is runtime.launcher
    assert runtime.recovery.manager is runtime.manager
    assert runtime.recovery.launcher is runtime.launcher
    assert runtime.recovery.monitor is runtime.monitor
    assert runtime.policy.manager is runtime.manager
    assert runtime.repo_resolver.aliases == {}
    assert runtime.notifier is None


def test_build_runtime_can_attach_optional_notifier_without_rewiring_store(tmp_path: Path) -> None:
    runtime = build_coding_task_runtime(tmp_path, send_callback=_noop, throttle_s=45)

    assert runtime.notifier is not None
    assert runtime.notifier.manager is runtime.manager
    assert runtime.notifier.send_callback is _noop
    assert runtime.notifier.throttle_s == 45
    assert runtime.policy.manager is runtime.manager
    assert runtime.store.store_path == tmp_path / "automation" / "coding" / "tasks.json"


def test_build_runtime_can_include_repo_aliases(tmp_path: Path) -> None:
    runtime = build_coding_task_runtime(
        tmp_path,
        repo_aliases={"codex-remote": "/Users/miau/Documents/codex-remote"},
    )

    assert runtime.repo_resolver.aliases["codex-remote"] == "/Users/miau/Documents/codex-remote"
