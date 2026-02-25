"""
StreamableHTTP Server Transport Module

This module implements an HTTP transport layer with Streamable HTTP.

The transport handles bidirectional communication using HTTP requests and
responses, with streaming support for long-running operations.
"""

import json
import logging
import re
from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from http import HTTPStatus
from typing import Any

import anyio
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from pydantic import ValidationError
from sse_starlette import EventSourceResponse
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import Receive, Scope, Send

from mcp.server.transport_security import (
    TransportSecurityMiddleware,
    TransportSecuritySettings,
)
from mcp.shared.message import ServerMessageMetadata, SessionMessage
from mcp.shared.version import SUPPORTED_PROTOCOL_VERSIONS
from mcp.types import (
    DEFAULT_NEGOTIATED_VERSION,
    INTERNAL_ERROR,
    INVALID_PARAMS,
    INVALID_REQUEST,
    PARSE_ERROR,
    ErrorData,
    JSONRPCError,
    JSONRPCMessage,
    JSONRPCRequest,
    JSONRPCResponse,
    RequestId,
)

logger = logging.getLogger(__name__)


# Header names
MCP_SESSION_ID_HEADER = "mcp-session-id"
MCP_PROTOCOL_VERSION_HEADER = "mcp-protocol-version"
LAST_EVENT_ID_HEADER = "last-event-id"

# Content types
CONTENT_TYPE_JSON = "application/json"
CONTENT_TYPE_SSE = "text/event-stream"

# Special key for the standalone GET stream
GET_STREAM_KEY = "_GET_stream"

# Session ID validation pattern (visible ASCII characters ranging from 0x21 to 0x7E)
# Pattern ensures entire string contains only valid characters by using ^ and $ anchors
SESSION_ID_PATTERN = re.compile(r"^[\x21-\x7E]+$")

# Type aliases
StreamId = str
EventId = str


@dataclass
class EventMessage:
    """
    A JSONRPCMessage with an optional event ID for stream resumability.
    """

    message: JSONRPCMessage
    event_id: str | None = None


EventCallback = Callable[[EventMessage], Awaitable[None]]


class EventStore(ABC):
    """
    Interface for resumability support via event storage.
    """

    @abstractmethod
    async def store_event(self, stream_id: StreamId, message: JSONRPCMessage | None) -> EventId:
        """
        Stores an event for later retrieval.

        Args:
            stream_id: ID of the stream the event belongs to
            message: The JSON-RPC message to store, or None for priming events

        Returns:
            The generated event ID for the stored event
        """
        pass  # pragma: no cover

    @abstractmethod
    async def replay_events_after(
        self,
        last_event_id: EventId,
        send_callback: EventCallback,
    ) -> StreamId | None:
        """
        Replays events that occurred after the specified event ID.

        Args:
            last_event_id: The ID of the last event the client received
            send_callback: A callback function to send events to the client

        Returns:
            The stream ID of the replayed events
        """
        pass  # pragma: no cover


