"""
TaskResultHandler - Integrated handler for tasks/result endpoint.

This implements the dequeue-send-wait pattern from the MCP Tasks spec:
1. Dequeue all pending messages for the task
2. Send them to the client via transport with relatedRequestId routing
3. Wait if task is not in terminal state
4. Return final result when task completes

This is the core of the task message queue pattern.
"""

import logging
from typing import Any

import anyio

from mcp.server.session import ServerSession
from mcp.shared.exceptions import McpError
from mcp.shared.experimental.tasks.helpers import RELATED_TASK_METADATA_KEY, is_terminal
from mcp.shared.experimental.tasks.message_queue import TaskMessageQueue
from mcp.shared.experimental.tasks.resolver import Resolver
from mcp.shared.experimental.tasks.store import TaskStore
from mcp.shared.message import ServerMessageMetadata, SessionMessage
from mcp.types import (
    INVALID_PARAMS,
    ErrorData,
    GetTaskPayloadRequest,
    GetTaskPayloadResult,
    JSONRPCMessage,
    RelatedTaskMetadata,
    RequestId,
)

logger = logging.getLogger(__name__)


class TaskResultHandler:
    """
    Handler for tasks/result that implements the message queue pattern.

    This handler:
    1. Dequeues pending messages (elicitations, notifications) for the task
    2. Sends them to the client via the response stream
    3. Waits for responses and resolves them back to callers
    4. Blocks until task reaches terminal state
    5. Returns the final result

    Usage:
        # Create handler with store and queue
        handler = TaskResultHandler(task_store, message_queue)

        # Register it with the server
        @server.experimental.get_task_result()
        async def handle_task_result(req: GetTaskPayloadRequest) -> GetTaskPayloadResult:
            ctx = server.request_context
            return await handler.handle(req, ctx.session, ctx.request_id)

        # Or use the convenience method
        handler.register(server)
    """

    def __init__(
        self,
        store: TaskStore,
        queue: TaskMessageQueue,
    ):
        self._store = store
        self._queue = queue
        # Map from internal request ID to resolver for routing responses
        self._pending_requests: dict[RequestId, Resolver[dict[str, Any]]] = {}

    async def send_message(
        self,
        session: ServerSession,
        message: SessionMessage,
    ) -> None:
        """
        Send a message via the session.

        This is a helper for delivering queued task messages.
        """
        await session.send_message(message)

    async def handle(
        self,
        request: GetTaskPayloadRequest,
        session: ServerSession,
        request_id: RequestId,
    ) -> GetTaskPayloadResult:
        """
        Handle a tasks/result request.

        This implements the dequeue-send-wait loop:
        1. Dequeue all pending messages
        2. Send each via transport with relatedRequestId = this request's ID
        3. If task not terminal, wait for status change
        4. Loop until task is terminal
        5. Return final result

        Args:
            request: The GetTaskPayloadRequest
            session: The server session for sending messages
            request_id: The request ID for relatedRequestId routing

        Returns:
            GetTaskPayloadResult with the task's final payload
        """
        task_id = request.params.taskId

        while True:
            task = await self._store.get_task(task_id)
            if task is None:
                raise McpError(
                    ErrorData(
                        code=INVALID_PARAMS,
                        message=f"Task not found: {task_id}",
                    )
                )

            await self._deliver_queued_messages(task_id, session, request_id)

            # If task is terminal, return result
            if is_terminal(task.status):
                result = await self._store.get_result(task_id)
                # GetTaskPayloadResult is a Result with extra="allow"
                # The stored result contains the actual payload data
                # Per spec: tasks/result MUST include _meta with related-task metadata
                related_task = RelatedTaskMetadata(taskId=task_id)
                related_task_meta: dict[str, Any] = {RELATED_TASK_METADATA_KEY: related_task.model_dump(by_alias=True)}
                if result is not None:
                    result_data = result.model_dump(by_alias=True)
                    existing_meta: dict[str, Any] = result_data.get("_meta") or {}
                    result_data["_meta"] = {**existing_meta, **related_task_meta}
                    return GetTaskPayloadResult.model_validate(result_data)
                return GetTaskPayloadResult.model_validate({"_meta": related_task_meta})

            # Wait for task update (status change or new messages)
            await self._wait_for_task_update(task_id)

    async def _deliver_queued_messages(
        self,
        task_id: str,
        session: ServerSession,
        request_id: RequestId,
    ) -> None:
        """
        Dequeue and send all pending messages for a task.

        Each message is sent via the session's write stream with
        relatedRequestId set so responses route back to this stream.
        """
        while True:
            message = await self._queue.dequeue(task_id)
            if message is None:
                break

            # If this is a request (not notification), wait for response
            if message.type == "request" and message.resolver is not None:
                # Store the resolver so we can route the response back
                original_id = message.original_request_id
                if original_id is not None:
                    self._pending_requests[original_id] = message.resolver

            logger.debug("Delivering queued message for task %s: %s", task_id, message.type)

            # Send the message with relatedRequestId for routing
            session_message = SessionMessage(
                message=JSONRPCMessage(message.message),
                metadata=ServerMessageMetadata(related_request_id=request_id),
            )
            await self.send_message(session, session_message)

    async def _wait_for_task_update(self, task_id: str) -> None:
        """
        Wait for task to be updated (status change or new message).

        Races between store update and queue message - first one wins.
        """
        async with anyio.create_task_group() as tg:

            async def wait_for_store() -> None:
                try:
                    await self._store.wait_for_update(task_id)
                except Exception:
                    pass
                finally:
                    tg.cancel_scope.cancel()

            async def wait_for_queue() -> None:
                try:
                    await self._queue.wait_for_message(task_id)
                except Exception:
                    pass
                finally:
                    tg.cancel_scope.cancel()

            tg.start_soon(wait_for_store)
            tg.start_soon(wait_for_queue)

    def route_response(self, request_id: RequestId, response: dict[str, Any]) -> bool:
        """
        Route a response back to the waiting resolver.

        This is called when a response arrives for a queued request.

        Args:
            request_id: The request ID from the response
            response: The response data

        Returns:
            True if response was routed, False if no pending request
        """
        resolver = self._pending_requests.pop(request_id, None)
        if resolver is not None and not resolver.done():
            resolver.set_result(response)
            return True
        return False

    def route_error(self, request_id: RequestId, error: ErrorData) -> bool:
        """
        Route an error back to the waiting resolver.

        Args:
            request_id: The request ID from the error response
            error: The error data

        Returns:
            True if error was routed, False if no pending request
        """
        resolver = self._pending_requests.pop(request_id, None)
        if resolver is not None and not resolver.done():
            resolver.set_exception(McpError(error))
            return True
        return False
