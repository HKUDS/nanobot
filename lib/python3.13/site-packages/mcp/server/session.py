"""
ServerSession Module

This module provides the ServerSession class, which manages communication between the
server and client in the MCP (Model Context Protocol) framework. It is most commonly
used in MCP servers to interact with the client.

Common usage pattern:
```
    server = Server(name)

    @server.call_tool()
    async def handle_tool_call(ctx: RequestContext, arguments: dict[str, Any]) -> Any:
        # Check client capabilities before proceeding
        if ctx.session.check_client_capability(
            types.ClientCapabilities(experimental={"advanced_tools": dict()})
        ):
            # Perform advanced tool operations
            result = await perform_advanced_tool_operation(arguments)
        else:
            # Fall back to basic tool operations
            result = await perform_basic_tool_operation(arguments)

        return result

    @server.list_prompts()
    async def handle_list_prompts(ctx: RequestContext) -> list[types.Prompt]:
        # Access session for any necessary checks or operations
        if ctx.session.client_params:
            # Customize prompts based on client initialization parameters
            return generate_custom_prompts(ctx.session.client_params)
        else:
            return default_prompts
```

The ServerSession class is typically used internally by the Server class and should not
be instantiated directly by users of the MCP framework.
"""

from enum import Enum
from typing import Any, TypeVar, overload

import anyio
import anyio.lowlevel
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from pydantic import AnyUrl

import mcp.types as types
from mcp.server.experimental.session_features import ExperimentalServerSessionFeatures
from mcp.server.models import InitializationOptions
from mcp.server.validation import validate_sampling_tools, validate_tool_use_result_messages
from mcp.shared.experimental.tasks.capabilities import check_tasks_capability
from mcp.shared.experimental.tasks.helpers import RELATED_TASK_METADATA_KEY
from mcp.shared.message import ServerMessageMetadata, SessionMessage
from mcp.shared.session import (
    BaseSession,
    RequestResponder,
)
from mcp.shared.version import SUPPORTED_PROTOCOL_VERSIONS


class InitializationState(Enum):
    NotInitialized = 1
    Initializing = 2
    Initialized = 3


ServerSessionT = TypeVar("ServerSessionT", bound="ServerSession")

ServerRequestResponder = (
    RequestResponder[types.ClientRequest, types.ServerResult] | types.ClientNotification | Exception
)


