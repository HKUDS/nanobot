"""
StreamableHTTP Client Transport Module

This module implements the StreamableHTTP transport for MCP clients,
providing support for HTTP POST requests with optional SSE streaming responses
and session management.
"""

import contextlib
import logging
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, overload
from warnings import warn

import anyio
import httpx
from anyio.abc import TaskGroup
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from httpx_sse import EventSource, ServerSentEvent, aconnect_sse
from typing_extensions import deprecated

from mcp.shared._httpx_utils import (
    McpHttpClientFactory,
    create_mcp_http_client,
)
from mcp.shared.message import ClientMessageMetadata, SessionMessage
from mcp.types import (
    ErrorData,
    InitializeResult,
    JSONRPCError,
    JSONRPCMessage,
    JSONRPCNotification,
    JSONRPCRequest,
    JSONRPCResponse,
    RequestId,
)

logger = logging.getLogger(__name__)


SessionMessageOrError = SessionMessage | Exception
StreamWriter = MemoryObjectSendStream[SessionMessageOrError]
StreamReader = MemoryObjectReceiveStream[SessionMessage]
GetSessionIdCallback = Callable[[], str | None]

MCP_SESSION_ID = "mcp-session-id"
MCP_PROTOCOL_VERSION = "mcp-protocol-version"
LAST_EVENT_ID = "last-event-id"

# Reconnection defaults
DEFAULT_RECONNECTION_DELAY_MS = 1000  # 1 second fallback when server doesn't provide retry
MAX_RECONNECTION_ATTEMPTS = 2  # Max retry attempts before giving up
CONTENT_TYPE = "content-type"
ACCEPT = "accept"


JSON = "application/json"
SSE = "text/event-stream"

# Sentinel value for detecting unset optional parameters
_UNSET = object()


class StreamableHTTPError(Exception):
    """Base exception for StreamableHTTP transport errors."""


class ResumptionError(StreamableHTTPError):
    """Raised when resumption request is invalid."""


@dataclass
class RequestContext:
    """Context for a request operation."""

    client: httpx.AsyncClient
    session_id: str | None
    session_message: SessionMessage
    metadata: ClientMessageMetadata | None
    read_stream_writer: StreamWriter
    headers: dict[str, str] | None = None  # Deprecated - no longer used
    sse_read_timeout: float | None = None  # Deprecated - no longer used


