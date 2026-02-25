"""
Helper functions for pure task management.

These helpers work with pure TaskContext and don't require server dependencies.
For server-integrated task helpers, use mcp.server.experimental.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from uuid import uuid4

from mcp.shared.exceptions import McpError
from mcp.shared.experimental.tasks.context import TaskContext
from mcp.shared.experimental.tasks.store import TaskStore
from mcp.types import (
    INVALID_PARAMS,
    TASK_STATUS_CANCELLED,
    TASK_STATUS_COMPLETED,
    TASK_STATUS_FAILED,
    TASK_STATUS_WORKING,
    CancelTaskResult,
    ErrorData,
    Task,
    TaskMetadata,
    TaskStatus,
)

# Metadata key for model-immediate-response (per MCP spec)
# Servers MAY include this in CreateTaskResult._meta to provide an immediate
# response string while the task executes in the background.
MODEL_IMMEDIATE_RESPONSE_KEY = "io.modelcontextprotocol/model-immediate-response"

# Metadata key for associating requests with a task (per MCP spec)
RELATED_TASK_METADATA_KEY = "io.modelcontextprotocol/related-task"


def is_terminal(status: TaskStatus) -> bool:
    """
    Check if a task status represents a terminal state.

    Terminal states are those where the task has finished and will not change.

    Args:
        status: The task status to check

    Returns:
        True if the status is terminal (completed, failed, or cancelled)
    """
    return status in (TASK_STATUS_COMPLETED, TASK_STATUS_FAILED, TASK_STATUS_CANCELLED)


async def cancel_task(
    store: TaskStore,
    task_id: str,
) -> CancelTaskResult:
    """
    Cancel a task with spec-compliant validation.

    Per spec: "Receivers MUST reject cancellation of terminal status tasks
    with -32602 (Invalid params)"

    This helper validates that the task exists and is not in a terminal state
    before setting it to "cancelled".

    Args:
        store: The task store
        task_id: The task identifier to cancel

    Returns:
        CancelTaskResult with the cancelled task state

    Raises:
        McpError: With INVALID_PARAMS (-32602) if:
            - Task does not exist
            - Task is already in a terminal state (completed, failed, cancelled)

    Example:
        @server.experimental.cancel_task()
        async def handle_cancel(request: CancelTaskRequest) -> CancelTaskResult:
            return await cancel_task(store, request.params.taskId)
    """
    task = await store.get_task(task_id)
    if task is None:
        raise McpError(
            ErrorData(
                code=INVALID_PARAMS,
                message=f"Task not found: {task_id}",
            )
        )

    if is_terminal(task.status):
        raise McpError(
            ErrorData(
                code=INVALID_PARAMS,
                message=f"Cannot cancel task in terminal state '{task.status}'",
            )
        )

    # Update task to cancelled status
    cancelled_task = await store.update_task(task_id, status=TASK_STATUS_CANCELLED)
    return CancelTaskResult(**cancelled_task.model_dump())


def generate_task_id() -> str:
    """Generate a unique task ID."""
    return str(uuid4())


def create_task_state(
    metadata: TaskMetadata,
    task_id: str | None = None,
) -> Task:
    """
    Create a Task object with initial state.

    This is a helper for TaskStore implementations.

    Args:
        metadata: Task metadata
        task_id: Optional task ID (generated if not provided)

    Returns:
        A new Task in "working" status
    """
    now = datetime.now(timezone.utc)
    return Task(
        taskId=task_id or generate_task_id(),
        status=TASK_STATUS_WORKING,
        createdAt=now,
        lastUpdatedAt=now,
        ttl=metadata.ttl,
        pollInterval=500,  # Default 500ms poll interval
    )


@asynccontextmanager
async def task_execution(
    task_id: str,
    store: TaskStore,
) -> AsyncIterator[TaskContext]:
    """
    Context manager for safe task execution (pure, no server dependencies).

    Loads a task from the store and provides a TaskContext for the work.
    If an unhandled exception occurs, the task is automatically marked as failed
    and the exception is suppressed (since the failure is captured in task state).

    This is useful for distributed workers that don't have a server session.

    Args:
        task_id: The task identifier to execute
        store: The task store (must be accessible by the worker)

    Yields:
        TaskContext for updating status and completing/failing the task

    Raises:
        ValueError: If the task is not found in the store

    Example (distributed worker):
        async def worker_process(task_id: str):
            store = RedisTaskStore(redis_url)
            async with task_execution(task_id, store) as ctx:
                await ctx.update_status("Working...")
                result = await do_work()
                await ctx.complete(result)
    """
    task = await store.get_task(task_id)
    if task is None:
        raise ValueError(f"Task {task_id} not found")

    ctx = TaskContext(task, store)
    try:
        yield ctx
    except Exception as e:
        # Auto-fail the task if an exception occurs and task isn't already terminal
        # Exception is suppressed since failure is captured in task state
        if not is_terminal(ctx.task.status):
            await ctx.fail(str(e))
        # Don't re-raise - the failure is recorded in task state
