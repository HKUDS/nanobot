"""
TaskStore - Abstract interface for task state storage.
"""

from abc import ABC, abstractmethod

from mcp.types import Result, Task, TaskMetadata, TaskStatus


class TaskStore(ABC):
    """
    Abstract interface for task state storage.

    This is a pure storage interface - it doesn't manage execution.
    Implementations can use in-memory storage, databases, Redis, etc.

    All methods are async to support various backends.
    """

    @abstractmethod
    async def create_task(
        self,
        metadata: TaskMetadata,
        task_id: str | None = None,
    ) -> Task:
        """
        Create a new task.

        Args:
            metadata: Task metadata (ttl, etc.)
            task_id: Optional task ID. If None, implementation should generate one.

        Returns:
            The created Task with status="working"

        Raises:
            ValueError: If task_id already exists
        """

    @abstractmethod
    async def get_task(self, task_id: str) -> Task | None:
        """
        Get a task by ID.

        Args:
            task_id: The task identifier

        Returns:
            The Task, or None if not found
        """

    @abstractmethod
    async def update_task(
        self,
        task_id: str,
        status: TaskStatus | None = None,
        status_message: str | None = None,
    ) -> Task:
        """
        Update a task's status and/or message.

        Args:
            task_id: The task identifier
            status: New status (if changing)
            status_message: New status message (if changing)

        Returns:
            The updated Task

        Raises:
            ValueError: If task not found
            ValueError: If attempting to transition from a terminal status
                (completed, failed, cancelled). Per spec, terminal states
                MUST NOT transition to any other status.
        """

    @abstractmethod
    async def store_result(self, task_id: str, result: Result) -> None:
        """
        Store the result for a task.

        Args:
            task_id: The task identifier
            result: The result to store

        Raises:
            ValueError: If task not found
        """

    @abstractmethod
    async def get_result(self, task_id: str) -> Result | None:
        """
        Get the stored result for a task.

        Args:
            task_id: The task identifier

        Returns:
            The stored Result, or None if not available
        """

    @abstractmethod
    async def list_tasks(
        self,
        cursor: str | None = None,
    ) -> tuple[list[Task], str | None]:
        """
        List tasks with pagination.

        Args:
            cursor: Optional cursor for pagination

        Returns:
            Tuple of (tasks, next_cursor). next_cursor is None if no more pages.
        """

    @abstractmethod
    async def delete_task(self, task_id: str) -> bool:
        """
        Delete a task.

        Args:
            task_id: The task identifier

        Returns:
            True if deleted, False if not found
        """

    @abstractmethod
    async def wait_for_update(self, task_id: str) -> None:
        """
        Wait until the task status changes.

        This blocks until either:
        1. The task status changes
        2. The wait is cancelled

        Used by tasks/result to wait for task completion or status changes.

        Args:
            task_id: The task identifier

        Raises:
            ValueError: If task not found
        """

    @abstractmethod
    async def notify_update(self, task_id: str) -> None:
        """
        Signal that a task has been updated.

        This wakes up any coroutines waiting in wait_for_update().

        Args:
            task_id: The task identifier
        """
