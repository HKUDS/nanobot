"""
In-memory implementation of TaskStore for demonstration purposes.

This implementation stores all tasks in memory and provides automatic cleanup
based on the TTL duration specified in the task metadata using lazy expiration.

Note: This is not suitable for production use as all data is lost on restart.
For production, consider implementing TaskStore with a database or distributed cache.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import anyio

from mcp.shared.experimental.tasks.helpers import create_task_state, is_terminal
from mcp.shared.experimental.tasks.store import TaskStore
from mcp.types import Result, Task, TaskMetadata, TaskStatus


@dataclass
class StoredTask:
    """Internal storage representation of a task."""

    task: Task
    result: Result | None = None
    # Time when this task should be removed (None = never)
    expires_at: datetime | None = field(default=None)


class InMemoryTaskStore(TaskStore):
    """
    A simple in-memory implementation of TaskStore.

    Features:
    - Automatic TTL-based cleanup (lazy expiration)
    - Thread-safe for single-process async use
    - Pagination support for list_tasks

    Limitations:
    - All data lost on restart
    - Not suitable for distributed systems
    - No persistence

    For production, implement TaskStore with Redis, PostgreSQL, etc.
    """

    def __init__(self, page_size: int = 10) -> None:
        self._tasks: dict[str, StoredTask] = {}
        self._page_size = page_size
        self._update_events: dict[str, anyio.Event] = {}

    def _calculate_expiry(self, ttl_ms: int | None) -> datetime | None:
        """Calculate expiry time from TTL in milliseconds."""
        if ttl_ms is None:
            return None
        return datetime.now(timezone.utc) + timedelta(milliseconds=ttl_ms)

    def _is_expired(self, stored: StoredTask) -> bool:
        """Check if a task has expired."""
        if stored.expires_at is None:
            return False
        return datetime.now(timezone.utc) >= stored.expires_at

    def _cleanup_expired(self) -> None:
        """Remove all expired tasks. Called lazily during access operations."""
        expired_ids = [task_id for task_id, stored in self._tasks.items() if self._is_expired(stored)]
        for task_id in expired_ids:
            del self._tasks[task_id]

    async def create_task(
        self,
        metadata: TaskMetadata,
        task_id: str | None = None,
    ) -> Task:
        """Create a new task with the given metadata."""
        # Cleanup expired tasks on access
        self._cleanup_expired()

        task = create_task_state(metadata, task_id)

        if task.taskId in self._tasks:
            raise ValueError(f"Task with ID {task.taskId} already exists")

        stored = StoredTask(
            task=task,
            expires_at=self._calculate_expiry(metadata.ttl),
        )
        self._tasks[task.taskId] = stored

        # Return a copy to prevent external modification
        return Task(**task.model_dump())

    async def get_task(self, task_id: str) -> Task | None:
        """Get a task by ID."""
        # Cleanup expired tasks on access
        self._cleanup_expired()

        stored = self._tasks.get(task_id)
        if stored is None:
            return None

        # Return a copy to prevent external modification
        return Task(**stored.task.model_dump())

    async def update_task(
        self,
        task_id: str,
        status: TaskStatus | None = None,
        status_message: str | None = None,
    ) -> Task:
        """Update a task's status and/or message."""
        stored = self._tasks.get(task_id)
        if stored is None:
            raise ValueError(f"Task with ID {task_id} not found")

        # Per spec: Terminal states MUST NOT transition to any other status
        if status is not None and status != stored.task.status and is_terminal(stored.task.status):
            raise ValueError(f"Cannot transition from terminal status '{stored.task.status}'")

        status_changed = False
        if status is not None and stored.task.status != status:
            stored.task.status = status
            status_changed = True

        if status_message is not None:
            stored.task.statusMessage = status_message

        # Update lastUpdatedAt on any change
        stored.task.lastUpdatedAt = datetime.now(timezone.utc)

        # If task is now terminal and has TTL, reset expiry timer
        if status is not None and is_terminal(status) and stored.task.ttl is not None:
            stored.expires_at = self._calculate_expiry(stored.task.ttl)

        # Notify waiters if status changed
        if status_changed:
            await self.notify_update(task_id)

        return Task(**stored.task.model_dump())

    async def store_result(self, task_id: str, result: Result) -> None:
        """Store the result for a task."""
        stored = self._tasks.get(task_id)
        if stored is None:
            raise ValueError(f"Task with ID {task_id} not found")

        stored.result = result

    async def get_result(self, task_id: str) -> Result | None:
        """Get the stored result for a task."""
        stored = self._tasks.get(task_id)
        if stored is None:
            return None

        return stored.result

    async def list_tasks(
        self,
        cursor: str | None = None,
    ) -> tuple[list[Task], str | None]:
        """List tasks with pagination."""
        # Cleanup expired tasks on access
        self._cleanup_expired()

        all_task_ids = list(self._tasks.keys())

        start_index = 0
        if cursor is not None:
            try:
                cursor_index = all_task_ids.index(cursor)
                start_index = cursor_index + 1
            except ValueError:
                raise ValueError(f"Invalid cursor: {cursor}")

        page_task_ids = all_task_ids[start_index : start_index + self._page_size]
        tasks = [Task(**self._tasks[tid].task.model_dump()) for tid in page_task_ids]

        # Determine next cursor
        next_cursor = None
        if start_index + self._page_size < len(all_task_ids) and page_task_ids:
            next_cursor = page_task_ids[-1]

        return tasks, next_cursor

    async def delete_task(self, task_id: str) -> bool:
        """Delete a task."""
        if task_id not in self._tasks:
            return False

        del self._tasks[task_id]
        return True

    async def wait_for_update(self, task_id: str) -> None:
        """Wait until the task status changes."""
        if task_id not in self._tasks:
            raise ValueError(f"Task with ID {task_id} not found")

        # Create a fresh event for waiting (anyio.Event can't be cleared)
        self._update_events[task_id] = anyio.Event()
        event = self._update_events[task_id]
        await event.wait()

    async def notify_update(self, task_id: str) -> None:
        """Signal that a task has been updated."""
        if task_id in self._update_events:
            self._update_events[task_id].set()

    # --- Testing/debugging helpers ---

    def cleanup(self) -> None:
        """Cleanup all tasks (useful for testing or graceful shutdown)."""
        self._tasks.clear()
        self._update_events.clear()

    def get_all_tasks(self) -> list[Task]:
        """Get all tasks (useful for debugging). Returns copies to prevent modification."""
        self._cleanup_expired()
        return [Task(**stored.task.model_dump()) for stored in self._tasks.values()]
