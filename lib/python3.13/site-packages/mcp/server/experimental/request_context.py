"""
Experimental request context features.

This module provides the Experimental class which gives access to experimental
features within a request context, such as task-augmented request handling.

WARNING: These APIs are experimental and may change without notice.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from mcp.server.experimental.task_context import ServerTaskContext
from mcp.server.experimental.task_support import TaskSupport
from mcp.server.session import ServerSession
from mcp.shared.exceptions import McpError
from mcp.shared.experimental.tasks.helpers import MODEL_IMMEDIATE_RESPONSE_KEY, is_terminal
from mcp.types import (
    METHOD_NOT_FOUND,
    TASK_FORBIDDEN,
    TASK_REQUIRED,
    ClientCapabilities,
    CreateTaskResult,
    ErrorData,
    Result,
    TaskExecutionMode,
    TaskMetadata,
    Tool,
)


@dataclass
class Experimental:
    """
    Experimental features context for task-augmented requests.

    Provides helpers for validating task execution compatibility and
    running tasks with automatic lifecycle management.

    WARNING: This API is experimental and may change without notice.
    """

    task_metadata: TaskMetadata | None = None
    _client_capabilities: ClientCapabilities | None = field(default=None, repr=False)
    _session: ServerSession | None = field(default=None, repr=False)
    _task_support: TaskSupport | None = field(default=None, repr=False)

    @property
    def is_task(self) -> bool:
        """Check if this request is task-augmented."""
        return self.task_metadata is not None

    @property
    def client_supports_tasks(self) -> bool:
        """Check if the client declared task support."""
        if self._client_capabilities is None:
            return False
        return self._client_capabilities.tasks is not None

    def validate_task_mode(
        self,
        tool_task_mode: TaskExecutionMode | None,
        *,
        raise_error: bool = True,
    ) -> ErrorData | None:
        """
        Validate that the request is compatible with the tool's task execution mode.

        Per MCP spec:
        - "required": Clients MUST invoke as task. Server returns -32601 if not.
        - "forbidden" (or None): Clients MUST NOT invoke as task. Server returns -32601 if they do.
        - "optional": Either is acceptable.

        Args:
            tool_task_mode: The tool's execution.taskSupport value
                ("forbidden", "optional", "required", or None)
            raise_error: If True, raises McpError on validation failure. If False, returns ErrorData.

        Returns:
            None if valid, ErrorData if invalid and raise_error=False

        Raises:
            McpError: If invalid and raise_error=True
        """

        mode = tool_task_mode or TASK_FORBIDDEN

        error: ErrorData | None = None

        if mode == TASK_REQUIRED and not self.is_task:
            error = ErrorData(
                code=METHOD_NOT_FOUND,
                message="This tool requires task-augmented invocation",
            )
        elif mode == TASK_FORBIDDEN and self.is_task:
            error = ErrorData(
                code=METHOD_NOT_FOUND,
                message="This tool does not support task-augmented invocation",
            )

        if error is not None and raise_error:
            raise McpError(error)

        return error

    def validate_for_tool(
        self,
        tool: Tool,
        *,
        raise_error: bool = True,
    ) -> ErrorData | None:
        """
        Validate that the request is compatible with the given tool.

        Convenience wrapper around validate_task_mode that extracts the mode from a Tool.

        Args:
            tool: The Tool definition
            raise_error: If True, raises McpError on validation failure.

        Returns:
            None if valid, ErrorData if invalid and raise_error=False
        """
        mode = tool.execution.taskSupport if tool.execution else None
        return self.validate_task_mode(mode, raise_error=raise_error)

    def can_use_tool(self, tool_task_mode: TaskExecutionMode | None) -> bool:
        """
        Check if this client can use a tool with the given task mode.

        Useful for filtering tool lists or providing warnings.
        Returns False if tool requires "required" but client doesn't support tasks.

        Args:
            tool_task_mode: The tool's execution.taskSupport value

        Returns:
            True if the client can use this tool, False otherwise
        """
        mode = tool_task_mode or TASK_FORBIDDEN
        if mode == TASK_REQUIRED and not self.client_supports_tasks:
            return False
        return True

    async def run_task(
        self,
        work: Callable[[ServerTaskContext], Awaitable[Result]],
        *,
        task_id: str | None = None,
        model_immediate_response: str | None = None,
    ) -> CreateTaskResult:
        """
        Create a task, spawn background work, and return CreateTaskResult immediately.

        This is the recommended way to handle task-augmented tool calls. It:
        1. Creates a task in the store
        2. Spawns the work function in a background task
        3. Returns CreateTaskResult immediately

        The work function receives a ServerTaskContext with:
        - elicit() for sending elicitation requests
        - create_message() for sampling requests
        - update_status() for progress updates
        - complete()/fail() for finishing the task

        When work() returns a Result, the task is auto-completed with that result.
        If work() raises an exception, the task is auto-failed.

        Args:
            work: Async function that does the actual work
            task_id: Optional task ID (generated if not provided)
            model_immediate_response: Optional string to include in _meta as
                io.modelcontextprotocol/model-immediate-response

        Returns:
            CreateTaskResult to return to the client

        Raises:
            RuntimeError: If task support is not enabled or task_metadata is missing

        Example:
            @server.call_tool()
            async def handle_tool(name: str, args: dict):
                ctx = server.request_context

                async def work(task: ServerTaskContext) -> CallToolResult:
                    result = await task.elicit(
                        message="Are you sure?",
                        requestedSchema={"type": "object", ...}
                    )
                    confirmed = result.content.get("confirm", False)
                    return CallToolResult(content=[TextContent(text="Done" if confirmed else "Cancelled")])

                return await ctx.experimental.run_task(work)

        WARNING: This API is experimental and may change without notice.
        """
        if self._task_support is None:
            raise RuntimeError("Task support not enabled. Call server.experimental.enable_tasks() first.")
        if self._session is None:
            raise RuntimeError("Session not available.")
        if self.task_metadata is None:
            raise RuntimeError(
                "Request is not task-augmented (no task field in params). "
                "The client must send a task-augmented request."
            )

        support = self._task_support
        # Access task_group via TaskSupport - raises if not in run() context
        task_group = support.task_group

        task = await support.store.create_task(self.task_metadata, task_id)

        task_ctx = ServerTaskContext(
            task=task,
            store=support.store,
            session=self._session,
            queue=support.queue,
            handler=support.handler,
        )

        async def execute() -> None:
            try:
                result = await work(task_ctx)
                if not is_terminal(task_ctx.task.status):
                    await task_ctx.complete(result)
            except Exception as e:
                if not is_terminal(task_ctx.task.status):
                    await task_ctx.fail(str(e))

        task_group.start_soon(execute)

        meta: dict[str, Any] | None = None
        if model_immediate_response is not None:
            meta = {MODEL_IMMEDIATE_RESPONSE_KEY: model_immediate_response}

        return CreateTaskResult(task=task, **{"_meta": meta} if meta else {})
