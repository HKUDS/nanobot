"""Task-selection and concurrency policy for coding-task orchestration."""

from __future__ import annotations

from nanobot.coding_tasks.manager import CodexWorkerManager
from nanobot.coding_tasks.types import CodingTask


class CodingTaskPolicy:
    """Encapsulate MVP task-selection rules outside transport routers."""

    def __init__(self, manager: CodexWorkerManager) -> None:
        self.manager = manager

    def blocking_active_task(self) -> CodingTask | None:
        """Return the workspace-wide task that blocks creating another task."""
        return self.manager.latest_active_task()

    def select_control_task(self, channel: str, chat_id: str) -> CodingTask | None:
        """Return the newest non-terminal task for one origin chat."""
        return self.manager.latest_active_task_for_origin(channel, chat_id)

    def latest_origin_task(self, channel: str, chat_id: str) -> CodingTask | None:
        """Return the latest task for one origin chat, terminal or not."""
        tasks = self.manager.tasks_for_origin(channel, chat_id)
        return tasks[0] if tasks else None