class StreamableHTTPServerTransport:
    """
    HTTP server transport with event streaming support for MCP.

    Handles JSON-RPC messages in HTTP POST requests with SSE streaming.
    Supports optional JSON responses and session management.
    """

    # Server notification streams for POST requests as well as standalone SSE stream
    _read_stream_writer: MemoryObjectSendStream[SessionMessage | Exception] | None = None
    _read_stream: MemoryObjectReceiveStream[SessionMessage | Exception] | None = None
    _write_stream: MemoryObjectSendStream[SessionMessage] | None = None
    _write_stream_reader: MemoryObjectReceiveStream[SessionMessage] | None = None
    _security: TransportSecurityMiddleware

    def __init__(
        self,
        mcp_session_id: str | None,
        is_json_response_enabled: bool = False,
        event_store: EventStore | None = None,
        security_settings: TransportSecuritySettings | None = None,
        retry_interval: int | None = None,
    ) -> None:
        """
        Initialize a new StreamableHTTP server transport.

        Args:
            mcp_session_id: Optional session identifier for this connection.
                            Must contain only visible ASCII characters (0x21-0x7E).
            is_json_response_enabled: If True, return JSON responses for requests
                                    instead of SSE streams. Default is False.
            event_store: Event store for resumability support. If provided,
                        resumability will be enabled, allowing clients to
                        reconnect and resume messages.
            security_settings: Optional security settings for DNS rebinding protection.
            retry_interval: Retry interval in milliseconds to suggest to clients in SSE
                           retry field. When set, the server will send a retry field in
                           SSE priming events to control client reconnection timing for
                           polling behavior. Only used when event_store is provided.

        Raises:
            ValueError: If the session ID contains invalid characters.
        """
        if mcp_session_id is not None and not SESSION_ID_PATTERN.fullmatch(mcp_session_id):
            raise ValueError("Session ID must only contain visible ASCII characters (0x21-0x7E)")

        self.mcp_session_id = mcp_session_id
        self.is_json_response_enabled = is_json_response_enabled
        self._event_store = event_store
        self._security = TransportSecurityMiddleware(security_settings)
        self._retry_interval = retry_interval
        self._request_streams: dict[
            RequestId,
            tuple[
                MemoryObjectSendStream[EventMessage],
                MemoryObjectReceiveStream[EventMessage],
            ],
        ] = {}
        self._sse_stream_writers: dict[RequestId, MemoryObjectSendStream[dict[str, str]]] = {}
        self._terminated = False

    @property
    def is_terminated(self) -> bool:
        """Check if this transport has been explicitly terminated."""
        return self._terminated

    def close_sse_stream(self, request_id: RequestId) -> None:  # pragma: no cover
        """Close SSE connection for a specific request without terminating the stream.

        This method closes the HTTP connection for the specified request, triggering
        client reconnection. Events continue to be stored in the event store and will
        be replayed when the client reconnects with Last-Event-ID.

        Use this to implement polling behavior during long-running operations -
        client will reconnect after the retry interval specified in the priming event.

        Args:
            request_id: The request ID whose SSE stream should be closed.

        Note:
            This is a no-op if there is no active stream for the request ID.
            Requires event_store to be configured for events to be stored during
            the disconnect.
        """
        writer = self._sse_stream_writers.pop(request_id, None)
        if writer:
            writer.close()

        # Also close and remove request streams
        if request_id in self._request_streams:
            send_stream, receive_stream = self._request_streams.pop(request_id)
            send_stream.close()
            receive_stream.close()

    def close_standalone_sse_stream(self) -> None:  # pragma: no cover
        """Close the standalone GET SSE stream, triggering client reconnection.

        This method closes the HTTP connection for the standalone GET stream used
        for unsolicited server-to-client notifications. The client SHOULD reconnect
        with Last-Event-ID to resume receiving notifications.

        Use this to implement polling behavior for the notification stream -
        client will reconnect after the retry interval specified in the priming event.

        Note:
            This is a no-op if there is no active standalone SSE stream.
            Requires event_store to be configured for events to be stored during
            the disconnect.
            Currently, client reconnection for standalone GET streams is NOT
            implemented - this is a known gap (see test_standalone_get_stream_reconnection).
        """
        self.close_sse_stream(GET_STREAM_KEY)

    def _create_session_message(  # pragma: no cover
        self,
        message: JSONRPCMessage,
        request: Request,
        request_id: RequestId,
        protocol_version: str,
    ) -> SessionMessage:
        """Create a session message with metadata including close_sse_stream callback.

        The close_sse_stream callbacks are only provided when the client supports
        resumability (protocol version >= 2025-11-25). Old clients can't resume if
        the stream is closed early because they didn't receive a priming event.
        """
        # Only provide close callbacks when client supports resumability
        if self._event_store and protocol_version >= "2025-11-25":

            async def close_stream_callback() -> None:
                self.close_sse_stream(request_id)

            async def close_standalone_stream_callback() -> None:
                self.close_standalone_sse_stream()

            metadata = ServerMessageMetadata(
                request_context=request,
                close_sse_stream=close_stream_callback,
                close_standalone_sse_stream=close_standalone_stream_callback,
            )
        else:
            metadata = ServerMessageMetadata(request_context=request)

        return SessionMessage(message, metadata=metadata)

    async def _maybe_send_priming_event(
        self,
        request_id: RequestId,
        sse_stream_writer: MemoryObjectSendStream[dict[str, Any]],
        protocol_version: str,
    ) -> None:
        """Send priming event for SSE resumability if event_store is configured.

        Only sends priming events to clients with protocol version >= 2025-11-25,
        which includes the fix for handling empty SSE data. Older clients would
        crash trying to parse empty data as JSON.
        """
        if not self._event_store:
            return
        # Priming events have empty data which older clients cannot handle.
        if protocol_version < "2025-11-25":
            return
        priming_event_id = await self._event_store.store_event(
            str(request_id),  # Convert RequestId to StreamId (str)
            None,  # Priming event has no payload
        )
        priming_event: dict[str, str | int] = {"id": priming_event_id, "data": ""}
        if self._retry_interval is not None:
            priming_event["retry"] = self._retry_interval
        await sse_stream_writer.send(priming_event)

    def _create_error_response(
        self,
        error_message: str,
        status_code: HTTPStatus,
        error_code: int = INVALID_REQUEST,
        headers: dict[str, str] | None = None,
    ) -> Response:
        """Create an error response with a simple string message."""
        response_headers = {"Content-Type": CONTENT_TYPE_JSON}
        if headers:  # pragma: no cover
            response_headers.update(headers)

        if self.mcp_session_id:
            response_headers[MCP_SESSION_ID_HEADER] = self.mcp_session_id

        # Return a properly formatted JSON error response
        error_response = JSONRPCError(
            jsonrpc="2.0",
            id="server-error",  # We don't have a request ID for general errors
            error=ErrorData(
                code=error_code,
                message=error_message,
            ),
        )

        return Response(
            error_response.model_dump_json(by_alias=True, exclude_none=True),
            status_code=status_code,
            headers=response_headers,
        )

    def _create_json_response(  # pragma: no cover
        self,
        response_message: JSONRPCMessage | None,
        status_code: HTTPStatus = HTTPStatus.OK,
        headers: dict[str, str] | None = None,
    ) -> Response:
        """Create a JSON response from a JSONRPCMessage"""
        response_headers = {"Content-Type": CONTENT_TYPE_JSON}
        if headers:
            response_headers.update(headers)

        if self.mcp_session_id:
            response_headers[MCP_SESSION_ID_HEADER] = self.mcp_session_id

        return Response(
            response_message.model_dump_json(by_alias=True, exclude_none=True) if response_message else None,
            status_code=status_code,
            headers=response_headers,
        )

    def _get_session_id(self, request: Request) -> str | None:  # pragma: no cover
        """Extract the session ID from request headers."""
        return request.headers.get(MCP_SESSION_ID_HEADER)

    def _create_event_data(self, event_message: EventMessage) -> dict[str, str]:  # pragma: no cover
        """Create event data dictionary from an EventMessage."""
        event_data = {
            "event": "message",
            "data": event_message.message.model_dump_json(by_alias=True, exclude_none=True),
        }

        # If an event ID was provided, include it
        if event_message.event_id:
            event_data["id"] = event_message.event_id

        return event_data

    async def _clean_up_memory_streams(self, request_id: RequestId) -> None:  # pragma: no cover
        """Clean up memory streams for a given request ID."""
        if request_id in self._request_streams:
            try:
                # Close the request stream
                await self._request_streams[request_id][0].aclose()
                await self._request_streams[request_id][1].aclose()
            except Exception:
                # During cleanup, we catch all exceptions since streams might be in various states
                logger.debug("Error closing memory streams - may already be closed")
            finally:
                # Remove the request stream from the mapping
                self._request_streams.pop(request_id, None)

    async def handle_request(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Application entry point that handles all HTTP requests"""
        request = Request(scope, receive)

        # Validate request headers for DNS rebinding protection
        is_post = request.method == "POST"
        error_response = await self._security.validate_request(request, is_post=is_post)
        if error_response:  # pragma: no cover
            await error_response(scope, receive, send)
            return

        if self._terminated:  # pragma: no cover
            # If the session has been terminated, return 404 Not Found
            response = self._create_error_response(
                "Not Found: Session has been terminated",
                HTTPStatus.NOT_FOUND,
            )
            await response(scope, receive, send)
            return

        if request.method == "POST":
            await self._handle_post_request(scope, request, receive, send)
        elif request.method == "GET":  # pragma: no cover
            await self._handle_get_request(request, send)
        elif request.method == "DELETE":  # pragma: no cover
            await self._handle_delete_request(request, send)
        else:  # pragma: no cover
            await self._handle_unsupported_request(request, send)

    def _check_accept_headers(self, request: Request) -> tuple[bool, bool]:
        """Check if the request accepts the required media types."""
        accept_header = request.headers.get("accept", "")
        accept_types = [media_type.strip() for media_type in accept_header.split(",")]

        has_json = any(media_type.startswith(CONTENT_TYPE_JSON) for media_type in accept_types)
        has_sse = any(media_type.startswith(CONTENT_TYPE_SSE) for media_type in accept_types)

        return has_json, has_sse

    def _check_content_type(self, request: Request) -> bool:
        """Check if the request has the correct Content-Type."""
        content_type = request.headers.get("content-type", "")
        content_type_parts = [part.strip() for part in content_type.split(";")[0].split(",")]

        return any(part == CONTENT_TYPE_JSON for part in content_type_parts)

    async def _validate_accept_header(self, request: Request, scope: Scope, send: Send) -> bool:  # pragma: no cover
        """Validate Accept header based on response mode. Returns True if valid."""
        has_json, has_sse = self._check_accept_headers(request)
        if self.is_json_response_enabled:
            # For JSON-only responses, only require application/json
            if not has_json:
                response = self._create_error_response(
                    "Not Acceptable: Client must accept application/json",
                    HTTPStatus.NOT_ACCEPTABLE,
                )
                await response(scope, request.receive, send)
                return False
        # For SSE responses, require both content types
        elif not (has_json and has_sse):
            response = self._create_error_response(
                "Not Acceptable: Client must accept both application/json and text/event-stream",
                HTTPStatus.NOT_ACCEPTABLE,
            )
            await response(scope, request.receive, send)
            return False
        return True

    async def _handle_post_request(self, scope: Scope, request: Request, receive: Receive, send: Send) -> None:
        """Handle POST requests containing JSON-RPC messages."""
        writer = self._read_stream_writer
        if writer is None:  # pragma: no cover
            raise ValueError("No read stream writer available. Ensure connect() is called first.")
        try:
            # Validate Accept header
            if not await self._validate_accept_header(request, scope, send):
                return

            # Validate Content-Type
            if not self._check_content_type(request):  # pragma: no cover
                response = self._create_error_response(
                    "Unsupported Media Type: Content-Type must be application/json",
                    HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
                )
                await response(scope, receive, send)
                return

            # Parse the body - only read it once
            body = await request.body()

            try:
                raw_message = json.loads(body)
            except json.JSONDecodeError as e:
                response = self._create_error_response(f"Parse error: {str(e)}", HTTPStatus.BAD_REQUEST, PARSE_ERROR)
                await response(scope, receive, send)
                return

            try:  # pragma: no cover
                message = JSONRPCMessage.model_validate(raw_message)
            except ValidationError as e:  # pragma: no cover
                response = self._create_error_response(
                    f"Validation error: {str(e)}",
                    HTTPStatus.BAD_REQUEST,
                    INVALID_PARAMS,
                )
                await response(scope, receive, send)
                return

            # Check if this is an initialization request
            is_initialization_request = (
                isinstance(message.root, JSONRPCRequest) and message.root.method == "initialize"
            )  # pragma: no cover

            if is_initialization_request:  # pragma: no cover
                # Check if the server already has an established session
                if self.mcp_session_id:
                    # Check if request has a session ID
                    request_session_id = self._get_session_id(request)

                    # If request has a session ID but doesn't match, return 404
                    if request_session_id and request_session_id != self.mcp_session_id:
                        response = self._create_error_response(
                            "Not Found: Invalid or expired session ID",
                            HTTPStatus.NOT_FOUND,
                        )
                        await response(scope, receive, send)
                        return
            elif not await self._validate_request_headers(request, send):  # pragma: no cover
                return

            # For notifications and responses only, return 202 Accepted
            if not isinstance(message.root, JSONRPCRequest):  # pragma: no cover
                # Create response object and send it
                response = self._create_json_response(
                    None,
                    HTTPStatus.ACCEPTED,
                )
                await response(scope, receive, send)

                # Process the message after sending the response
                metadata = ServerMessageMetadata(request_context=request)
                session_message = SessionMessage(message, metadata=metadata)
                await writer.send(session_message)

                return

            # Extract protocol version for priming event decision.
            # For initialize requests, get from request params.
            # For other requests, get from header (already validated).
            protocol_version = (
                str(message.root.params.get("protocolVersion", DEFAULT_NEGOTIATED_VERSION))
                if is_initialization_request and message.root.params
                else request.headers.get(MCP_PROTOCOL_VERSION_HEADER, DEFAULT_NEGOTIATED_VERSION)
            )

            # Extract the request ID outside the try block for proper scope
            request_id = str(message.root.id)  # pragma: no cover
            # Register this stream for the request ID
            self._request_streams[request_id] = anyio.create_memory_object_stream[EventMessage](0)  # pragma: no cover
            request_stream_reader = self._request_streams[request_id][1]  # pragma: no cover

            if self.is_json_response_enabled:  # pragma: no cover
                # Process the message
                metadata = ServerMessageMetadata(request_context=request)
                session_message = SessionMessage(message, metadata=metadata)
                await writer.send(session_message)
                try:
                    # Process messages from the request-specific stream
                    # We need to collect all messages until we get a response
                    response_message = None

                    # Use similar approach to SSE writer for consistency
                    async for event_message in request_stream_reader:
                        # If it's a response, this is what we're waiting for
                        if isinstance(event_message.message.root, JSONRPCResponse | JSONRPCError):
                            response_message = event_message.message
                            break
                        # For notifications and request, keep waiting
                        else:
                            logger.debug(f"received: {event_message.message.root.method}")

                    # At this point we should have a response
                    if response_message:
                        # Create JSON response
                        response = self._create_json_response(response_message)
                        await response(scope, receive, send)
                    else:
                        # This shouldn't happen in normal operation
                        logger.error("No response message received before stream closed")
                        response = self._create_error_response(
                            "Error processing request: No response received",
                            HTTPStatus.INTERNAL_SERVER_ERROR,
                        )
                        await response(scope, receive, send)
                except Exception:
                    logger.exception("Error processing JSON response")
                    response = self._create_error_response(
                        "Error processing request",
                        HTTPStatus.INTERNAL_SERVER_ERROR,
                        INTERNAL_ERROR,
                    )
                    await response(scope, receive, send)
                finally:
                    await self._clean_up_memory_streams(request_id)
            else:  # pragma: no cover
                # Create SSE stream
                sse_stream_writer, sse_stream_reader = anyio.create_memory_object_stream[dict[str, str]](0)

                # Store writer reference so close_sse_stream() can close it
                self._sse_stream_writers[request_id] = sse_stream_writer

                async def sse_writer():
                    # Get the request ID from the incoming request message
                    try:
                        async with sse_stream_writer, request_stream_reader:
                            # Send priming event for SSE resumability
                            await self._maybe_send_priming_event(request_id, sse_stream_writer, protocol_version)

                            # Process messages from the request-specific stream
                            async for event_message in request_stream_reader:
                                # Build the event data
                                event_data = self._create_event_data(event_message)
                                await sse_stream_writer.send(event_data)

                                # If response, remove from pending streams and close
                                if isinstance(
                                    event_message.message.root,
                                    JSONRPCResponse | JSONRPCError,
                                ):
                                    break
                    except anyio.ClosedResourceError:
                        # Expected when close_sse_stream() is called
                        logger.debug("SSE stream closed by close_sse_stream()")
                    except Exception:
                        logger.exception("Error in SSE writer")
                    finally:
                        logger.debug("Closing SSE writer")
                        self._sse_stream_writers.pop(request_id, None)
                        await self._clean_up_memory_streams(request_id)

                # Create and start EventSourceResponse
                # SSE stream mode (original behavior)
                # Set up headers
                headers = {
                    "Cache-Control": "no-cache, no-transform",
                    "Connection": "keep-alive",
                    "Content-Type": CONTENT_TYPE_SSE,
                    **({MCP_SESSION_ID_HEADER: self.mcp_session_id} if self.mcp_session_id else {}),
                }
                response = EventSourceResponse(
                    content=sse_stream_reader,
                    data_sender_callable=sse_writer,
                    headers=headers,
                )

                # Start the SSE response (this will send headers immediately)
                try:
                    # First send the response to establish the SSE connection
                    async with anyio.create_task_group() as tg:
                        tg.start_soon(response, scope, receive, send)
                        # Then send the message to be processed by the server
                        session_message = self._create_session_message(message, request, request_id, protocol_version)
                        await writer.send(session_message)
                except Exception:
                    logger.exception("SSE response error")
                    await sse_stream_writer.aclose()
                    await sse_stream_reader.aclose()
                    await self._clean_up_memory_streams(request_id)

        except Exception as err:  # pragma: no cover
            logger.exception("Error handling POST request")
            response = self._create_error_response(
                f"Error handling POST request: {err}",
                HTTPStatus.INTERNAL_SERVER_ERROR,
                INTERNAL_ERROR,
            )
            await response(scope, receive, send)
            if writer:
                await writer.send(Exception(err))
            return

    async def _handle_get_request(self, request: Request, send: Send) -> None:  # pragma: no cover
        """
        Handle GET request to establish SSE.

        This allows the server to communicate to the client without the client
        first sending data via HTTP POST. The server can send JSON-RPC requests
        and notifications on this stream.
        """
        writer = self._read_stream_writer
        if writer is None:
            raise ValueError("No read stream writer available. Ensure connect() is called first.")

        # Validate Accept header - must include text/event-stream
        _, has_sse = self._check_accept_headers(request)

        if not has_sse:
            response = self._create_error_response(
                "Not Acceptable: Client must accept text/event-stream",
                HTTPStatus.NOT_ACCEPTABLE,
            )
            await response(request.scope, request.receive, send)
            return

        if not await self._validate_request_headers(request, send):
            return

        # Handle resumability: check for Last-Event-ID header
        if last_event_id := request.headers.get(LAST_EVENT_ID_HEADER):
            await self._replay_events(last_event_id, request, send)
            return

        headers = {
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "Content-Type": CONTENT_TYPE_SSE,
        }

        if self.mcp_session_id:
            headers[MCP_SESSION_ID_HEADER] = self.mcp_session_id

        # Check if we already have an active GET stream
        if GET_STREAM_KEY in self._request_streams:
            response = self._create_error_response(
                "Conflict: Only one SSE stream is allowed per session",
                HTTPStatus.CONFLICT,
            )
            await response(request.scope, request.receive, send)
            return

        # Create SSE stream
        sse_stream_writer, sse_stream_reader = anyio.create_memory_object_stream[dict[str, str]](0)

        async def standalone_sse_writer():
            try:
                # Create a standalone message stream for server-initiated messages

                self._request_streams[GET_STREAM_KEY] = anyio.create_memory_object_stream[EventMessage](0)
                standalone_stream_reader = self._request_streams[GET_STREAM_KEY][1]

                async with sse_stream_writer, standalone_stream_reader:
                    # Process messages from the standalone stream
                    async for event_message in standalone_stream_reader:
                        # For the standalone stream, we handle:
                        # - JSONRPCNotification (server sends notifications to client)
                        # - JSONRPCRequest (server sends requests to client)
                        # We should NOT receive JSONRPCResponse

                        # Send the message via SSE
                        event_data = self._create_event_data(event_message)
                        await sse_stream_writer.send(event_data)
            except Exception:
                logger.exception("Error in standalone SSE writer")
            finally:
                logger.debug("Closing standalone SSE writer")
                await self._clean_up_memory_streams(GET_STREAM_KEY)

        # Create and start EventSourceResponse
        response = EventSourceResponse(
            content=sse_stream_reader,
            data_sender_callable=standalone_sse_writer,
            headers=headers,
        )

        try:
            # This will send headers immediately and establish the SSE connection
            await response(request.scope, request.receive, send)
        except Exception:
            logger.exception("Error in standalone SSE response")
            await sse_stream_writer.aclose()
            await sse_stream_reader.aclose()
            await self._clean_up_memory_streams(GET_STREAM_KEY)

    async def _handle_delete_request(self, request: Request, send: Send) -> None:  # pragma: no cover
        """Handle DELETE requests for explicit session termination."""
        # Validate session ID
        if not self.mcp_session_id:
            # If no session ID set, return Method Not Allowed
            response = self._create_error_response(
                "Method Not Allowed: Session termination not supported",
                HTTPStatus.METHOD_NOT_ALLOWED,
            )
            await response(request.scope, request.receive, send)
            return

        if not await self._validate_request_headers(request, send):
            return

        await self.terminate()

        response = self._create_json_response(
            None,
            HTTPStatus.OK,
        )
        await response(request.scope, request.receive, send)

    async def terminate(self) -> None:
        """Terminate the current session, closing all streams.

        Once terminated, all requests with this session ID will receive 404 Not Found.
        """

        self._terminated = True
        logger.info(f"Terminating session: {self.mcp_session_id}")

        # We need a copy of the keys to avoid modification during iteration
        request_stream_keys = list(self._request_streams.keys())

        # Close all request streams asynchronously
        for key in request_stream_keys:  # pragma: no cover
            await self._clean_up_memory_streams(key)

        # Clear the request streams dictionary immediately
        self._request_streams.clear()
        try:
            if self._read_stream_writer is not None:  # pragma: no branch
                await self._read_stream_writer.aclose()
            if self._read_stream is not None:  # pragma: no branch
                await self._read_stream.aclose()
            if self._write_stream_reader is not None:  # pragma: no branch
                await self._write_stream_reader.aclose()
            if self._write_stream is not None:  # pragma: no branch
                await self._write_stream.aclose()
        except Exception as e:  # pragma: no cover
            # During cleanup, we catch all exceptions since streams might be in various states
            logger.debug(f"Error closing streams: {e}")

    async def _handle_unsupported_request(self, request: Request, send: Send) -> None:  # pragma: no cover
        """Handle unsupported HTTP methods."""
        headers = {
            "Content-Type": CONTENT_TYPE_JSON,
            "Allow": "GET, POST, DELETE",
        }
        if self.mcp_session_id:
            headers[MCP_SESSION_ID_HEADER] = self.mcp_session_id

        response = self._create_error_response(
            "Method Not Allowed",
            HTTPStatus.METHOD_NOT_ALLOWED,
            headers=headers,
        )
        await response(request.scope, request.receive, send)

    async def _validate_request_headers(self, request: Request, send: Send) -> bool:  # pragma: no cover
        if not await self._validate_session(request, send):
            return False
        if not await self._validate_protocol_version(request, send):
            return False
        return True

    async def _validate_session(self, request: Request, send: Send) -> bool:  # pragma: no cover
        """Validate the session ID in the request."""
        if not self.mcp_session_id:
            # If we're not using session IDs, return True
            return True

        # Get the session ID from the request headers
        request_session_id = self._get_session_id(request)

        # If no session ID provided but required, return error
        if not request_session_id:
            response = self._create_error_response(
                "Bad Request: Missing session ID",
                HTTPStatus.BAD_REQUEST,
            )
            await response(request.scope, request.receive, send)
            return False

        # If session ID doesn't match, return error
        if request_session_id != self.mcp_session_id:
            response = self._create_error_response(
                "Not Found: Invalid or expired session ID",
                HTTPStatus.NOT_FOUND,
            )
            await response(request.scope, request.receive, send)
            return False

        return True

    async def _validate_protocol_version(self, request: Request, send: Send) -> bool:  # pragma: no cover
        """Validate the protocol version header in the request."""
        # Get the protocol version from the request headers
        protocol_version = request.headers.get(MCP_PROTOCOL_VERSION_HEADER)

        # If no protocol version provided, assume default version
        if protocol_version is None:
            protocol_version = DEFAULT_NEGOTIATED_VERSION

        # Check if the protocol version is supported
        if protocol_version not in SUPPORTED_PROTOCOL_VERSIONS:
            supported_versions = ", ".join(SUPPORTED_PROTOCOL_VERSIONS)
            response = self._create_error_response(
                f"Bad Request: Unsupported protocol version: {protocol_version}. "
                + f"Supported versions: {supported_versions}",
                HTTPStatus.BAD_REQUEST,
            )
            await response(request.scope, request.receive, send)
            return False

        return True

    async def _replay_events(self, last_event_id: str, request: Request, send: Send) -> None:  # pragma: no cover
        """
        Replays events that would have been sent after the specified event ID.
        Only used when resumability is enabled.
        """
        event_store = self._event_store
        if not event_store:
            return

        try:
            headers = {
                "Cache-Control": "no-cache, no-transform",
                "Connection": "keep-alive",
                "Content-Type": CONTENT_TYPE_SSE,
            }

            if self.mcp_session_id:
                headers[MCP_SESSION_ID_HEADER] = self.mcp_session_id

            # Get protocol version from header (already validated in _validate_protocol_version)
            replay_protocol_version = request.headers.get(MCP_PROTOCOL_VERSION_HEADER, DEFAULT_NEGOTIATED_VERSION)

            # Create SSE stream for replay
            sse_stream_writer, sse_stream_reader = anyio.create_memory_object_stream[dict[str, str]](0)

            async def replay_sender():
                try:
                    async with sse_stream_writer:
                        # Define an async callback for sending events
                        async def send_event(event_message: EventMessage) -> None:
                            event_data = self._create_event_data(event_message)
                            await sse_stream_writer.send(event_data)

                        # Replay past events and get the stream ID
                        stream_id = await event_store.replay_events_after(last_event_id, send_event)

                        # If stream ID not in mapping, create it
                        if stream_id and stream_id not in self._request_streams:
                            # Register SSE writer so close_sse_stream() can close it
                            self._sse_stream_writers[stream_id] = sse_stream_writer

                            # Send priming event for this new connection
                            await self._maybe_send_priming_event(stream_id, sse_stream_writer, replay_protocol_version)

                            # Create new request streams for this connection
                            self._request_streams[stream_id] = anyio.create_memory_object_stream[EventMessage](0)
                            msg_reader = self._request_streams[stream_id][1]

                            # Forward messages to SSE
                            async with msg_reader:
                                async for event_message in msg_reader:
                                    event_data = self._create_event_data(event_message)

                                    await sse_stream_writer.send(event_data)
                except anyio.ClosedResourceError:
                    # Expected when close_sse_stream() is called
                    logger.debug("Replay SSE stream closed by close_sse_stream()")
                except Exception:
                    logger.exception("Error in replay sender")

            # Create and start EventSourceResponse
            response = EventSourceResponse(
                content=sse_stream_reader,
                data_sender_callable=replay_sender,
                headers=headers,
            )

            try:
                await response(request.scope, request.receive, send)
            except Exception:
                logger.exception("Error in replay response")
            finally:
                await sse_stream_writer.aclose()
                await sse_stream_reader.aclose()

        except Exception:
            logger.exception("Error replaying events")
            response = self._create_error_response(
                "Error replaying events",
                HTTPStatus.INTERNAL_SERVER_ERROR,
                INTERNAL_ERROR,
            )
            await response(request.scope, request.receive, send)

    @asynccontextmanager
    async def connect(
        self,
    ) -> AsyncGenerator[
        tuple[
            MemoryObjectReceiveStream[SessionMessage | Exception],
            MemoryObjectSendStream[SessionMessage],
        ],
        None,
    ]:
        """Context manager that provides read and write streams for a connection.

        Yields:
            Tuple of (read_stream, write_stream) for bidirectional communication
        """

        # Create the memory streams for this connection

        read_stream_writer, read_stream = anyio.create_memory_object_stream[SessionMessage | Exception](0)
        write_stream, write_stream_reader = anyio.create_memory_object_stream[SessionMessage](0)

        # Store the streams
        self._read_stream_writer = read_stream_writer
        self._read_stream = read_stream
        self._write_stream_reader = write_stream_reader
        self._write_stream = write_stream

        # Start a task group for message routing
        async with anyio.create_task_group() as tg:
            # Create a message router that distributes messages to request streams
            async def message_router():  # pragma: no cover
                try:
                    async for session_message in write_stream_reader:
                        # Determine which request stream(s) should receive this message
                        message = session_message.message
                        target_request_id = None
                        # Check if this is a response
                        if isinstance(message.root, JSONRPCResponse | JSONRPCError):
                            response_id = str(message.root.id)
                            # If this response is for an existing request stream,
                            # send it there
                            target_request_id = response_id
                        # Extract related_request_id from meta if it exists
                        elif (
                            session_message.metadata is not None
                            and isinstance(
                                session_message.metadata,
                                ServerMessageMetadata,
                            )
                            and session_message.metadata.related_request_id is not None
                        ):
                            target_request_id = str(session_message.metadata.related_request_id)

                        request_stream_id = target_request_id if target_request_id is not None else GET_STREAM_KEY

                        # Store the event if we have an event store,
                        # regardless of whether a client is connected
                        # messages will be replayed on the re-connect
                        event_id = None
                        if self._event_store:
                            event_id = await self._event_store.store_event(request_stream_id, message)
                            logger.debug(f"Stored {event_id} from {request_stream_id}")

                        if request_stream_id in self._request_streams:
                            try:
                                # Send both the message and the event ID
                                await self._request_streams[request_stream_id][0].send(EventMessage(message, event_id))
                            except (
                                anyio.BrokenResourceError,
                                anyio.ClosedResourceError,
                            ):
                                # Stream might be closed, remove from registry
                                self._request_streams.pop(request_stream_id, None)
                        else:
                            logger.debug(
                                f"""Request stream {request_stream_id} not found 
                                for message. Still processing message as the client
                                might reconnect and replay."""
                            )
                except anyio.ClosedResourceError:
                    if self._terminated:
                        logger.debug("Read stream closed by client")
                    else:
                        logger.exception("Unexpected closure of read stream in message router")
                except Exception:
                    logger.exception("Error in message router")

            # Start the message router
            tg.start_soon(message_router)

            try:
                # Yield the streams for the caller to use
                yield read_stream, write_stream
            finally:
                for stream_id in list(self._request_streams.keys()):  # pragma: no cover
                    await self._clean_up_memory_streams(stream_id)
                self._request_streams.clear()

                # Clean up the read and write streams
                try:
                    await read_stream_writer.aclose()
                    await read_stream.aclose()
                    await write_stream_reader.aclose()
                    await write_stream.aclose()
                except Exception as e:  # pragma: no cover
                    # During cleanup, we catch all exceptions since streams might be in various states
                    logger.debug(f"Error closing streams: {e}")
