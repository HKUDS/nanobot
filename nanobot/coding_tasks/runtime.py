"""Shared runtime assembly for coding-task orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable

from nanobot.bus.events import OutboundMessage
from nanobot.coding_tasks.manager import CodexWorkerManager
from nanobot.coding_tasks.notifier import CodingTaskNotifier
from nanobot.coding_tasks.policy import CodingTaskPolicy
from nanobot.coding_tasks.progress import CodexProgressMonitor
from nanobot.coding_tasks.repo_resolver import RepoRefResolver
from nanobot.coding_tasks.recovery import CodexTaskRecovery
from nanobot.coding_tasks.store import CodingTaskStore
from nanobot.coding_tasks.worker import CodexWorkerLauncher


@dataclass(slots=True)
class CodingTaskRuntime:
    """Fully wired coding-task collaborators for one workspace."""

    workspace: Path
    store: CodingTaskStore
    manager: CodexWorkerManager
    launcher: CodexWorkerLauncher
    monitor: CodexProgressMonitor
    recovery: CodexTaskRecovery
    policy: CodingTaskPolicy
    repo_resolver: RepoRefResolver
    notifier: CodingTaskNotifier | None = None


def build_coding_task_runtime(
    workspace: Path,
    *,
    send_callback: Callable[[OutboundMessage], Awaitable[None]] | None = None,
    throttle_s: int = 30,
    store: CodingTaskStore | None = None,
    manager: CodexWorkerManager | None = None,
    launcher: CodexWorkerLauncher | None = None,
    repo_aliases: dict[str, str] | None = None,
) -> CodingTaskRuntime:
    """Assemble the coding-task collaborators from one workspace root."""
    resolved_workspace = Path(workspace)
    task_store = store or getattr(manager, "store", None) or CodingTaskStore(
        resolved_workspace / "automation" / "coding" / "tasks.json"
    )
    task_manager = manager or CodexWorkerManager(resolved_workspace, task_store)
    task_launcher = launcher or CodexWorkerLauncher(resolved_workspace, task_manager)
    task_monitor = CodexProgressMonitor(task_manager, task_launcher)
    task_recovery = CodexTaskRecovery(task_manager, task_launcher, task_monitor)
    task_policy = CodingTaskPolicy(task_manager)
    task_repo_resolver = RepoRefResolver(
        aliases={
            alias: path
            for alias, path in dict(repo_aliases or {}).items()
        }
    )
    task_notifier = (
        CodingTaskNotifier(task_manager, send_callback, throttle_s=throttle_s)
        if send_callback is not None
        else None
    )
    return CodingTaskRuntime(
        workspace=resolved_workspace,
        store=task_store,
        manager=task_manager,
        launcher=task_launcher,
        monitor=task_monitor,
        recovery=task_recovery,
        policy=task_policy,
        repo_resolver=task_repo_resolver,
        notifier=task_notifier,
    )
