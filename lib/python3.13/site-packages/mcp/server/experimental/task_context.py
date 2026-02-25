"""
ServerTaskContext - Server-integrated task context with elicitation and sampling.

This wraps the pure TaskContext and adds server-specific functionality:
- Elicitation (task.elicit())
- Sampling (task.create_message())
- Status notifications
"""

from typing import Any

import anyio

from mcp.server.experimental.task_result_handler import TaskResultHandler
from mcp.server.session import ServerSession
from mcp.server.validation import validate_sampling_tools, validate_tool_use_result_messages
from mcp.shared.exceptions import McpError
from mcp.shared.experimental.tasks.capabilities import (
    require_task_augmented_elicitation,
    require_task_augmented_sampling,
)
from mcp.shared.experimental.tasks.context import TaskContext
from mcp.shared.experimental.tasks.message_queue import QueuedMessage, TaskMessageQueue
from mcp.shared.experimental.tasks.resolver import Resolver
from mcp.shared.experimental.tasks.store import TaskStore
from mcp.types import (
    INVALID_REQUEST,
    TASK_STATUS_INPUT_REQUIRED,
    TASK_STATUS_WORKING,
    ClientCapabilities,
    CreateMessageResult,
    CreateTaskResult,
    ElicitationCapability,
    ElicitRequestedSchema,
    ElicitResult,
    ErrorData,
    IncludeContext,
    ModelPreferences,
    RequestId,
    Result,
    SamplingCapability,
    SamplingMessage,
    ServerNotification,
    Task,
    TaskMetadata,
    TaskStatusNotification,
    TaskStatusNotificationParams,
    Tool,
    ToolChoice,
)


