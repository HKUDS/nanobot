import logging
from datetime import timedelta
from typing import Any, Protocol, overload

import anyio.lowlevel
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from pydantic import AnyUrl, TypeAdapter
from typing_extensions import deprecated

import mcp.types as types
from mcp.client.experimental import ExperimentalClientFeatures
from mcp.client.experimental.task_handlers import ExperimentalTaskHandlers
from mcp.shared.context import RequestContext
from mcp.shared.message import SessionMessage
from mcp.shared.session import BaseSession, ProgressFnT, RequestResponder
from mcp.shared.version import SUPPORTED_PROTOCOL_VERSIONS

DEFAULT_CLIENT_INFO = types.Implementation(name="mcp", version="0.1.0")

logger = logging.getLogger("client")


class SamplingFnT(Protocol):
    async def __call__(
        self,
        context: RequestContext["ClientSession", Any],
        params: types.CreateMessageRequestParams,
    ) -> types.CreateMessageResult | types.CreateMessageResultWithTools | types.ErrorData: ...  # pragma: no branch


class ElicitationFnT(Protocol):
    async def __call__(
        self,
        context: RequestContext["ClientSession", Any],
        params: types.ElicitRequestParams,
    ) -> types.ElicitResult | types.ErrorData: ...  # pragma: no branch


class ListRootsFnT(Protocol):
    async def __call__(
        self, context: RequestContext["ClientSession", Any]
    ) -> types.ListRootsResult | types.ErrorData: ...  # pragma: no branch


class LoggingFnT(Protocol):
    async def __call__(
        self,
        params: types.LoggingMessageNotificationParams,
    ) -> None: ...  # pragma: no branch


class MessageHandlerFnT(Protocol):
    async def __call__(
        self,
        message: RequestResponder[types.ServerRequest, types.ClientResult] | types.ServerNotification | Exception,
    ) -> None: ...  # pragma: no branch


async def _default_message_handler(
    message: RequestResponder[types.ServerRequest, types.ClientResult] | types.ServerNotification | Exception,
) -> None:
    await anyio.lowlevel.checkpoint()


async def _default_sampling_callback(
    context: RequestContext["ClientSession", Any],
    params: types.CreateMessageRequestParams,
) -> types.CreateMessageResult | types.CreateMessageResultWithTools | types.ErrorData:
    return types.ErrorData(
        code=types.INVALID_REQUEST,
        message="Sampling not supported",
    )


async def _default_elicitation_callback(
    context: RequestContext["ClientSession", Any],
    params: types.ElicitRequestParams,
) -> types.ElicitResult | types.ErrorData:
    return types.ErrorData(  # pragma: no cover
        code=types.INVALID_REQUEST,
        message="Elicitation not supported",
    )


async def _default_list_roots_callback(
    context: RequestContext["ClientSession", Any],
) -> types.ListRootsResult | types.ErrorData:
    return types.ErrorData(
        code=types.INVALID_REQUEST,
        message="List roots not supported",
    )


async def _default_logging_callback(
    params: types.LoggingMessageNotificationParams,
) -> None:
    pass


ClientResponse: TypeAdapter[types.ClientResult | types.ErrorData] = TypeAdapter(types.ClientResult | types.ErrorData)