class StreamableHTTPTransport:
    """StreamableHTTP client transport implementation."""

    @overload
    def __init__(self, url: str) -> None: ...

    @overload
    @deprecated(
        "Parameters headers, timeout, sse_read_timeout, and auth are deprecated. "
        "Configure these on the httpx.AsyncClient instead."
    )
    def __init__(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        timeout: float | timedelta = 30,
        sse_read_timeout: float | timedelta = 60 * 5,
        auth: httpx.Auth | None = None,
    ) -> None: ...

    def __init__(
        self,
        url: str,
        headers: Any = _UNSET,
        timeout: Any = _UNSET,
        sse_read_timeout: Any = _UNSET,
        auth: Any = _UNSET,
    ) -> None:
        """Initialize the StreamableHTTP transport.

        Args:
            url: The endpoint URL.
            headers: Optional headers to include in requests.
            timeout: HTTP timeout for regular operations.
            sse_read_timeout: Timeout for SSE read operations.
            auth: Optional HTTPX authentication handler.
        """
        # Check for deprecated parameters and issue runtime warning
        deprecated_params: list[str] = []
        if headers is not _UNSET:
            deprecated_params.append("headers")
        if timeout is not _UNSET:
            deprecated_params.append("timeout")
        if sse_read_timeout is not _UNSET:
            deprecated_params.append("sse_read_timeout")
        if auth is not _UNSET:
            deprecated_params.append("auth")

        if deprecated_params:
            warn(
                f"Parameters {', '.join(deprecated_params)} are deprecated and will be ignored. "
                "Configure these on the httpx.AsyncClient instead.",
                DeprecationWarning,
                stacklevel=2,
            )

        self.url = url
        self.session_id = None
        self.protocol_version = None

    def _prepare_headers(self) -> dict[str, str]:
        """Build MCP-specific request headers.

        These headers will be merged with the httpx.AsyncClient's default headers,
        with these MCP-specific headers taking precedence.
        """
        headers: dict[str, str] = {}
        # Add MCP protocol headers
        headers[ACCEPT] = f"{JSON}, {SSE}"
        headers[CONTENT_TYPE] = JSON
        # Add session headers if available
        if self.session_id:
            headers[MCP_SESSION_ID] = self.session_id
        if self.protocol_version:
            headers[MCP_PROTOCOL_VERSION] = self.protocol_version
        return headers

    def _is_initialization_request(self, message: JSONRPCMessage) -> bool:
        """Check if the message is an initialization request."""
        return isinstance(message.root, JSONRPCRequest) and message.root.method == "initialize"

    def _is_initialized_notification(self, message: JSONRPCMessage) -> bool:
        """Check if the message is an initialized notification."""
        return isinstance(message.root, JSONRPCNotification) and message.root.method == "notifications/initialized"

    def _maybe_extract_session_id_from_response(
        self,
        response: httpx.Response,
    ) -> None:
        """Extract and store session ID from response headers."""
        new_session_id = response.headers.get(MCP_SESSION_ID)
        if new_session_id:
            self.session_id = new_session_id
            logger.info(f"Received session ID: {self.session_id}")

    def _maybe_extract_protocol_version_from_message(
        self,
        message: JSONRPCMessage,
    ) -> None:
        """Extract protocol version from initialization response message."""
        if isinstance(message.root, JSONRPCResponse) and message.root.result:  # pragma: no branch
            try:
                # Parse the result as InitializeResult for type safety
                init_result = InitializeResult.model_validate(message.root.result)
                self.protocol_version = str(init_result.protocolVersion)
                logger.info(f"Negotiated protocol version: {self.protocol_version}")
            except Exception as exc:  # pragma: no cover
                logger.warning(
                    f"Failed to parse initialization response as InitializeResult: {exc}"
                )  # pragma: no cover
                logger.warning(f"Raw result: {message.root.result}")

    async def _handle_sse_event(
        self,
        sse: ServerSentEvent,
        read_stream_writer: StreamWriter,
        original_request_id: RequestId | None = None,
        resumption_callback: Callable[[str], Awaitable[None]] | None = None,
        is_initialization: bool = False,
    ) -> bool:
        """Handle an SSE event, returning True if the response is complete."""
        if sse.event == "message":
            # Handle priming events (empty data with ID) for resumability
            if not sse.data:
                # Call resumption callback for priming events that have an ID
                if sse.id and resumption_callback:
                    await resumption_callback(sse.id)
                return False
            try:
                message = JSONRPCMessage.model_validate_json(sse.data)
                logger.debug(f"SSE message: {message}")

                # Extract protocol version from initialization response
                if is_initialization:
                    self._maybe_extract_protocol_version_from_message(message)

                # If this is a response and we have original_request_id, replace it
                if original_request_id is not None and isinstance(message.root, JSONRPCResponse | JSONRPCError):
                    message.root.id = original_request_id

                session_message = SessionMessage(message)
                await read_stream_writer.send(session_message)

                # Call resumption token callback if we have an ID
                if sse.id and resumption_callback:
                    await resumption_callback(sse.id)

                # If this is a response or error return True indicating completion
                # Otherwise, return False to continue listening
                return isinstance(message.root, JSONRPCResponse | JSONRPCError)

            except Exception as exc:  # pragma: no cover
                logger.exception("Error parsing SSE message")
                await read_stream_writer.send(exc)
                return False
        else:  # pragma: no cover
            logger.warning(f"Unknown SSE event: {sse.event}")
            return False

    async def handle_get_stream(
        self,
        client: httpx.AsyncClient,
        read_stream_writer: StreamWriter,
    ) -> None:
        """Handle GET stream for server-initiated messages with auto-reconnect."""
        last_event_id: str | None = None
        retry_interval_ms: int | None = None
        attempt: int = 0

        while attempt < MAX_RECONNECTION_ATTEMPTS:  # pragma: no branch
            try:
                if not self.session_id:
                    return

                headers = self._prepare_headers()
                if last_event_id:
                    headers[LAST_EVENT_ID] = last_event_id  # pragma: no cover

                async with aconnect_sse(
                    client,
                    "GET",
                    self.url,
                    headers=headers,
                ) as event_source:
                    event_source.response.raise_for_status()
                    logger.debug("GET SSE connection established")

                    async for sse in event_source.aiter_sse():
                        # Track last event ID for reconnection
                        if sse.id:
                            last_event_id = sse.id  # pragma: no cover
                        # Track retry interval from server
                        if sse.retry is not None:
                            retry_interval_ms = sse.retry  # pragma: no cover

                        await self._handle_sse_event(sse, read_stream_writer)

                    # Stream ended normally (server closed) - reset attempt counter
                    attempt = 0

            except Exception as exc:  # pragma: no cover
                logger.debug(f"GET stream error: {exc}")
                attempt += 1

            if attempt >= MAX_RECONNECTION_ATTEMPTS:  # pragma: no cover
                logger.debug(f"GET stream max reconnection attempts ({MAX_RECONNECTION_ATTEMPTS}) exceeded")
                return

            # Wait before reconnecting
            delay_ms = retry_interval_ms if retry_interval_ms is not None else DEFAULT_RECONNECTION_DELAY_MS
            logger.info(f"GET stream disconnected, reconnecting in {delay_ms}ms...")
            await anyio.sleep(delay_ms / 1000.0)

    async def _handle_resumption_request(self, ctx: RequestContext) -> None:
        """Handle a resumption request using GET with SSE."""
        headers = self._prepare_headers()
        if ctx.metadata and ctx.metadata.resumption_token:
            headers[LAST_EVENT_ID] = ctx.metadata.resumption_token
        else:
            raise ResumptionError("Resumption request requires a resumption token")  # pragma: no cover

        # Extract original request ID to map responses
        original_request_id = None
        if isinstance(ctx.session_message.message.root, JSONRPCRequest):  # pragma: no branch
            original_request_id = ctx.session_message.message.root.id

        async with aconnect_sse(
            ctx.client,
            "GET",
            self.url,
            headers=headers,
        ) as event_source:
            event_source.response.raise_for_status()
            logger.debug("Resumption GET SSE connection established")

            async for sse in event_source.aiter_sse():  # pragma: no branch
                is_complete = await self._handle_sse_event(
                    sse,
                    ctx.read_stream_writer,
                    original_request_id,
                    ctx.metadata.on_resumption_token_update if ctx.metadata else None,
                )
                if is_complete:
                    await event_source.response.aclose()
                    break

    async def _handle_post_request(self, ctx: RequestContext) -> None:
        """Handle a POST request with response processing."""
        headers = self._prepare_headers()
        message = ctx.session_message.message
        is_initialization = self._is_initialization_request(message)

        async with ctx.client.stream(
            "POST",
            self.url,
            json=message.model_dump(by_alias=True, mode="json", exclude_none=True),
            headers=headers,
        ) as response:
            if response.status_code == 202:
                logger.debug("Received 202 Accepted")
                return

            if response.status_code == 404:  # pragma: no branch
                if isinstance(message.root, JSONRPCRequest):
                    await self._send_session_terminated_error(  # pragma: no cover
                        ctx.read_stream_writer,  # pragma: no cover
                        message.root.id,  # pragma: no cover
                    )  # pragma: no cover
                return  # pragma: no cover

            response.raise_for_status()
            if is_initialization:
                self._maybe_extract_session_id_from_response(response)

            # Per https://modelcontextprotocol.io/specification/2025-06-18/basic#notifications:
            # The server MUST NOT send a response to notifications.
            if isinstance(message.root, JSONRPCRequest):
                content_type = response.headers.get(CONTENT_TYPE, "").lower()
                if content_type.startswith(JSON):
                    await self._handle_json_response(response, ctx.read_stream_writer, is_initialization)
                elif content_type.startswith(SSE):
                    await self._handle_sse_response(response, ctx, is_initialization)
                else:
                    await self._handle_unexpected_content_type(  # pragma: no cover
                        content_type,  # pragma: no cover
                        ctx.read_stream_writer,  # pragma: no cover
                    )  # pragma: no cover

    async def _handle_json_response(
        self,
        response: httpx.Response,
        read_stream_writer: StreamWriter,
        is_initialization: bool = False,
    ) -> None:
        """Handle JSON response from the server."""
        try:
            content = await response.aread()
            message = JSONRPCMessage.model_validate_json(content)

            # Extract protocol version from initialization response
            if is_initialization:
                self._maybe_extract_protocol_version_from_message(message)

            session_message = SessionMessage(message)
            await read_stream_writer.send(session_message)
        except Exception as exc:  # pragma: no cover
            logger.exception("Error parsing JSON response")
            await read_stream_writer.send(exc)

    async def _handle_sse_response(
        self,
        response: httpx.Response,
        ctx: RequestContext,
        is_initialization: bool = False,
    ) -> None:
        """Handle SSE response from the server."""
        last_event_id: str | None = None
        retry_interval_ms: int | None = None

        try:
            event_source = EventSource(response)
            async for sse in event_source.aiter_sse():  # pragma: no branch
                # Track last event ID for potential reconnection
                if sse.id:
                    last_event_id = sse.id

                # Track retry interval from server
                if sse.retry is not None:
                    retry_interval_ms = sse.retry

                is_complete = await self._handle_sse_event(
                    sse,
                    ctx.read_stream_writer,
                    resumption_callback=(ctx.metadata.on_resumption_token_update if ctx.metadata else None),
                    is_initialization=is_initialization,
                )
                # If the SSE event indicates completion, like returning respose/error
                # break the loop
                if is_complete:
                    await response.aclose()
                    return  # Normal completion, no reconnect needed
        except Exception as e:  # pragma: no cover
            logger.debug(f"SSE stream ended: {e}")

        # Stream ended without response - reconnect if we received an event with ID
        if last_event_id is not None:  # pragma: no branch
            logger.info("SSE stream disconnected, reconnecting...")
            await self._handle_reconnection(ctx, last_event_id, retry_interval_ms)

    async def _handle_reconnection(
        self,
        ctx: RequestContext,
        last_event_id: str,
        retry_interval_ms: int | None = None,
        attempt: int = 0,
    ) -> None:
        """Reconnect with Last-Event-ID to resume stream after server disconnect."""
        # Bail if max retries exceeded
        if attempt >= MAX_RECONNECTION_ATTEMPTS:  # pragma: no cover
            logger.debug(f"Max reconnection attempts ({MAX_RECONNECTION_ATTEMPTS}) exceeded")
            return

        # Always wait - use server value or default
        delay_ms = retry_interval_ms if retry_interval_ms is not None else DEFAULT_RECONNECTION_DELAY_MS
        await anyio.sleep(delay_ms / 1000.0)

        headers = self._prepare_headers()
        headers[LAST_EVENT_ID] = last_event_id

        # Extract original request ID to map responses
        original_request_id = None
        if isinstance(ctx.session_message.message.root, JSONRPCRequest):  # pragma: no branch
            original_request_id = ctx.session_message.message.root.id

        try:
            async with aconnect_sse(
                ctx.client,
                "GET",
                self.url,
                headers=headers,
            ) as event_source:
                event_source.response.raise_for_status()
                logger.info("Reconnected to SSE stream")

                # Track for potential further reconnection
                reconnect_last_event_id: str = last_event_id
                reconnect_retry_ms = retry_interval_ms

                async for sse in event_source.aiter_sse():
                    if sse.id:  # pragma: no branch
                        reconnect_last_event_id = sse.id
                    if sse.retry is not None:
                        reconnect_retry_ms = sse.retry

                    is_complete = await self._handle_sse_event(
                        sse,
                        ctx.read_stream_writer,
                        original_request_id,
                        ctx.metadata.on_resumption_token_update if ctx.metadata else None,
                    )
                    if is_complete:
                        await event_source.response.aclose()
                        return

                # Stream ended again without response - reconnect again (reset attempt counter)
                logger.info("SSE stream disconnected, reconnecting...")
                await self._handle_reconnection(ctx, reconnect_last_event_id, reconnect_retry_ms, 0)
        except Exception as e:  # pragma: no cover
            logger.debug(f"Reconnection failed: {e}")
            # Try to reconnect again if we still have an event ID
            await self._handle_reconnection(ctx, last_event_id, retry_interval_ms, attempt + 1)

    async def _handle_unexpected_content_type(
        self,
        content_type: str,
        read_stream_writer: StreamWriter,
    ) -> None:  # pragma: no cover
        """Handle unexpected content type in response."""
        error_msg = f"Unexpected content type: {content_type}"  # pragma: no cover
        logger.error(error_msg)  # pragma: no cover
        await read_stream_writer.send(ValueError(error_msg))  # pragma: no cover

    async def _send_session_terminated_error(
        self,
        read_stream_writer: StreamWriter,
        request_id: RequestId,
    ) -> None:
        """Send a session terminated error response."""
        jsonrpc_error = JSONRPCError(
            jsonrpc="2.0",
            id=request_id,
            error=ErrorData(code=32600, message="Session terminated"),
        )
        session_message = SessionMessage(JSONRPCMessage(jsonrpc_error))
        await read_stream_writer.send(session_message)

    async def post_writer(
        self,
        client: httpx.AsyncClient,
        write_stream_reader: StreamReader,
        read_stream_writer: StreamWriter,
        write_stream: MemoryObjectSendStream[SessionMessage],
        start_get_stream: Callable[[], None],
        tg: TaskGroup,
    ) -> None:
        """Handle writing requests to the server."""
        try:
            async with write_stream_reader:
                async for session_message in write_stream_reader:
                    message = session_message.message
                    metadata = (
                        session_message.metadata
                        if isinstance(session_message.metadata, ClientMessageMetadata)
                        else None
                    )

                    # Check if this is a resumption request
                    is_resumption = bool(metadata and metadata.resumption_token)

                    logger.debug(f"Sending client message: {message}")

                    # Handle initialized notification
                    if self._is_initialized_notification(message):
                        start_get_stream()

                    ctx = RequestContext(
                        client=client,
                        session_id=self.session_id,
                        session_message=session_message,
                        metadata=metadata,
                        read_stream_writer=read_stream_writer,
                    )

                    async def handle_request_async():
                        if is_resumption:
                            await self._handle_resumption_request(ctx)
                        else:
                            await self._handle_post_request(ctx)

                    # If this is a request, start a new task to handle it
                    if isinstance(message.root, JSONRPCRequest):
                        tg.start_soon(handle_request_async)
                    else:
                        await handle_request_async()

        except Exception:
            logger.exception("Error in post_writer")  # pragma: no cover
        finally:
            await read_stream_writer.aclose()
            await write_stream.aclose()

    async def terminate_session(self, client: httpx.AsyncClient) -> None:  # pragma: no cover
        """Terminate the session by sending a DELETE request."""
        if not self.session_id:
            return

        try:
            headers = self._prepare_headers()
            response = await client.delete(self.url, headers=headers)

            if response.status_code == 405:
                logger.debug("Server does not allow session termination")
            elif response.status_code not in (200, 204):
                logger.warning(f"Session termination failed: {response.status_code}")
        except Exception as exc:
            logger.warning(f"Session termination failed: {exc}")

    def get_session_id(self) -> str | None:
        """Get the current session ID."""
        return self.session_id


