"""
TaskContext - Pure task state management.

This module provides TaskContext, which manages task state without any
server/session dependencies. It can be used standalone for distributed
workers or wrapped by ServerTaskContext for full server integration.
"""

from mcp.shared.experimental.tasks.store import TaskStore
from mcp.types import TASK_STATUS_COMPLETED, TASK_STATUS_FAILED, Result, Task


class TaskContext:
    """
    Pure task state management - no session dependencies.

    This class handles:
    - Task state (status, result)
    - Cancellation tracking
    - Store interactions

    For server-integrated features (elicit, create_message, notifications),
    use ServerTaskContext from mcp.server.experimental.

    Example (distributed worker):
        async def worker_job(task_id: str):
            store = RedisTaskStore(redis_url)
            task = await store.get_task(task_id)
            ctx = TaskContext(task=task, store=store)

            await ctx.update_status("Working...")
            result = await do_work()
            await ctx.complete(result)
    """

    def __init__(self, task: Task, store: TaskStore):
        self._task = task
        self._store = store
        self._cancelled = False

    @property
    def task_id(self) -> str:
        """The task identifier."""
        return self._task.taskId

    @property
    def task(self) -> Task:
        """The current task state."""
        return self._task

    @property
    def is_cancelled(self) -> bool:
        """Whether cancellation has been requested."""
        return self._cancelled

    def request_cancellation(self) -> None:
        """
        Request cancellation of this task.

        This sets is_cancelled=True. Task work should check this
        periodically and exit gracefully if set.
        """
        self._cancelled = True

    async def update_status(self, message: str) -> None:
        """
        Update the task's status message.

        Args:
            message: The new status message
        """
        self._task = await self._store.update_task(
            self.task_id,
            status_message=message,
        )

    async def complete(self, result: Result) -> None:
        """
        Mark the task as completed with the given result.

        Args:
            result: The task result
        """
        await self._store.store_result(self.task_id, result)
        self._task = await self._store.update_task(
            self.task_id,
            status=TASK_STATUS_COMPLETED,
        )

    async def fail(self, error: str) -> None:
        """
        Mark the task as failed with an error message.

        Args:
            error: The error message
        """
        self._task = await self._store.update_task(
            self.task_id,
            status=TASK_STATUS_FAILED,
            status_message=error,
        )
