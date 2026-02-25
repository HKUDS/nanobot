"""
TaskMessageQueue - FIFO queue for task-related messages.

This implements the core message queue pattern from the MCP Tasks spec.
When a handler needs to send a request (like elicitation) during a task-augmented
request, the message is enqueued instead of sent directly. Messages are delivered
to the client only through the `tasks/result` endpoint.

This pattern enables:
1. Decoupling request handling from message delivery
2. Proper bidirectional communication via the tasks/result stream
3. Automatic status management (working <-> input_required)
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

import anyio

from mcp.shared.experimental.tasks.resolver import Resolver
from mcp.types import JSONRPCNotification, JSONRPCRequest, RequestId


@dataclass
class QueuedMessage:
    """
    A message queued for delivery via tasks/result.

    Messages are stored with their type and a resolver for requests
    that expect responses.
    """

    type: Literal["request", "notification"]
    """Whether this is a request (expects response) or notification (one-way)."""

    message: JSONRPCRequest | JSONRPCNotification
    """The JSON-RPC message to send."""

    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    """When the message was enqueued."""

    resolver: Resolver[dict[str, Any]] | None = None
    """Resolver to set when response arrives (only for requests)."""

    original_request_id: RequestId | None = None
    """The original request ID used internally, for routing responses back."""


class TaskMessageQueue(ABC):
    """
    Abstract interface for task message queuing.

    This is a FIFO queue that stores messages to be delivered via `tasks/result`.
    When a task-augmented handler calls elicit() or sends a notification, the
    message is enqueued here instead of being sent directly to the client.

    The `tasks/result` handler then dequeues and sends these messages through
    the transport, with `relatedRequestId` set to the tasks/result request ID
    so responses are routed correctly.

    Implementations can use in-memory storage, Redis, etc.
    """

    @abstractmethod
    async def enqueue(self, task_id: str, message: QueuedMessage) -> None:
        """
        Add a message to the queue for a task.

        Args:
            task_id: The task identifier
            message: The message to enqueue
        """

    @abstractmethod
    async def dequeue(self, task_id: str) -> QueuedMessage | None:
        """
        Remove and return the next message from the queue.

        Args:
            task_id: The task identifier

        Returns:
            The next message, or None if queue is empty
        """

    @abstractmethod
    async def peek(self, task_id: str) -> QueuedMessage | None:
        """
        Return the next message without removing it.

        Args:
            task_id: The task identifier

        Returns:
            The next message, or None if queue is empty
        """

    @abstractmethod
    async def is_empty(self, task_id: str) -> bool:
        """
        Check if the queue is empty for a task.

        Args:
            task_id: The task identifier

        Returns:
            True if no messages are queued
        """

    @abstractmethod
    async def clear(self, task_id: str) -> list[QueuedMessage]:
        """
        Remove and return all messages from the queue.

        This is useful for cleanup when a task is cancelled or completed.

        Args:
            task_id: The task identifier

        Returns:
            All queued messages (may be empty)
        """

    @abstractmethod
    async def wait_for_message(self, task_id: str) -> None:
        """
        Wait until a message is available in the queue.

        This blocks until either:
        1. A message is enqueued for this task
        2. The wait is cancelled

        Args:
            task_id: The task identifier
        """

    @abstractmethod
    async def notify_message_available(self, task_id: str) -> None:
        """
        Signal that a message is available for a task.

        This wakes up any coroutines waiting in wait_for_message().

        Args:
            task_id: The task identifier
        """


class InMemoryTaskMessageQueue(TaskMessageQueue):
    """
    In-memory implementation of TaskMessageQueue.

    This is suitable for single-process servers. For distributed systems,
    implement TaskMessageQueue with Redis, RabbitMQ, etc.

    Features:
    - FIFO ordering per task
    - Async wait for message availability
    - Thread-safe for single-process async use
    """

    def __init__(self) -> None:
        self._queues: dict[str, list[QueuedMessage]] = {}
        self._events: dict[str, anyio.Event] = {}

    def _get_queue(self, task_id: str) -> list[QueuedMessage]:
        """Get or create the queue for a task."""
        if task_id not in self._queues:
            self._queues[task_id] = []
        return self._queues[task_id]

    async def enqueue(self, task_id: str, message: QueuedMessage) -> None:
        """Add a message to the queue."""
        queue = self._get_queue(task_id)
        queue.append(message)
        # Signal that a message is available
        await self.notify_message_available(task_id)

    async def dequeue(self, task_id: str) -> QueuedMessage | None:
        """Remove and return the next message."""
        queue = self._get_queue(task_id)
        if not queue:
            return None
        return queue.pop(0)

    async def peek(self, task_id: str) -> QueuedMessage | None:
        """Return the next message without removing it."""
        queue = self._get_queue(task_id)
        if not queue:
            return None
        return queue[0]

    async def is_empty(self, task_id: str) -> bool:
        """Check if the queue is empty."""
        queue = self._get_queue(task_id)
        return len(queue) == 0

    async def clear(self, task_id: str) -> list[QueuedMessage]:
        """Remove and return all messages."""
        queue = self._get_queue(task_id)
        messages = list(queue)
        queue.clear()
        return messages

    async def wait_for_message(self, task_id: str) -> None:
        """Wait until a message is available."""
        # Check if there are already messages
        if not await self.is_empty(task_id):
            return

        # Create a fresh event for waiting (anyio.Event can't be cleared)
        self._events[task_id] = anyio.Event()
        event = self._events[task_id]

        # Double-check after creating event (avoid race condition)
        if not await self.is_empty(task_id):
            return

        # Wait for a new message
        await event.wait()

    async def notify_message_available(self, task_id: str) -> None:
        """Signal that a message is available."""
        if task_id in self._events:
            self._events[task_id].set()

    def cleanup(self, task_id: str | None = None) -> None:
        """
        Clean up queues and events.

        Args:
            task_id: If provided, clean up only this task. Otherwise clean up all.
        """
        if task_id is not None:
            self._queues.pop(task_id, None)
            self._events.pop(task_id, None)
        else:
            self._queues.clear()
            self._events.clear()
