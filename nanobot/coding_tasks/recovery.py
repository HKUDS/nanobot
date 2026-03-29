"""Recovery helpers for long-running coding tasks across gateway restarts."""

from __future__ import annotations

from dataclasses import dataclass, field

from nanobot.coding_tasks.manager import CodexWorkerManager
from nanobot.coding_tasks.progress import CodexProgressMonitor
from nanobot.coding_tasks.worker import CodexWorkerLauncher


@dataclass(slots=True)
class RecoveryResult:
    """Outcome of scanning recoverable coding tasks on startup."""

    recovered_ids: list[str] = field(default_factory=list)
    failed_ids: list[str] = field(default_factory=list)


class CodexTaskRecovery:
    """Reconnect to recoverable coding tasks or fail them with recovery hints."""

    def __init__(
        self,
        manager: CodexWorkerManager,
        launcher: CodexWorkerLauncher,
        monitor: CodexProgressMonitor,
    ) -> None:
        self.manager = manager
        self.launcher = launcher
        self.monitor = monitor

    def recover_tasks(self) -> RecoveryResult:
        """Reconnect recoverable tasks to live tmux sessions when possible."""
        result = RecoveryResult()
        for task in self.manager.recoverable_tasks():
            if not task.tmux_session or not self.launcher.has_session(task.tmux_session):
                self.manager.mark_failed(
                    task.id,
                    summary=(
                        "tmux session missing after restart; run "
                        f"`nanobot coding-task run {task.id}` to relaunch the worker."
                    ),
                )
                result.failed_ids.append(task.id)
                continue

            report = self.monitor.refresh_task(task.id)
            result.recovered_ids.append(task.id)
        return result
