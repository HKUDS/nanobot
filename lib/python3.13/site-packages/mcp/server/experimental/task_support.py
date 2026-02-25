"""
TaskSupport - Configuration for experimental task support.

This module provides the TaskSupport class which encapsulates all the
infrastructure needed for task-augmented requests: store, queue, and handler.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

import anyio
from anyio.abc import TaskGroup

from mcp.server.experimental.task_result_handler import TaskResultHandler
from mcp.server.session import ServerSession
from mcp.shared.experimental.tasks.in_memory_task_store import InMemoryTaskStore
from mcp.shared.experimental.tasks.message_queue import InMemoryTaskMessageQueue, TaskMessageQueue
from mcp.shared.experimental.tasks.store import TaskStore


@dataclass
class TaskSupport:
    """
    Configuration for experimental task support.

    Encapsulates the task store, message queue, result handler, and task group
    for spawning background work.

    When enabled on a server, this automatically:
    - Configures response routing for each session
    - Provides default handlers for task operations
    - Manages a task group for background task execution

    Example:
        # Simple in-memory setup
        server.experimental.enable_tasks()

        # Custom store/queue for distributed systems
        server.experimental.enable_tasks(
            store=RedisTaskStore(redis_url),
            queue=RedisTaskMessageQueue(redis_url),
        )
    """

    store: TaskStore
    queue: TaskMessageQueue
    handler: TaskResultHandler = field(init=False)
    _task_group: TaskGroup | None = field(init=False, default=None)

    def __post_init__(self) -> None:
        """Create the result handler from store and queue."""
        self.handler = TaskResultHandler(self.store, self.queue)

    @property
    def task_group(self) -> TaskGroup:
        """Get the task group for spawning background work.

        Raises:
            RuntimeError: If not within a run() context
        """
        if self._task_group is None:
            raise RuntimeError("TaskSupport not running. Ensure Server.run() is active.")
        return self._task_group

    @asynccontextmanager
    async def run(self) -> AsyncIterator[None]:
        """
        Run the task support lifecycle.

        This creates a task group for spawning background task work.
        Called automatically by Server.run().

        Usage:
            async with task_support.run():
                # Task group is now available
                ...
        """
        async with anyio.create_task_group() as tg:
            self._task_group = tg
            try:
                yield
            finally:
                self._task_group = None

    def configure_session(self, session: ServerSession) -> None:
        """
        Configure a session for task support.

        This registers the result handler as a response router so that
        responses to queued requests (elicitation, sampling) are routed
        back to the waiting resolvers.

        Called automatically by Server.run() for each new session.

        Args:
            session: The session to configure
        """
        session.add_response_router(self.handler)

    @classmethod
    def in_memory(cls) -> "TaskSupport":
        """
        Create in-memory task support.

        Suitable for development, testing, and single-process servers.
        For distributed systems, provide custom store and queue implementations.

        Returns:
            TaskSupport configured with in-memory store and queue
        """
        return cls(
            store=InMemoryTaskStore(),
            queue=InMemoryTaskMessageQueue(),
        )