@asynccontextmanager
async def streamable_http_client(
    url: str,
    *,
    http_client: httpx.AsyncClient | None = None,
    terminate_on_close: bool = True,
) -> AsyncGenerator[
    tuple[
        MemoryObjectReceiveStream[SessionMessage | Exception],
        MemoryObjectSendStream[SessionMessage],
        GetSessionIdCallback,
    ],
    None,
]:
    """
    Client transport for StreamableHTTP.

    Args:
        url: The MCP server endpoint URL.
        http_client: Optional pre-configured httpx.AsyncClient. If None, a default
            client with recommended MCP timeouts will be created. To configure headers,
            authentication, or other HTTP settings, create an httpx.AsyncClient and pass it here.
        terminate_on_close: If True, send a DELETE request to terminate the session
            when the context exits.

    Yields:
        Tuple containing:
            - read_stream: Stream for reading messages from the server
            - write_stream: Stream for sending messages to the server
            - get_session_id_callback: Function to retrieve the current session ID

    Example:
        See examples/snippets/clients/ for usage patterns.
    """
    read_stream_writer, read_stream = anyio.create_memory_object_stream[SessionMessage | Exception](0)
    write_stream, write_stream_reader = anyio.create_memory_object_stream[SessionMessage](0)

    # Determine if we need to create and manage the client
    client_provided = http_client is not None
    client = http_client

    if client is None:
        # Create default client with recommended MCP timeouts
        client = create_mcp_http_client()

    transport = StreamableHTTPTransport(url)

    async with anyio.create_task_group() as tg:
        try:
            logger.debug(f"Connecting to StreamableHTTP endpoint: {url}")

            async with contextlib.AsyncExitStack() as stack:
                # Only manage client lifecycle if we created it
                if not client_provided:
                    await stack.enter_async_context(client)

                def start_get_stream() -> None:
                    tg.start_soon(transport.handle_get_stream, client, read_stream_writer)

                tg.start_soon(
                    transport.post_writer,
                    client,
                    write_stream_reader,
                    read_stream_writer,
                    write_stream,
                    start_get_stream,
                    tg,
                )

                try:
                    yield (
                        read_stream,
                        write_stream,
                        transport.get_session_id,
                    )
                finally:
                    if transport.session_id and terminate_on_close:
                        await transport.terminate_session(client)
                    tg.cancel_scope.cancel()
        finally:
            await read_stream_writer.aclose()
            await write_stream.aclose()