class ServerSession(
    BaseSession[
        types.ServerRequest,
        types.ServerNotification,
        types.ServerResult,
        types.ClientRequest,
        types.ClientNotification,
    ]
):
    _initialized: InitializationState = InitializationState.NotInitialized
    _client_params: types.InitializeRequestParams | None = None
    _experimental_features: ExperimentalServerSessionFeatures | None = None

    def __init__(
        self,
        read_stream: MemoryObjectReceiveStream[SessionMessage | Exception],
        write_stream: MemoryObjectSendStream[SessionMessage],
        init_options: InitializationOptions,
        stateless: bool = False,
    ) -> None:
        super().__init__(read_stream, write_stream, types.ClientRequest, types.ClientNotification)
        self._initialization_state = (
            InitializationState.Initialized if stateless else InitializationState.NotInitialized
        )

        self._init_options = init_options
        self._incoming_message_stream_writer, self._incoming_message_stream_reader = anyio.create_memory_object_stream[
            ServerRequestResponder
        ](0)
        self._exit_stack.push_async_callback(lambda: self._incoming_message_stream_reader.aclose())

    @property
    def client_params(self) -> types.InitializeRequestParams | None:
        return self._client_params  # pragma: no cover

    @property
    def experimental(self) -> ExperimentalServerSessionFeatures:
        """Experimental APIs for server→client task operations.

        WARNING: These APIs are experimental and may change without notice.
        """
        if self._experimental_features is None:
            self._experimental_features = ExperimentalServerSessionFeatures(self)
        return self._experimental_features

    def check_client_capability(self, capability: types.ClientCapabilities) -> bool:  # pragma: no cover
        """Check if the client supports a specific capability."""
        if self._client_params is None:
            return False

        client_caps = self._client_params.capabilities

        if capability.roots is not None:
            if client_caps.roots is None:
                return False
            if capability.roots.listChanged and not client_caps.roots.listChanged:
                return False

        if capability.sampling is not None:
            if client_caps.sampling is None:
                return False
            if capability.sampling.context is not None and client_caps.sampling.context is None:
                return False
            if capability.sampling.tools is not None and client_caps.sampling.tools is None:
                return False

        if capability.elicitation is not None and client_caps.elicitation is None:
            return False

        if capability.experimental is not None:
            if client_caps.experimental is None:
                return False
            for exp_key, exp_value in capability.experimental.items():
                if exp_key not in client_caps.experimental or client_caps.experimental[exp_key] != exp_value:
                    return False

        if capability.tasks is not None:
            if client_caps.tasks is None:
                return False
            if not check_tasks_capability(capability.tasks, client_caps.tasks):
                return False

        return True

    async def _receive_loop(self) -> None:
        async with self._incoming_message_stream_writer:
            await super()._receive_loop()

    async def _received_request(self, responder: RequestResponder[types.ClientRequest, types.ServerResult]):
        match responder.request.root:
            case types.InitializeRequest(params=params):
                requested_version = params.protocolVersion
                self._initialization_state = InitializationState.Initializing
                self._client_params = params
                with responder:
                    await responder.respond(
                        types.ServerResult(
                            types.InitializeResult(
                                protocolVersion=requested_version
                                if requested_version in SUPPORTED_PROTOCOL_VERSIONS
                                else types.LATEST_PROTOCOL_VERSION,
                                capabilities=self._init_options.capabilities,
                                serverInfo=types.Implementation(
                                    name=self._init_options.server_name,
                                    version=self._init_options.server_version,
                                    websiteUrl=self._init_options.website_url,
                                    icons=self._init_options.icons,
                                ),
                                instructions=self._init_options.instructions,
                            )
                        )
                    )
                self._initialization_state = InitializationState.Initialized
            case types.PingRequest():
                # Ping requests are allowed at any time
                pass
            case _:
                if self._initialization_state != InitializationState.Initialized:
                    raise RuntimeError("Received request before initialization was complete")

    async def _received_notification(self, notification: types.ClientNotification) -> None:
        # Need this to avoid ASYNC910
        await anyio.lowlevel.checkpoint()
        match notification.root:
            case types.InitializedNotification():
                self._initialization_state = InitializationState.Initialized
            case _:
                if self._initialization_state != InitializationState.Initialized:  # pragma: no cover
                    raise RuntimeError("Received notification before initialization was complete")

    async def send_log_message(
        self,
        level: types.LoggingLevel,
        data: Any,
        logger: str | None = None,
        related_request_id: types.RequestId | None = None,
    ) -> None:
        """Send a log message notification."""
        await self.send_notification(
            types.ServerNotification(
                types.LoggingMessageNotification(
                    params=types.LoggingMessageNotificationParams(
                        level=level,
                        data=data,
                        logger=logger,
                    ),
                )
            ),
            related_request_id,
        )

    async def send_resource_updated(self, uri: AnyUrl) -> None:  # pragma: no cover
        """Send a resource updated notification."""
        await self.send_notification(
            types.ServerNotification(
                types.ResourceUpdatedNotification(
                    params=types.ResourceUpdatedNotificationParams(uri=uri),
                )
            )
        )

    @overload
    async def create_message(
        self,
        messages: list[types.SamplingMessage],
        *,
        max_tokens: int,
        system_prompt: str | None = None,
        include_context: types.IncludeContext | None = None,
        temperature: float | None = None,
        stop_sequences: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        model_preferences: types.ModelPreferences | None = None,
        tools: None = None,
        tool_choice: types.ToolChoice | None = None,
        related_request_id: types.RequestId | None = None,
    ) -> types.CreateMessageResult:
        """Overload: Without tools, returns single content."""
        ...

    @overload
    async def create_message(
        self,
        messages: list[types.SamplingMessage],
        *,
        max_tokens: int,
        system_prompt: str | None = None,
        include_context: types.IncludeContext | None = None,
        temperature: float | None = None,
        stop_sequences: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        model_preferences: types.ModelPreferences | None = None,
        tools: list[types.Tool],
        tool_choice: types.ToolChoice | None = None,
        related_request_id: types.RequestId | None = None,
    ) -> types.CreateMessageResultWithTools:
        """Overload: With tools, returns array-capable content."""
        ...

    async def create_message(
        self,
        messages: list[types.SamplingMessage],
        *,
        max_tokens: int,
        system_prompt: str | None = None,
        include_context: types.IncludeContext | None = None,
        temperature: float | None = None,
        stop_sequences: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        model_preferences: types.ModelPreferences | None = None,
        tools: list[types.Tool] | None = None,
        tool_choice: types.ToolChoice | None = None,
        related_request_id: types.RequestId | None = None,
    ) -> types.CreateMessageResult | types.CreateMessageResultWithTools:
        """Send a sampling/create_message request.

        Args:
            messages: The conversation messages to send.
            max_tokens: Maximum number of tokens to generate.
            system_prompt: Optional system prompt.
            include_context: Optional context inclusion setting.
                Should only be set to "thisServer" or "allServers"
                if the client has sampling.context capability.
            temperature: Optional sampling temperature.
            stop_sequences: Optional stop sequences.
            metadata: Optional metadata to pass through to the LLM provider.
            model_preferences: Optional model selection preferences.
            tools: Optional list of tools the LLM can use during sampling.
                Requires client to have sampling.tools capability.
            tool_choice: Optional control over tool usage behavior.
                Requires client to have sampling.tools capability.
            related_request_id: Optional ID of a related request.

        Returns:
            The sampling result from the client.

        Raises:
            McpError: If tools are provided but client doesn't support them.
            ValueError: If tool_use or tool_result message structure is invalid.
        """
        client_caps = self._client_params.capabilities if self._client_params else None
        validate_sampling_tools(client_caps, tools, tool_choice)
        validate_tool_use_result_messages(messages)

        request = types.ServerRequest(
            types.CreateMessageRequest(
                params=types.CreateMessageRequestParams(
                    messages=messages,
                    systemPrompt=system_prompt,
                    includeContext=include_context,
                    temperature=temperature,
                    maxTokens=max_tokens,
                    stopSequences=stop_sequences,
                    metadata=metadata,
                    modelPreferences=model_preferences,
                    tools=tools,
                    toolChoice=tool_choice,
                ),
            )
        )
        metadata_obj = ServerMessageMetadata(related_request_id=related_request_id)

        # Use different result types based on whether tools are provided
        if tools is not None:
            return await self.send_request(
                request=request,
                result_type=types.CreateMessageResultWithTools,
                metadata=metadata_obj,
            )
        return await self.send_request(
            request=request,
            result_type=types.CreateMessageResult,
            metadata=metadata_obj,
        )

    async def list_roots(self) -> types.ListRootsResult:
        """Send a roots/list request."""
        return await self.send_request(
            types.ServerRequest(types.ListRootsRequest()),
            types.ListRootsResult,
        )

    async def elicit(
        self,
        message: str,
        requestedSchema: types.ElicitRequestedSchema,
        related_request_id: types.RequestId | None = None,
    ) -> types.ElicitResult:
        """Send a form mode elicitation/create request.

        Args:
            message: The message to present to the user
            requestedSchema: Schema defining the expected response structure
            related_request_id: Optional ID of the request that triggered this elicitation

        Returns:
            The client's response

        Note:
            This method is deprecated in favor of elicit_form(). It remains for
            backward compatibility but new code should use elicit_form().
        """
        return await self.elicit_form(message, requestedSchema, related_request_id)

    async def elicit_form(
        self,
        message: str,
        requestedSchema: types.ElicitRequestedSchema,
        related_request_id: types.RequestId | None = None,
    ) -> types.ElicitResult:
        """Send a form mode elicitation/create request.

        Args:
            message: The message to present to the user
            requestedSchema: Schema defining the expected response structure
            related_request_id: Optional ID of the request that triggered this elicitation

        Returns:
            The client's response with form data
        """
        return await self.send_request(
            types.ServerRequest(
                types.ElicitRequest(
                    params=types.ElicitRequestFormParams(
                        message=message,
                        requestedSchema=requestedSchema,
                    ),
                )
            ),
            types.ElicitResult,
            metadata=ServerMessageMetadata(related_request_id=related_request_id),
        )

    async def elicit_url(
        self,
        message: str,
        url: str,
        elicitation_id: str,
        related_request_id: types.RequestId | None = None,
    ) -> types.ElicitResult:
        """Send a URL mode elicitation/create request.

        This directs the user to an external URL for out-of-band interactions
        like OAuth flows, credential collection, or payment processing.

        Args:
            message: Human-readable explanation of why the interaction is needed
            url: The URL the user should navigate to
            elicitation_id: Unique identifier for tracking this elicitation
            related_request_id: Optional ID of the request that triggered this elicitation

        Returns:
            The client's response indicating acceptance, decline, or cancellation
        """
        return await self.send_request(
            types.ServerRequest(
                types.ElicitRequest(
                    params=types.ElicitRequestURLParams(
                        message=message,
                        url=url,
                        elicitationId=elicitation_id,
                    ),
                )
            ),
            types.ElicitResult,
            metadata=ServerMessageMetadata(related_request_id=related_request_id),
        )

    async def send_ping(self) -> types.EmptyResult:  # pragma: no cover
        """Send a ping request."""
        return await self.send_request(
            types.ServerRequest(types.PingRequest()),
            types.EmptyResult,
        )

    async def send_progress_notification(
        self,
        progress_token: str | int,
        progress: float,
        total: float | None = None,
        message: str | None = None,
        related_request_id: str | None = None,
    ) -> None:
        """Send a progress notification."""
        await self.send_notification(
            types.ServerNotification(
                types.ProgressNotification(
                    params=types.ProgressNotificationParams(
                        progressToken=progress_token,
                        progress=progress,
                        total=total,
                        message=message,
                    ),
                )
            ),
            related_request_id,
        )

    async def send_resource_list_changed(self) -> None:  # pragma: no cover
        """Send a resource list changed notification."""
        await self.send_notification(types.ServerNotification(types.ResourceListChangedNotification()))

    async def send_tool_list_changed(self) -> None:  # pragma: no cover
        """Send a tool list changed notification."""
        await self.send_notification(types.ServerNotification(types.ToolListChangedNotification()))

    async def send_prompt_list_changed(self) -> None:  # pragma: no cover
        """Send a prompt list changed notification."""
        await self.send_notification(types.ServerNotification(types.PromptListChangedNotification()))

    async def send_elicit_complete(
        self,
        elicitation_id: str,
        related_request_id: types.RequestId | None = None,
    ) -> None:
        """Send an elicitation completion notification.

        This should be sent when a URL mode elicitation has been completed
        out-of-band to inform the client that it may retry any requests
        that were waiting for this elicitation.

        Args:
            elicitation_id: The unique identifier of the completed elicitation
            related_request_id: Optional ID of the request that triggered this
        """
        await self.send_notification(
            types.ServerNotification(
                types.ElicitCompleteNotification(
                    params=types.ElicitCompleteNotificationParams(elicitationId=elicitation_id)
                )
            ),
            related_request_id,
        )

    def _build_elicit_form_request(
        self,
        message: str,
        requestedSchema: types.ElicitRequestedSchema,
        related_task_id: str | None = None,
        task: types.TaskMetadata | None = None,
    ) -> types.JSONRPCRequest:
        """Build a form mode elicitation request without sending it.

        Args:
            message: The message to present to the user
            requestedSchema: Schema defining the expected response structure
            related_task_id: If provided, adds io.modelcontextprotocol/related-task metadata
            task: If provided, makes this a task-augmented request

        Returns:
            A JSONRPCRequest ready to be sent or queued
        """
        params = types.ElicitRequestFormParams(
            message=message,
            requestedSchema=requestedSchema,
            task=task,
        )
        params_data = params.model_dump(by_alias=True, mode="json", exclude_none=True)

        # Add related-task metadata if associated with a parent task
        if related_task_id is not None:
            # Defensive: model_dump() never includes _meta, but guard against future changes
            if "_meta" not in params_data:  # pragma: no cover
                params_data["_meta"] = {}
            params_data["_meta"][RELATED_TASK_METADATA_KEY] = types.RelatedTaskMetadata(
                taskId=related_task_id
            ).model_dump(by_alias=True)

        request_id = f"task-{related_task_id}-{id(params)}" if related_task_id else self._request_id
        if related_task_id is None:
            self._request_id += 1

        return types.JSONRPCRequest(
            jsonrpc="2.0",
            id=request_id,
            method="elicitation/create",
            params=params_data,
        )

    def _build_elicit_url_request(
        self,
        message: str,
        url: str,
        elicitation_id: str,
        related_task_id: str | None = None,
    ) -> types.JSONRPCRequest:
        """Build a URL mode elicitation request without sending it.

        Args:
            message: Human-readable explanation of why the interaction is needed
            url: The URL the user should navigate to
            elicitation_id: Unique identifier for tracking this elicitation
            related_task_id: If provided, adds io.modelcontextprotocol/related-task metadata

        Returns:
            A JSONRPCRequest ready to be sent or queued
        """
        params = types.ElicitRequestURLParams(
            message=message,
            url=url,
            elicitationId=elicitation_id,
        )
        params_data = params.model_dump(by_alias=True, mode="json", exclude_none=True)

        # Add related-task metadata if associated with a parent task
        if related_task_id is not None:
            # Defensive: model_dump() never includes _meta, but guard against future changes
            if "_meta" not in params_data:  # pragma: no cover
                params_data["_meta"] = {}
            params_data["_meta"][RELATED_TASK_METADATA_KEY] = types.RelatedTaskMetadata(
                taskId=related_task_id
            ).model_dump(by_alias=True)

        request_id = f"task-{related_task_id}-{id(params)}" if related_task_id else self._request_id
        if related_task_id is None:
            self._request_id += 1

        return types.JSONRPCRequest(
            jsonrpc="2.0",
            id=request_id,
            method="elicitation/create",
            params=params_data,
        )

    def _build_create_message_request(
        self,
        messages: list[types.SamplingMessage],
        *,
        max_tokens: int,
        system_prompt: str | None = None,
        include_context: types.IncludeContext | None = None,
        temperature: float | None = None,
        stop_sequences: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        model_preferences: types.ModelPreferences | None = None,
        tools: list[types.Tool] | None = None,
        tool_choice: types.ToolChoice | None = None,
        related_task_id: str | None = None,
        task: types.TaskMetadata | None = None,
    ) -> types.JSONRPCRequest:
        """Build a sampling/createMessage request without sending it.

        Args:
            messages: The conversation messages to send
            max_tokens: Maximum number of tokens to generate
            system_prompt: Optional system prompt
            include_context: Optional context inclusion setting
            temperature: Optional sampling temperature
            stop_sequences: Optional stop sequences
            metadata: Optional metadata to pass through to the LLM provider
            model_preferences: Optional model selection preferences
            tools: Optional list of tools the LLM can use during sampling
            tool_choice: Optional control over tool usage behavior
            related_task_id: If provided, adds io.modelcontextprotocol/related-task metadata
            task: If provided, makes this a task-augmented request

        Returns:
            A JSONRPCRequest ready to be sent or queued
        """
        params = types.CreateMessageRequestParams(
            messages=messages,
            systemPrompt=system_prompt,
            includeContext=include_context,
            temperature=temperature,
            maxTokens=max_tokens,
            stopSequences=stop_sequences,
            metadata=metadata,
            modelPreferences=model_preferences,
            tools=tools,
            toolChoice=tool_choice,
            task=task,
        )
        params_data = params.model_dump(by_alias=True, mode="json", exclude_none=True)

        # Add related-task metadata if associated with a parent task
        if related_task_id is not None:
            # Defensive: model_dump() never includes _meta, but guard against future changes
            if "_meta" not in params_data:  # pragma: no cover
                params_data["_meta"] = {}
            params_data["_meta"][RELATED_TASK_METADATA_KEY] = types.RelatedTaskMetadata(
                taskId=related_task_id
            ).model_dump(by_alias=True)

        request_id = f"task-{related_task_id}-{id(params)}" if related_task_id else self._request_id
        if related_task_id is None:
            self._request_id += 1

        return types.JSONRPCRequest(
            jsonrpc="2.0",
            id=request_id,
            method="sampling/createMessage",
            params=params_data,
        )

    async def send_message(self, message: SessionMessage) -> None:
        """Send a raw session message.

        This is primarily used by TaskResultHandler to deliver queued messages
        (elicitation/sampling requests) to the client during task execution.

        WARNING: This is a low-level experimental method that may change without
        notice. Prefer using higher-level methods like send_notification() or
        send_request() for normal operations.

        Args:
            message: The session message to send
        """
        await self._write_stream.send(message)

    async def _handle_incoming(self, req: ServerRequestResponder) -> None:
        await self._incoming_message_stream_writer.send(req)

    @property
    def incoming_messages(
        self,
    ) -> MemoryObjectReceiveStream[ServerRequestResponder]:
        return self._incoming_message_stream_reader