class ClientSession(
    BaseSession[
        types.ClientRequest,
        types.ClientNotification,
        types.ClientResult,
        types.ServerRequest,
        types.ServerNotification,
    ]
):
    def __init__(
        self,
        read_stream: MemoryObjectReceiveStream[SessionMessage | Exception],
        write_stream: MemoryObjectSendStream[SessionMessage],
        read_timeout_seconds: timedelta | None = None,
        sampling_callback: SamplingFnT | None = None,
        elicitation_callback: ElicitationFnT | None = None,
        list_roots_callback: ListRootsFnT | None = None,
        logging_callback: LoggingFnT | None = None,
        message_handler: MessageHandlerFnT | None = None,
        client_info: types.Implementation | None = None,
        *,
        sampling_capabilities: types.SamplingCapability | None = None,
        experimental_task_handlers: ExperimentalTaskHandlers | None = None,
    ) -> None:
        super().__init__(
            read_stream,
            write_stream,
            types.ServerRequest,
            types.ServerNotification,
            read_timeout_seconds=read_timeout_seconds,
        )
        self._client_info = client_info or DEFAULT_CLIENT_INFO
        self._sampling_callback = sampling_callback or _default_sampling_callback
        self._sampling_capabilities = sampling_capabilities
        self._elicitation_callback = elicitation_callback or _default_elicitation_callback
        self._list_roots_callback = list_roots_callback or _default_list_roots_callback
        self._logging_callback = logging_callback or _default_logging_callback
        self._message_handler = message_handler or _default_message_handler
        self._tool_output_schemas: dict[str, dict[str, Any] | None] = {}
        self._server_capabilities: types.ServerCapabilities | None = None
        self._experimental_features: ExperimentalClientFeatures | None = None

        # Experimental: Task handlers (use defaults if not provided)
        self._task_handlers = experimental_task_handlers or ExperimentalTaskHandlers()

    async def initialize(self) -> types.InitializeResult:
        sampling = (
            (self._sampling_capabilities or types.SamplingCapability())
            if self._sampling_callback is not _default_sampling_callback
            else None
        )
        elicitation = (
            types.ElicitationCapability(
                form=types.FormElicitationCapability(),
                url=types.UrlElicitationCapability(),
            )
            if self._elicitation_callback is not _default_elicitation_callback
            else None
        )
        roots = (
            # TODO: Should this be based on whether we
            # _will_ send notifications, or only whether
            # they're supported?
            types.RootsCapability(listChanged=True)
            if self._list_roots_callback is not _default_list_roots_callback
            else None
        )

        result = await self.send_request(
            types.ClientRequest(
                types.InitializeRequest(
                    params=types.InitializeRequestParams(
                        protocolVersion=types.LATEST_PROTOCOL_VERSION,
                        capabilities=types.ClientCapabilities(
                            sampling=sampling,
                            elicitation=elicitation,
                            experimental=None,
                            roots=roots,
                            tasks=self._task_handlers.build_capability(),
                        ),
                        clientInfo=self._client_info,
                    ),
                )
            ),
            types.InitializeResult,
        )

        if result.protocolVersion not in SUPPORTED_PROTOCOL_VERSIONS:
            raise RuntimeError(f"Unsupported protocol version from the server: {result.protocolVersion}")

        self._server_capabilities = result.capabilities

        await self.send_notification(types.ClientNotification(types.InitializedNotification()))

        return result

    def get_server_capabilities(self) -> types.ServerCapabilities | None:
        """Return the server capabilities received during initialization.

        Returns None if the session has not been initialized yet.
        """
        return self._server_capabilities

    @property
    def experimental(self) -> ExperimentalClientFeatures:
        """Experimental APIs for tasks and other features.

        WARNING: These APIs are experimental and may change without notice.

        Example:
            status = await session.experimental.get_task(task_id)
            result = await session.experimental.get_task_result(task_id, CallToolResult)
        """
        if self._experimental_features is None:
            self._experimental_features = ExperimentalClientFeatures(self)
        return self._experimental_features

    async def send_ping(self) -> types.EmptyResult:
        """Send a ping request."""
        return await self.send_request(
            types.ClientRequest(types.PingRequest()),
            types.EmptyResult,
        )

    async def send_progress_notification(
        self,
        progress_token: str | int,
        progress: float,
        total: float | None = None,
        message: str | None = None,
    ) -> None:
        """Send a progress notification."""
        await self.send_notification(
            types.ClientNotification(
                types.ProgressNotification(
                    params=types.ProgressNotificationParams(
                        progressToken=progress_token,
                        progress=progress,
                        total=total,
                        message=message,
                    ),
                ),
            )
        )

    async def set_logging_level(self, level: types.LoggingLevel) -> types.EmptyResult:
        """Send a logging/setLevel request."""
        return await self.send_request(  # pragma: no cover
            types.ClientRequest(
                types.SetLevelRequest(
                    params=types.SetLevelRequestParams(level=level),
                )
            ),
            types.EmptyResult,
        )

    @overload
    @deprecated("Use list_resources(params=PaginatedRequestParams(...)) instead")
    async def list_resources(self, cursor: str | None) -> types.ListResourcesResult: ...

    @overload
    async def list_resources(self, *, params: types.PaginatedRequestParams | None) -> types.ListResourcesResult: ...

    @overload
    async def list_resources(self) -> types.ListResourcesResult: ...

    async def list_resources(
        self,
        cursor: str | None = None,
        *,
        params: types.PaginatedRequestParams | None = None,
    ) -> types.ListResourcesResult:
        """Send a resources/list request.

        Args:
            cursor: Simple cursor string for pagination (deprecated, use params instead)
            params: Full pagination parameters including cursor and any future fields
        """
        if params is not None and cursor is not None:
            raise ValueError("Cannot specify both cursor and params")

        if params is not None:
            request_params = params
        elif cursor is not None:
            request_params = types.PaginatedRequestParams(cursor=cursor)
        else:
            request_params = None

        return await self.send_request(
            types.ClientRequest(types.ListResourcesRequest(params=request_params)),
            types.ListResourcesResult,
        )

    @overload
    @deprecated("Use list_resource_templates(params=PaginatedRequestParams(...)) instead")
    async def list_resource_templates(self, cursor: str | None) -> types.ListResourceTemplatesResult: ...

    @overload
    async def list_resource_templates(
        self, *, params: types.PaginatedRequestParams | None
    ) -> types.ListResourceTemplatesResult: ...

    @overload
    async def list_resource_templates(self) -> types.ListResourceTemplatesResult: ...

    async def list_resource_templates(
        self,
        cursor: str | None = None,
        *,
        params: types.PaginatedRequestParams | None = None,
    ) -> types.ListResourceTemplatesResult:
        """Send a resources/templates/list request.

        Args:
            cursor: Simple cursor string for pagination (deprecated, use params instead)
            params: Full pagination parameters including cursor and any future fields
        """
        if params is not None and cursor is not None:
            raise ValueError("Cannot specify both cursor and params")

        if params is not None:
            request_params = params
        elif cursor is not None:
            request_params = types.PaginatedRequestParams(cursor=cursor)
        else:
            request_params = None

        return await self.send_request(
            types.ClientRequest(types.ListResourceTemplatesRequest(params=request_params)),
            types.ListResourceTemplatesResult,
        )

    async def read_resource(self, uri: AnyUrl) -> types.ReadResourceResult:
        """Send a resources/read request."""
        return await self.send_request(
            types.ClientRequest(
                types.ReadResourceRequest(
                    params=types.ReadResourceRequestParams(uri=uri),
                )
            ),
            types.ReadResourceResult,
        )

    async def subscribe_resource(self, uri: AnyUrl) -> types.EmptyResult:
        """Send a resources/subscribe request."""
        return await self.send_request(  # pragma: no cover
            types.ClientRequest(
                types.SubscribeRequest(
                    params=types.SubscribeRequestParams(uri=uri),
                )
            ),
            types.EmptyResult,
        )

    async def unsubscribe_resource(self, uri: AnyUrl) -> types.EmptyResult:
        """Send a resources/unsubscribe request."""
        return await self.send_request(  # pragma: no cover
            types.ClientRequest(
                types.UnsubscribeRequest(
                    params=types.UnsubscribeRequestParams(uri=uri),
                )
            ),
            types.EmptyResult,
        )

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
        read_timeout_seconds: timedelta | None = None,
        progress_callback: ProgressFnT | None = None,
        *,
        meta: dict[str, Any] | None = None,
    ) -> types.CallToolResult:
        """Send a tools/call request with optional progress callback support."""

        _meta: types.RequestParams.Meta | None = None
        if meta is not None:
            _meta = types.RequestParams.Meta(**meta)

        result = await self.send_request(
            types.ClientRequest(
                types.CallToolRequest(
                    params=types.CallToolRequestParams(name=name, arguments=arguments, _meta=_meta),
                )
            ),
            types.CallToolResult,
            request_read_timeout_seconds=read_timeout_seconds,
            progress_callback=progress_callback,
        )

        if not result.isError:
            await self._validate_tool_result(name, result)

        return result

    async def _validate_tool_result(self, name: str, result: types.CallToolResult) -> None:
        """Validate the structured content of a tool result against its output schema."""
        if name not in self._tool_output_schemas:
            # refresh output schema cache
            await self.list_tools()

        output_schema = None
        if name in self._tool_output_schemas:
            output_schema = self._tool_output_schemas.get(name)
        else:
            logger.warning(f"Tool {name} not listed by server, cannot validate any structured content")

        if output_schema is not None:
            from jsonschema import SchemaError, ValidationError, validate

            if result.structuredContent is None:
                raise RuntimeError(
                    f"Tool {name} has an output schema but did not return structured content"
                )  # pragma: no cover
            try:
                validate(result.structuredContent, output_schema)
            except ValidationError as e:
                raise RuntimeError(f"Invalid structured content returned by tool {name}: {e}")  # pragma: no cover
            except SchemaError as e:  # pragma: no cover
                raise RuntimeError(f"Invalid schema for tool {name}: {e}")  # pragma: no cover

    @overload
    @deprecated("Use list_prompts(params=PaginatedRequestParams(...)) instead")
    async def list_prompts(self, cursor: str | None) -> types.ListPromptsResult: ...

    @overload
    async def list_prompts(self, *, params: types.PaginatedRequestParams | None) -> types.ListPromptsResult: ...

    @overload
    async def list_prompts(self) -> types.ListPromptsResult: ...

    async def list_prompts(
        self,
        cursor: str | None = None,
        *,
        params: types.PaginatedRequestParams | None = None,
    ) -> types.ListPromptsResult:
        """Send a prompts/list request.

        Args:
            cursor: Simple cursor string for pagination (deprecated, use params instead)
            params: Full pagination parameters including cursor and any future fields
        """
        if params is not None and cursor is not None:
            raise ValueError("Cannot specify both cursor and params")

        if params is not None:
            request_params = params
        elif cursor is not None:
            request_params = types.PaginatedRequestParams(cursor=cursor)
        else:
            request_params = None

        return await self.send_request(
            types.ClientRequest(types.ListPromptsRequest(params=request_params)),
            types.ListPromptsResult,
        )

    async def get_prompt(self, name: str, arguments: dict[str, str] | None = None) -> types.GetPromptResult:
        """Send a prompts/get request."""
        return await self.send_request(
            types.ClientRequest(
                types.GetPromptRequest(
                    params=types.GetPromptRequestParams(name=name, arguments=arguments),
                )
            ),
            types.GetPromptResult,
        )

    async def complete(
        self,
        ref: types.ResourceTemplateReference | types.PromptReference,
        argument: dict[str, str],
        context_arguments: dict[str, str] | None = None,
    ) -> types.CompleteResult:
        """Send a completion/complete request."""
        context = None
        if context_arguments is not None:
            context = types.CompletionContext(arguments=context_arguments)

        return await self.send_request(
            types.ClientRequest(
                types.CompleteRequest(
                    params=types.CompleteRequestParams(
                        ref=ref,
                        argument=types.CompletionArgument(**argument),
                        context=context,
                    ),
                )
            ),
            types.CompleteResult,
        )

    @overload
    @deprecated("Use list_tools(params=PaginatedRequestParams(...)) instead")
    async def list_tools(self, cursor: str | None) -> types.ListToolsResult: ...

    @overload
    async def list_tools(self, *, params: types.PaginatedRequestParams | None) -> types.ListToolsResult: ...

    @overload
    async def list_tools(self) -> types.ListToolsResult: ...

    async def list_tools(
        self,
        cursor: str | None = None,
        *,
        params: types.PaginatedRequestParams | None = None,
    ) -> types.ListToolsResult:
        """Send a tools/list request.

        Args:
            cursor: Simple cursor string for pagination (deprecated, use params instead)
            params: Full pagination parameters including cursor and any future fields
        """
        if params is not None and cursor is not None:
            raise ValueError("Cannot specify both cursor and params")

        if params is not None:
            request_params = params
        elif cursor is not None:
            request_params = types.PaginatedRequestParams(cursor=cursor)
        else:
            request_params = None

        result = await self.send_request(
            types.ClientRequest(types.ListToolsRequest(params=request_params)),
            types.ListToolsResult,
        )

        # Cache tool output schemas for future validation
        # Note: don't clear the cache, as we may be using a cursor
        for tool in result.tools:
            self._tool_output_schemas[tool.name] = tool.outputSchema

        return result

    async def send_roots_list_changed(self) -> None:  # pragma: no cover
        """Send a roots/list_changed notification."""
        await self.send_notification(types.ClientNotification(types.RootsListChangedNotification()))

    async def _received_request(self, responder: RequestResponder[types.ServerRequest, types.ClientResult]) -> None:
        ctx = RequestContext[ClientSession, Any](
            request_id=responder.request_id,
            meta=responder.request_meta,
            session=self,
            lifespan_context=None,
        )

        # Delegate to experimental task handler if applicable
        if self._task_handlers.handles_request(responder.request):
            with responder:
                await self._task_handlers.handle_request(ctx, responder)
            return None

        # Core request handling
        match responder.request.root:
            case types.CreateMessageRequest(params=params):
                with responder:
                    # Check if this is a task-augmented request
                    if params.task is not None:
                        response = await self._task_handlers.augmented_sampling(ctx, params, params.task)
                    else:
                        response = await self._sampling_callback(ctx, params)
                    client_response = ClientResponse.validate_python(response)
                    await responder.respond(client_response)

            case types.ElicitRequest(params=params):
                with responder:
                    # Check if this is a task-augmented request
                    if params.task is not None:
                        response = await self._task_handlers.augmented_elicitation(ctx, params, params.task)
                    else:
                        response = await self._elicitation_callback(ctx, params)
                    client_response = ClientResponse.validate_python(response)
                    await responder.respond(client_response)

            case types.ListRootsRequest():
                with responder:
                    response = await self._list_roots_callback(ctx)
                    client_response = ClientResponse.validate_python(response)
                    await responder.respond(client_response)

            case types.PingRequest():  # pragma: no cover
                with responder:
                    return await responder.respond(types.ClientResult(root=types.EmptyResult()))

            case _:  # pragma: no cover
                pass  # Task requests handled above by _task_handlers

        return None

    async def _handle_incoming(
        self,
        req: RequestResponder[types.ServerRequest, types.ClientResult] | types.ServerNotification | Exception,
    ) -> None:
        """Handle incoming messages by forwarding to the message handler."""
        await self._message_handler(req)

    async def _received_notification(self, notification: types.ServerNotification) -> None:
        """Handle notifications from the server."""
        # Process specific notification types
        match notification.root:
            case types.LoggingMessageNotification(params=params):
                await self._logging_callback(params)
            case types.ElicitCompleteNotification(params=params):
                # Handle elicitation completion notification
                # Clients MAY use this to retry requests or update UI
                # The notification contains the elicitationId of the completed elicitation
                pass
            case _:
                pass