@asynccontextmanager
@deprecated("Use `streamable_http_client` instead.")
async def streamablehttp_client(
    url: str,
    headers: dict[str, str] | None = None,
    timeout: float | timedelta = 30,
    sse_read_timeout: float | timedelta = 60 * 5,
    terminate_on_close: bool = True,
    httpx_client_factory: McpHttpClientFactory = create_mcp_http_client,
    auth: httpx.Auth | None = None,
) -> AsyncGenerator[
    tuple[
        MemoryObjectReceiveStream[SessionMessage | Exception],
        MemoryObjectSendStream[SessionMessage],
        GetSessionIdCallback,
    ],
    None,
]:
    # Convert timeout parameters
    timeout_seconds = timeout.total_seconds() if isinstance(timeout, timedelta) else timeout
    sse_read_timeout_seconds = (
        sse_read_timeout.total_seconds() if isinstance(sse_read_timeout, timedelta) else sse_read_timeout
    )

    # Create httpx client using the factory with old-style parameters
    client = httpx_client_factory(
        headers=headers,
        timeout=httpx.Timeout(timeout_seconds, read=sse_read_timeout_seconds),
        auth=auth,
    )

    # Manage client lifecycle since we created it
    async with client:
        async with streamable_http_client(
            url,
            http_client=client,
            terminate_on_close=terminate_on_close,
        ) as streams:
            yield streams
