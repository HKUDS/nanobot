"""
Experimental client-side task support.

This module provides client methods for interacting with MCP tasks.

WARNING: These APIs are experimental and may change without notice.

Example:
    # Call a tool as a task
    result = await session.experimental.call_tool_as_task("tool_name", {"arg": "value"})
    task_id = result.task.taskId

    # Get task status
    status = await session.experimental.get_task(task_id)

    # Get task result when complete
    if status.status == "completed":
        result = await session.experimental.get_task_result(task_id, CallToolResult)

    # List all tasks
    tasks = await session.experimental.list_tasks()

    # Cancel a task
    await session.experimental.cancel_task(task_id)
"""

from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any, TypeVar

import mcp.types as types
from mcp.shared.experimental.tasks.polling import poll_until_terminal

if TYPE_CHECKING:
    from mcp.client.session import ClientSession

ResultT = TypeVar("ResultT", bound=types.Result)


class ExperimentalClientFeatures:
    """
    Experimental client features for tasks and other experimental APIs.

    WARNING: These APIs are experimental and may change without notice.

    Access via session.experimental:
        status = await session.experimental.get_task(task_id)
    """

    def __init__(self, session: "ClientSession") -> None:
        self._session = session

    async def call_tool_as_task(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
        *,
        ttl: int = 60000,
        meta: dict[str, Any] | None = None,
    ) -> types.CreateTaskResult:
        """Call a tool as a task, returning a CreateTaskResult for polling.

        This is a convenience method for calling tools that support task execution.
        The server will return a task reference instead of the immediate result,
        which can then be polled via `get_task()` and retrieved via `get_task_result()`.

        Args:
            name: The tool name
            arguments: Tool arguments
            ttl: Task time-to-live in milliseconds (default: 60000 = 1 minute)
            meta: Optional metadata to include in the request

        Returns:
            CreateTaskResult containing the task reference

        Example:
            # Create task
            result = await session.experimental.call_tool_as_task(
                "long_running_tool", {"input": "data"}
            )
            task_id = result.task.taskId

            # Poll for completion
            while True:
                status = await session.experimental.get_task(task_id)
                if status.status == "completed":
                    break
                await asyncio.sleep(0.5)

            # Get result
            final = await session.experimental.get_task_result(task_id, CallToolResult)
        """
        _meta: types.RequestParams.Meta | None = None
        if meta is not None:
            _meta = types.RequestParams.Meta(**meta)

        return await self._session.send_request(
            types.ClientRequest(
                types.CallToolRequest(
                    params=types.CallToolRequestParams(
                        name=name,
                        arguments=arguments,
                        task=types.TaskMetadata(ttl=ttl),
                        _meta=_meta,
                    ),
                )
            ),
            types.CreateTaskResult,
        )

    async def get_task(self, task_id: str) -> types.GetTaskResult:
        """
        Get the current status of a task.

        Args:
            task_id: The task identifier

        Returns:
            GetTaskResult containing the task status and metadata
        """
        return await self._session.send_request(
            types.ClientRequest(
                types.GetTaskRequest(
                    params=types.GetTaskRequestParams(taskId=task_id),
                )
            ),
            types.GetTaskResult,
        )

    async def get_task_result(
        self,
        task_id: str,
        result_type: type[ResultT],
    ) -> ResultT:
        """
        Get the result of a completed task.

        The result type depends on the original request type:
        - tools/call tasks return CallToolResult
        - Other request types return their corresponding result type

        Args:
            task_id: The task identifier
            result_type: The expected result type (e.g., CallToolResult)

        Returns:
            The task result, validated against result_type
        """
        return await self._session.send_request(
            types.ClientRequest(
                types.GetTaskPayloadRequest(
                    params=types.GetTaskPayloadRequestParams(taskId=task_id),
                )
            ),
            result_type,
        )

    async def list_tasks(
        self,
        cursor: str | None = None,
    ) -> types.ListTasksResult:
        """
        List all tasks.

        Args:
            cursor: Optional pagination cursor

        Returns:
            ListTasksResult containing tasks and optional next cursor
        """
        params = types.PaginatedRequestParams(cursor=cursor) if cursor else None
        return await self._session.send_request(
            types.ClientRequest(
                types.ListTasksRequest(params=params),
            ),
            types.ListTasksResult,
        )

    async def cancel_task(self, task_id: str) -> types.CancelTaskResult:
        """
        Cancel a running task.

        Args:
            task_id: The task identifier

        Returns:
            CancelTaskResult with the updated task state
        """
        return await self._session.send_request(
            types.ClientRequest(
                types.CancelTaskRequest(
                    params=types.CancelTaskRequestParams(taskId=task_id),
                )
            ),
            types.CancelTaskResult,
        )

    async def poll_task(self, task_id: str) -> AsyncIterator[types.GetTaskResult]:
        """
        Poll a task until it reaches a terminal status.

        Yields GetTaskResult for each poll, allowing the caller to react to
        status changes (e.g., handle input_required). Exits when task reaches
        a terminal status (completed, failed, cancelled).

        Respects the pollInterval hint from the server.

        Args:
            task_id: The task identifier

        Yields:
            GetTaskResult for each poll

        Example:
            async for status in session.experimental.poll_task(task_id):
                print(f"Status: {status.status}")
                if status.status == "input_required":
                    # Handle elicitation request via tasks/result
                    pass

            # Task is now terminal, get the result
            result = await session.experimental.get_task_result(task_id, CallToolResult)
        """
        async for status in poll_until_terminal(self.get_task, task_id):
            yield status
