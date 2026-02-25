"""
Experimental server session features for server→client task operations.

This module provides the server-side equivalent of ExperimentalClientFeatures,
allowing the server to send task-augmented requests to the client and poll for results.

WARNING: These APIs are experimental and may change without notice.
"""

from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any, TypeVar

import mcp.types as types
from mcp.server.validation import validate_sampling_tools, validate_tool_use_result_messages
from mcp.shared.experimental.tasks.capabilities import (
    require_task_augmented_elicitation,
    require_task_augmented_sampling,
)
from mcp.shared.experimental.tasks.polling import poll_until_terminal

if TYPE_CHECKING:
    from mcp.server.session import ServerSession

ResultT = TypeVar("ResultT", bound=types.Result)


class ExperimentalServerSessionFeatures:
    """
    Experimental server session features for server→client task operations.

    This provides the server-side equivalent of ExperimentalClientFeatures,
    allowing the server to send task-augmented requests to the client and
    poll for results.

    WARNING: These APIs are experimental and may change without notice.

    Access via session.experimental:
        result = await session.experimental.elicit_as_task(...)
    """

    def __init__(self, session: "ServerSession") -> None:
        self._session = session

    async def get_task(self, task_id: str) -> types.GetTaskResult:
        """
        Send tasks/get to the client to get task status.

        Args:
            task_id: The task identifier

        Returns:
            GetTaskResult containing the task status
        """
        return await self._session.send_request(
            types.ServerRequest(types.GetTaskRequest(params=types.GetTaskRequestParams(taskId=task_id))),
            types.GetTaskResult,
        )

    async def get_task_result(
        self,
        task_id: str,
        result_type: type[ResultT],
    ) -> ResultT:
        """
        Send tasks/result to the client to retrieve the final result.

        Args:
            task_id: The task identifier
            result_type: The expected result type

        Returns:
            The task result, validated against result_type
        """
        return await self._session.send_request(
            types.ServerRequest(types.GetTaskPayloadRequest(params=types.GetTaskPayloadRequestParams(taskId=task_id))),
            result_type,
        )

    async def poll_task(self, task_id: str) -> AsyncIterator[types.GetTaskResult]:
        """
        Poll a client task until it reaches terminal status.

        Yields GetTaskResult for each poll, allowing the caller to react to
        status changes. Exits when task reaches a terminal status.

        Respects the pollInterval hint from the client.

        Args:
            task_id: The task identifier

        Yields:
            GetTaskResult for each poll
        """
        async for status in poll_until_terminal(self.get_task, task_id):
            yield status

    async def elicit_as_task(
        self,
        message: str,
        requestedSchema: types.ElicitRequestedSchema,
        *,
        ttl: int = 60000,
    ) -> types.ElicitResult:
        """
        Send a task-augmented elicitation to the client and poll until complete.

        The client will create a local task, process the elicitation asynchronously,
        and return the result when ready. This method handles the full flow:
        1. Send elicitation with task field
        2. Receive CreateTaskResult from client
        3. Poll client's task until terminal
        4. Retrieve and return the final ElicitResult

        Args:
            message: The message to present to the user
            requestedSchema: Schema defining the expected response
            ttl: Task time-to-live in milliseconds

        Returns:
            The client's elicitation response

        Raises:
            McpError: If client doesn't support task-augmented elicitation
        """
        client_caps = self._session.client_params.capabilities if self._session.client_params else None
        require_task_augmented_elicitation(client_caps)

        create_result = await self._session.send_request(
            types.ServerRequest(
                types.ElicitRequest(
                    params=types.ElicitRequestFormParams(
                        message=message,
                        requestedSchema=requestedSchema,
                        task=types.TaskMetadata(ttl=ttl),
                    )
                )
            ),
            types.CreateTaskResult,
        )

        task_id = create_result.task.taskId

        async for _ in self.poll_task(task_id):
            pass

        return await self.get_task_result(task_id, types.ElicitResult)

    async def create_message_as_task(
        self,
        messages: list[types.SamplingMessage],
        *,
        max_tokens: int,
        ttl: int = 60000,
        system_prompt: str | None = None,
        include_context: types.IncludeContext | None = None,
        temperature: float | None = None,
        stop_sequences: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        model_preferences: types.ModelPreferences | None = None,
        tools: list[types.Tool] | None = None,
        tool_choice: types.ToolChoice | None = None,
    ) -> types.CreateMessageResult:
        """
        Send a task-augmented sampling request and poll until complete.

        The client will create a local task, process the sampling request
        asynchronously, and return the result when ready.

        Args:
            messages: The conversation messages for sampling
            max_tokens: Maximum tokens in the response
            ttl: Task time-to-live in milliseconds
            system_prompt: Optional system prompt
            include_context: Context inclusion strategy
            temperature: Sampling temperature
            stop_sequences: Stop sequences
            metadata: Additional metadata
            model_preferences: Model selection preferences
            tools: Optional list of tools the LLM can use during sampling
            tool_choice: Optional control over tool usage behavior

        Returns:
            The sampling result from the client

        Raises:
            McpError: If client doesn't support task-augmented sampling or tools
            ValueError: If tool_use or tool_result message structure is invalid
        """
        client_caps = self._session.client_params.capabilities if self._session.client_params else None
        require_task_augmented_sampling(client_caps)
        validate_sampling_tools(client_caps, tools, tool_choice)
        validate_tool_use_result_messages(messages)

        create_result = await self._session.send_request(
            types.ServerRequest(
                types.CreateMessageRequest(
                    params=types.CreateMessageRequestParams(
                        messages=messages,
                        maxTokens=max_tokens,
                        systemPrompt=system_prompt,
                        includeContext=include_context,
                        temperature=temperature,
                        stopSequences=stop_sequences,
                        metadata=metadata,
                        modelPreferences=model_preferences,
                        tools=tools,
                        toolChoice=tool_choice,
                        task=types.TaskMetadata(ttl=ttl),
                    )
                )
            ),
            types.CreateTaskResult,
        )

        task_id = create_result.task.taskId

        async for _ in self.poll_task(task_id):
            pass

        return await self.get_task_result(task_id, types.CreateMessageResult)