class ServerTaskContext:
    """
    Server-integrated task context with elicitation and sampling.

    This wraps a pure TaskContext and adds server-specific functionality:
    - elicit() for sending elicitation requests to the client
    - create_message() for sampling requests
    - Status notifications via the session

    Example:
        async def my_task_work(task: ServerTaskContext) -> CallToolResult:
            await task.update_status("Starting...")

            result = await task.elicit(
                message="Continue?",
                requestedSchema={"type": "object", "properties": {"ok": {"type": "boolean"}}}
            )

            if result.content.get("ok"):
                return CallToolResult(content=[TextContent(text="Done!")])
            else:
                return CallToolResult(content=[TextContent(text="Cancelled")])
    """

    def __init__(
        self,
        *,
        task: Task,
        store: TaskStore,
        session: ServerSession,
        queue: TaskMessageQueue,
        handler: TaskResultHandler | None = None,
    ):
        """
        Create a ServerTaskContext.

        Args:
            task: The Task object
            store: The task store
            session: The server session
            queue: The message queue for elicitation/sampling
            handler: The result handler for response routing (required for elicit/create_message)
        """
        self._ctx = TaskContext(task=task, store=store)
        self._session = session
        self._queue = queue
        self._handler = handler
        self._store = store

    # Delegate pure properties to inner context

    @property
    def task_id(self) -> str:
        """The task identifier."""
        return self._ctx.task_id

    @property
    def task(self) -> Task:
        """The current task state."""
        return self._ctx.task

    @property
    def is_cancelled(self) -> bool:
        """Whether cancellation has been requested."""
        return self._ctx.is_cancelled

    def request_cancellation(self) -> None:
        """Request cancellation of this task."""
        self._ctx.request_cancellation()

    # Enhanced methods with notifications

    async def update_status(self, message: str, *, notify: bool = True) -> None:
        """
        Update the task's status message.

        Args:
            message: The new status message
            notify: Whether to send a notification to the client
        """
        await self._ctx.update_status(message)
        if notify:
            await self._send_notification()

    async def complete(self, result: Result, *, notify: bool = True) -> None:
        """
        Mark the task as completed with the given result.

        Args:
            result: The task result
            notify: Whether to send a notification to the client
        """
        await self._ctx.complete(result)
        if notify:
            await self._send_notification()

    async def fail(self, error: str, *, notify: bool = True) -> None:
        """
        Mark the task as failed with an error message.

        Args:
            error: The error message
            notify: Whether to send a notification to the client
        """
        await self._ctx.fail(error)
        if notify:
            await self._send_notification()

    async def _send_notification(self) -> None:
        """Send a task status notification to the client."""
        task = self._ctx.task
        await self._session.send_notification(
            ServerNotification(
                TaskStatusNotification(
                    params=TaskStatusNotificationParams(
                        taskId=task.taskId,
                        status=task.status,
                        statusMessage=task.statusMessage,
                        createdAt=task.createdAt,
                        lastUpdatedAt=task.lastUpdatedAt,
                        ttl=task.ttl,
                        pollInterval=task.pollInterval,
                    )
                )
            )
        )

    # Server-specific methods: elicitation and sampling

    def _check_elicitation_capability(self) -> None:
        """Check if the client supports elicitation."""
        if not self._session.check_client_capability(ClientCapabilities(elicitation=ElicitationCapability())):
            raise McpError(
                ErrorData(
                    code=INVALID_REQUEST,
                    message="Client does not support elicitation capability",
                )
            )

    def _check_sampling_capability(self) -> None:
        """Check if the client supports sampling."""
        if not self._session.check_client_capability(ClientCapabilities(sampling=SamplingCapability())):
            raise McpError(
                ErrorData(
                    code=INVALID_REQUEST,
                    message="Client does not support sampling capability",
                )
            )

    async def elicit(
        self,
        message: str,
        requestedSchema: ElicitRequestedSchema,
    ) -> ElicitResult:
        """
        Send an elicitation request via the task message queue.

        This method:
        1. Checks client capability
        2. Updates task status to "input_required"
        3. Queues the elicitation request
        4. Waits for the response (delivered via tasks/result round-trip)
        5. Updates task status back to "working"
        6. Returns the result

        Args:
            message: The message to present to the user
            requestedSchema: Schema defining the expected response structure

        Returns:
            The client's response

        Raises:
            McpError: If client doesn't support elicitation capability
        """
        self._check_elicitation_capability()

        if self._handler is None:
            raise RuntimeError("handler is required for elicit(). Pass handler= to ServerTaskContext.")

        # Update status to input_required
        await self._store.update_task(self.task_id, status=TASK_STATUS_INPUT_REQUIRED)

        # Build the request using session's helper
        request = self._session._build_elicit_form_request(  # pyright: ignore[reportPrivateUsage]
            message=message,
            requestedSchema=requestedSchema,
            related_task_id=self.task_id,
        )
        request_id: RequestId = request.id

        resolver: Resolver[dict[str, Any]] = Resolver()
        self._handler._pending_requests[request_id] = resolver  # pyright: ignore[reportPrivateUsage]

        queued = QueuedMessage(
            type="request",
            message=request,
            resolver=resolver,
            original_request_id=request_id,
        )
        await self._queue.enqueue(self.task_id, queued)

        try:
            # Wait for response (routed back via TaskResultHandler)
            response_data = await resolver.wait()
            await self._store.update_task(self.task_id, status=TASK_STATUS_WORKING)
            return ElicitResult.model_validate(response_data)
        except anyio.get_cancelled_exc_class():  # pragma: no cover
            # Coverage can't track async exception handlers reliably.
            # This path is tested in test_elicit_restores_status_on_cancellation
            # which verifies status is restored to "working" after cancellation.
            await self._store.update_task(self.task_id, status=TASK_STATUS_WORKING)
            raise

    async def elicit_url(
        self,
        message: str,
        url: str,
        elicitation_id: str,
    ) -> ElicitResult:
        """
        Send a URL mode elicitation request via the task message queue.

        This directs the user to an external URL for out-of-band interactions
        like OAuth flows, credential collection, or payment processing.

        This method:
        1. Checks client capability
        2. Updates task status to "input_required"
        3. Queues the elicitation request
        4. Waits for the response (delivered via tasks/result round-trip)
        5. Updates task status back to "working"
        6. Returns the result

        Args:
            message: Human-readable explanation of why the interaction is needed
            url: The URL the user should navigate to
            elicitation_id: Unique identifier for tracking this elicitation

        Returns:
            The client's response indicating acceptance, decline, or cancellation

        Raises:
            McpError: If client doesn't support elicitation capability
            RuntimeError: If handler is not configured
        """
        self._check_elicitation_capability()

        if self._handler is None:
            raise RuntimeError("handler is required for elicit_url(). Pass handler= to ServerTaskContext.")

        # Update status to input_required
        await self._store.update_task(self.task_id, status=TASK_STATUS_INPUT_REQUIRED)

        # Build the request using session's helper
        request = self._session._build_elicit_url_request(  # pyright: ignore[reportPrivateUsage]
            message=message,
            url=url,
            elicitation_id=elicitation_id,
            related_task_id=self.task_id,
        )
        request_id: RequestId = request.id

        resolver: Resolver[dict[str, Any]] = Resolver()
        self._handler._pending_requests[request_id] = resolver  # pyright: ignore[reportPrivateUsage]

        queued = QueuedMessage(
            type="request",
            message=request,
            resolver=resolver,
            original_request_id=request_id,
        )
        await self._queue.enqueue(self.task_id, queued)

        try:
            # Wait for response (routed back via TaskResultHandler)
            response_data = await resolver.wait()
            await self._store.update_task(self.task_id, status=TASK_STATUS_WORKING)
            return ElicitResult.model_validate(response_data)
        except anyio.get_cancelled_exc_class():  # pragma: no cover
            await self._store.update_task(self.task_id, status=TASK_STATUS_WORKING)
            raise

    async def create_message(
        self,
        messages: list[SamplingMessage],
        *,
        max_tokens: int,
        system_prompt: str | None = None,
        include_context: IncludeContext | None = None,
        temperature: float | None = None,
        stop_sequences: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        model_preferences: ModelPreferences | None = None,
        tools: list[Tool] | None = None,
        tool_choice: ToolChoice | None = None,
    ) -> CreateMessageResult:
        """
        Send a sampling request via the task message queue.

        This method:
        1. Checks client capability
        2. Updates task status to "input_required"
        3. Queues the sampling request
        4. Waits for the response (delivered via tasks/result round-trip)
        5. Updates task status back to "working"
        6. Returns the result

        Args:
            messages: The conversation messages for sampling
            max_tokens: Maximum tokens in the response
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
            McpError: If client doesn't support sampling capability or tools
            ValueError: If tool_use or tool_result message structure is invalid
        """
        self._check_sampling_capability()
        client_caps = self._session.client_params.capabilities if self._session.client_params else None
        validate_sampling_tools(client_caps, tools, tool_choice)
        validate_tool_use_result_messages(messages)

        if self._handler is None:
            raise RuntimeError("handler is required for create_message(). Pass handler= to ServerTaskContext.")

        # Update status to input_required
        await self._store.update_task(self.task_id, status=TASK_STATUS_INPUT_REQUIRED)

        # Build the request using session's helper
        request = self._session._build_create_message_request(  # pyright: ignore[reportPrivateUsage]
            messages=messages,
            max_tokens=max_tokens,
            system_prompt=system_prompt,
            include_context=include_context,
            temperature=temperature,
            stop_sequences=stop_sequences,
            metadata=metadata,
            model_preferences=model_preferences,
            tools=tools,
            tool_choice=tool_choice,
            related_task_id=self.task_id,
        )
        request_id: RequestId = request.id

        resolver: Resolver[dict[str, Any]] = Resolver()
        self._handler._pending_requests[request_id] = resolver  # pyright: ignore[reportPrivateUsage]

        queued = QueuedMessage(
            type="request",
            message=request,
            resolver=resolver,
            original_request_id=request_id,
        )
        await self._queue.enqueue(self.task_id, queued)

        try:
            # Wait for response (routed back via TaskResultHandler)
            response_data = await resolver.wait()
            await self._store.update_task(self.task_id, status=TASK_STATUS_WORKING)
            return CreateMessageResult.model_validate(response_data)
        except anyio.get_cancelled_exc_class():  # pragma: no cover
            # Coverage can't track async exception handlers reliably.
            # This path is tested in test_create_message_restores_status_on_cancellation
            # which verifies status is restored to "working" after cancellation.
            await self._store.update_task(self.task_id, status=TASK_STATUS_WORKING)
            raise

    async def elicit_as_task(
        self,
        message: str,
        requestedSchema: ElicitRequestedSchema,
        *,
        ttl: int = 60000,
    ) -> ElicitResult:
        """
        Send a task-augmented elicitation via the queue, then poll client.

        This is for use inside a task-augmented tool call when you want the client
        to handle the elicitation as its own task. The elicitation request is queued
        and delivered when the client calls tasks/result. After the client responds
        with CreateTaskResult, we poll the client's task until complete.

        Args:
            message: The message to present to the user
            requestedSchema: Schema defining the expected response structure
            ttl: Task time-to-live in milliseconds for the client's task

        Returns:
            The client's elicitation response

        Raises:
            McpError: If client doesn't support task-augmented elicitation
            RuntimeError: If handler is not configured
        """
        client_caps = self._session.client_params.capabilities if self._session.client_params else None
        require_task_augmented_elicitation(client_caps)

        if self._handler is None:
            raise RuntimeError("handler is required for elicit_as_task()")

        # Update status to input_required
        await self._store.update_task(self.task_id, status=TASK_STATUS_INPUT_REQUIRED)

        request = self._session._build_elicit_form_request(  # pyright: ignore[reportPrivateUsage]
            message=message,
            requestedSchema=requestedSchema,
            related_task_id=self.task_id,
            task=TaskMetadata(ttl=ttl),
        )
        request_id: RequestId = request.id

        resolver: Resolver[dict[str, Any]] = Resolver()
        self._handler._pending_requests[request_id] = resolver  # pyright: ignore[reportPrivateUsage]

        queued = QueuedMessage(
            type="request",
            message=request,
            resolver=resolver,
            original_request_id=request_id,
        )
        await self._queue.enqueue(self.task_id, queued)

        try:
            # Wait for initial response (CreateTaskResult from client)
            response_data = await resolver.wait()
            create_result = CreateTaskResult.model_validate(response_data)
            client_task_id = create_result.task.taskId

            # Poll the client's task using session.experimental
            async for _ in self._session.experimental.poll_task(client_task_id):
                pass

            # Get final result from client
            result = await self._session.experimental.get_task_result(
                client_task_id,
                ElicitResult,
            )

            await self._store.update_task(self.task_id, status=TASK_STATUS_WORKING)
            return result

        except anyio.get_cancelled_exc_class():  # pragma: no cover
            await self._store.update_task(self.task_id, status=TASK_STATUS_WORKING)
            raise

    async def create_message_as_task(
        self,
        messages: list[SamplingMessage],
        *,
        max_tokens: int,
        ttl: int = 60000,
        system_prompt: str | None = None,
        include_context: IncludeContext | None = None,
        temperature: float | None = None,
        stop_sequences: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        model_preferences: ModelPreferences | None = None,
        tools: list[Tool] | None = None,
        tool_choice: ToolChoice | None = None,
    ) -> CreateMessageResult:
        """
        Send a task-augmented sampling request via the queue, then poll client.

        This is for use inside a task-augmented tool call when you want the client
        to handle the sampling as its own task. The request is queued and delivered
        when the client calls tasks/result. After the client responds with
        CreateTaskResult, we poll the client's task until complete.

        Args:
            messages: The conversation messages for sampling
            max_tokens: Maximum tokens in the response
            ttl: Task time-to-live in milliseconds for the client's task
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
            RuntimeError: If handler is not configured
        """
        client_caps = self._session.client_params.capabilities if self._session.client_params else None
        require_task_augmented_sampling(client_caps)
        validate_sampling_tools(client_caps, tools, tool_choice)
        validate_tool_use_result_messages(messages)

        if self._handler is None:
            raise RuntimeError("handler is required for create_message_as_task()")

        # Update status to input_required
        await self._store.update_task(self.task_id, status=TASK_STATUS_INPUT_REQUIRED)

        # Build request WITH task field for task-augmented sampling
        request = self._session._build_create_message_request(  # pyright: ignore[reportPrivateUsage]
            messages=messages,
            max_tokens=max_tokens,
            system_prompt=system_prompt,
            include_context=include_context,
            temperature=temperature,
            stop_sequences=stop_sequences,
            metadata=metadata,
            model_preferences=model_preferences,
            tools=tools,
            tool_choice=tool_choice,
            related_task_id=self.task_id,
            task=TaskMetadata(ttl=ttl),
        )
        request_id: RequestId = request.id

        resolver: Resolver[dict[str, Any]] = Resolver()
        self._handler._pending_requests[request_id] = resolver  # pyright: ignore[reportPrivateUsage]

        queued = QueuedMessage(
            type="request",
            message=request,
            resolver=resolver,
            original_request_id=request_id,
        )
        await self._queue.enqueue(self.task_id, queued)

        try:
            # Wait for initial response (CreateTaskResult from client)
            response_data = await resolver.wait()
            create_result = CreateTaskResult.model_validate(response_data)
            client_task_id = create_result.task.taskId

            # Poll the client's task using session.experimental
            async for _ in self._session.experimental.poll_task(client_task_id):
                pass

            # Get final result from client
            result = await self._session.experimental.get_task_result(
                client_task_id,
                CreateMessageResult,
            )

            await self._store.update_task(self.task_id, status=TASK_STATUS_WORKING)
            return result

        except anyio.get_cancelled_exc_class():  # pragma: no cover
            await self._store.update_task(self.task_id, status=TASK_STATUS_WORKING)
            raise
