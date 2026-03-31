"""Throttled outbound notifications for coding task progress."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable

from nanobot.bus.events import OutboundMessage
from nanobot.coding_tasks.manager import CodexWorkerManager
from nanobot.coding_tasks.progress import TaskProgressReport
from nanobot.coding_tasks.reporting import (
    build_completion_report,
    build_failure_report,
    build_waiting_user_report,
    repo_display_name,
)


class CodingTaskNotifier:
    """Throttle and deliver coding-task notifications to the originating chat."""

    def __init__(
        self,
        manager: CodexWorkerManager,
        send_callback: Callable[[OutboundMessage], Awaitable[None]],
        *,
        throttle_s: int = 30,
    ) -> None:
        self.manager = manager
        self.send_callback = send_callback
        self.throttle_s = throttle_s
        self._last_sent_at: dict[str, float] = {}
        self._last_sent_signature: dict[str, tuple[str, str]] = {}

    async def maybe_notify(self, task_id: str, report: TaskProgressReport) -> bool:
        task = self.manager.require_task(task_id)
        channel = task.metadata.get("origin_channel")
        chat_id = task.metadata.get("origin_chat_id")
        if not channel or not chat_id:
            return False

        content = self._build_content(task, report)
        if not content:
            return False

        now = time.monotonic()
        signature = (task.status, content)
        last_signature = self._last_sent_signature.get(task_id)
        last_at = self._last_sent_at.get(task_id, 0.0)
        if last_signature == signature:
            return False
        if last_at and now - last_at < self.throttle_s:
            return False

        await self.send_callback(
            OutboundMessage(channel=channel, chat_id=chat_id, content=content, metadata={"render_as": "text"})
        )
        self._last_sent_at[task_id] = now
        self._last_sent_signature[task_id] = signature
        return True

    def _build_content(self, task, report: TaskProgressReport) -> str:
        if task.status == "completed":
            return build_completion_report(task)
        if task.status == "failed":
            return build_failure_report(task)
        if task.status == "waiting_user":
            return build_waiting_user_report(task)
        if task.status == "starting":
            return self._build_start_notification(task)
        if task.status == "running":
            return ""
        return ""

    def _build_start_notification(self, task) -> str:
        repo_name = repo_display_name(task)
        goal = _truncate_line(task.goal, limit=64)
        return "\n".join(
            [
                f"**已开始编程任务** · `{repo_name}`",
                f"**目标**: {goal}",
            ]
        )

def _truncate_line(text: str, *, limit: int) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3] + "..."
