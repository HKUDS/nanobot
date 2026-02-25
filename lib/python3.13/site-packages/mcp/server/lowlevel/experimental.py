"""Experimental handlers for the low-level MCP server.

WARNING: These APIs are experimental and may change without notice.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from mcp.server.experimental.task_support import TaskSupport
from mcp.server.lowlevel.func_inspection import create_call_wrapper
from mcp.shared.exceptions import McpError
from mcp.shared.experimental.tasks.helpers import cancel_task
from mcp.shared.experimental.tasks.in_memory_task_store import InMemoryTaskStore
from mcp.shared.experimental.tasks.message_queue import InMemoryTaskMessageQueue, TaskMessageQueue
from mcp.shared.experimental.tasks.store import TaskStore
from mcp.types import (
    INVALID_PARAMS,
    CancelTaskRequest,
    CancelTaskResult,
    ErrorData,
    GetTaskPayloadRequest,
    GetTaskPayloadResult,
    GetTaskRequest,
    GetTaskResult,
    ListTasksRequest,
    ListTasksResult,
    ServerCapabilities,
    ServerResult,
    ServerTasksCapability,
    ServerTasksRequestsCapability,
    TasksCancelCapability,
    TasksListCapability,
    TasksToolsCapability,
)

if TYPE_CHECKING:
    from mcp.server.lowlevel.server import Server

logger = logging.getLogger(__name__)


class ExperimentalHandlers:
    """Experimental request/notification handlers.

    WARNING: These APIs are experimental and may change without notice.
    """

    def __init__(
        self,
        server: Server,
        request_handlers: dict[type, Callable[..., Awaitable[ServerResult]]],
        notification_handlers: dict[type, Callable[..., Awaitable[None]]],
    ):
        self._server = server
        self._request_handlers = request_handlers
        self._notification_handlers = notification_handlers
        self._task_support: TaskSupport | None = None

    @property
    def task_support(self) -> TaskSupport | None:
        """Get the task support configuration, if enabled."""
        return self._task_support

    def update_capabilities(self, capabilities: ServerCapabilities) -> None:
        # Only add tasks capability if handlers are registered
        if not any(
            req_type in self._request_handlers
            for req_type in [GetTaskRequest, ListTasksRequest, CancelTaskRequest, GetTaskPayloadRequest]
        ):
            return

        capabilities.tasks = ServerTasksCapability()
        if ListTasksRequest in self._request_handlers:
            capabilities.tasks.list = TasksListCapability()
        if CancelTaskRequest in self._request_handlers:
            capabilities.tasks.cancel = TasksCancelCapability()

        capabilities.tasks.requests = ServerTasksRequestsCapability(
            tools=TasksToolsCapability()
        )  # assuming always supported for now

    def enable_tasks(
        self,
        store: TaskStore | None = None,
        queue: TaskMessageQueue | None = None,
    ) -> TaskSupport:
        """
        Enable experimental task support.

        This sets up the task infrastructure and auto-registers default handlers
        for tasks/get, tasks/result, tasks/list, and tasks/cancel.

        Args:
            store: Custom TaskStore implementation (defaults to InMemoryTaskStore)
            queue: Custom TaskMessageQueue implementation (defaults to InMemoryTaskMessageQueue)

        Returns:
            The TaskSupport configuration object

        Example:
            # Simple in-memory setup
            server.experimental.enable_tasks()

            # Custom store/queue for distributed systems
            server.experimental.enable_tasks(
                store=RedisTaskStore(redis_url),
                queue=RedisTaskMessageQueue(redis_url),
            )

        WARNING: This API is experimental and may change without notice.
        """
        if store is None:
            store = InMemoryTaskStore()
        if queue is None:
            queue = InMemoryTaskMessageQueue()

        self._task_support = TaskSupport(store=store, queue=queue)

        # Auto-register default handlers
        self._register_default_task_handlers()

        return self._task_support

    def _register_default_task_handlers(self) -> None:
        """Register default handlers for task operations."""
        assert self._task_support is not None
        support = self._task_support

        # Register get_task handler if not already registered
        if GetTaskRequest not in self._request_handlers:

            async def _default_get_task(req: GetTaskRequest) -> ServerResult:
                task = await support.store.get_task(req.params.taskId)
                if task is None:
                    raise McpError(
                        ErrorData(
                            code=INVALID_PARAMS,
                            message=f"Task not found: {req.params.taskId}",
                        )
                    )
                return ServerResult(
                    GetTaskResult(
                        taskId=task.taskId,
                        status=task.status,
                        statusMessage=task.statusMessage,
                        createdAt=task.createdAt,
                        lastUpdatedAt=task.lastUpdatedAt,
                        ttl=task.ttl,
                        pollInterval=task.pollInterval,
                    )
                )

            self._request_handlers[GetTaskRequest] = _default_get_task

        # Register get_task_result handler if not already registered
        if GetTaskPayloadRequest not in self._request_handlers:

            async def _default_get_task_result(req: GetTaskPayloadRequest) -> ServerResult:
                ctx = self._server.request_context
                result = await support.handler.handle(req, ctx.session, ctx.request_id)
                return ServerResult(result)

            self._request_handlers[GetTaskPayloadRequest] = _default_get_task_result

        # Register list_tasks handler if not already registered
        if ListTasksRequest not in self._request_handlers:

            async def _default_list_tasks(req: ListTasksRequest) -> ServerResult:
                cursor = req.params.cursor if req.params else None
                tasks, next_cursor = await support.store.list_tasks(cursor)
                return ServerResult(ListTasksResult(tasks=tasks, nextCursor=next_cursor))

            self._request_handlers[ListTasksRequest] = _default_list_tasks

        # Register cancel_task handler if not already registered
        if CancelTaskRequest not in self._request_handlers:

            async def _default_cancel_task(req: CancelTaskRequest) -> ServerResult:
                result = await cancel_task(support.store, req.params.taskId)
                return ServerResult(result)

            self._request_handlers[CancelTaskRequest] = _default_cancel_task

    def list_tasks(
        self,
    ) -> Callable[
        [Callable[[ListTasksRequest], Awaitable[ListTasksResult]]],
        Callable[[ListTasksRequest], Awaitable[ListTasksResult]],
    ]:
        """Register a handler for listing tasks.

        WARNING: This API is experimental and may change without notice.
        """

        def decorator(
            func: Callable[[ListTasksRequest], Awaitable[ListTasksResult]],
        ) -> Callable[[ListTasksRequest], Awaitable[ListTasksResult]]:
            logger.debug("Registering handler for ListTasksRequest")
            wrapper = create_call_wrapper(func, ListTasksRequest)

            async def handler(req: ListTasksRequest) -> ServerResult:
                result = await wrapper(req)
                return ServerResult(result)

            self._request_handlers[ListTasksRequest] = handler
            return func

        return decorator

    def get_task(
        self,
    ) -> Callable[
        [Callable[[GetTaskRequest], Awaitable[GetTaskResult]]], Callable[[GetTaskRequest], Awaitable[GetTaskResult]]
    ]:
        """Register a handler for getting task status.

        WARNING: This API is experimental and may change without notice.
        """

        def decorator(
            func: Callable[[GetTaskRequest], Awaitable[GetTaskResult]],
        ) -> Callable[[GetTaskRequest], Awaitable[GetTaskResult]]:
            logger.debug("Registering handler for GetTaskRequest")
            wrapper = create_call_wrapper(func, GetTaskRequest)

            async def handler(req: GetTaskRequest) -> ServerResult:
                result = await wrapper(req)
                return ServerResult(result)

            self._request_handlers[GetTaskRequest] = handler
            return func

        return decorator

    def get_task_result(
        self,
    ) -> Callable[
        [Callable[[GetTaskPayloadRequest], Awaitable[GetTaskPayloadResult]]],
        Callable[[GetTaskPayloadRequest], Awaitable[GetTaskPayloadResult]],
    ]:
        """Register a handler for getting task results/payload.

        WARNING: This API is experimental and may change without notice.
        """

        def decorator(
            func: Callable[[GetTaskPayloadRequest], Awaitable[GetTaskPayloadResult]],
        ) -> Callable[[GetTaskPayloadRequest], Awaitable[GetTaskPayloadResult]]:
            logger.debug("Registering handler for GetTaskPayloadRequest")
            wrapper = create_call_wrapper(func, GetTaskPayloadRequest)

            async def handler(req: GetTaskPayloadRequest) -> ServerResult:
                result = await wrapper(req)
                return ServerResult(result)

            self._request_handlers[GetTaskPayloadRequest] = handler
            return func

        return decorator

    def cancel_task(
        self,
    ) -> Callable[
        [Callable[[CancelTaskRequest], Awaitable[CancelTaskResult]]],
        Callable[[CancelTaskRequest], Awaitable[CancelTaskResult]],
    ]:
        """Register a handler for cancelling tasks.

        WARNING: This API is experimental and may change without notice.
        """

        def decorator(
            func: Callable[[CancelTaskRequest], Awaitable[CancelTaskResult]],
        ) -> Callable[[CancelTaskRequest], Awaitable[CancelTaskResult]]:
            logger.debug("Registering handler for CancelTaskRequest")
            wrapper = create_call_wrapper(func, CancelTaskRequest)

            async def handler(req: CancelTaskRequest) -> ServerResult:
                result = await wrapper(req)
                return ServerResult(result)

            self._request_handlers[CancelTaskRequest] = handler
            return func

        return decorator
