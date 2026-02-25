import asyncio
import logging
import signal
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import (
    Any,
    AsyncIterable,
    Awaitable,
    Callable,
    Coroutine,
    Iterator,
    Mapping,
    Optional,
    Set,
    Union,
)

import anyio
from starlette.background import BackgroundTask
from starlette.concurrency import iterate_in_threadpool
from starlette.datastructures import MutableHeaders
from starlette.responses import Response
from starlette.types import Receive, Scope, Send, Message

from sse_starlette.event import ServerSentEvent, ensure_bytes


logger = logging.getLogger(__name__)


@dataclass
class _ShutdownState:
    """Per-thread state for shutdown coordination.

    Issue #152 fix: Uses threading.local() instead of ContextVar to ensure
    one watcher per thread rather than one per async context.
    """

    events: Set[anyio.Event] = field(default_factory=set)
    watcher_started: bool = False


# Each thread gets its own shutdown state (one event loop per thread typically)
_thread_state = threading.local()


def _get_shutdown_state() -> _ShutdownState:
    """Get or create shutdown state for the current thread."""
    state = getattr(_thread_state, "shutdown_state", None)
    if state is None:
        state = _ShutdownState()
        _thread_state.shutdown_state = state
    return state


def _get_uvicorn_server():
    """
    Try to get uvicorn Server instance via signal handler introspection.

    When uvicorn registers signal handlers, they're bound methods on the Server instance.
    We can retrieve the Server from the handler's __self__ attribute.

    Returns None if:
    - Not running under uvicorn
    - Signal handler isn't a bound method
    - Any introspection fails
    """
    try:
        handler = signal.getsignal(signal.SIGTERM)
        if hasattr(handler, "__self__"):
            server = handler.__self__
            if hasattr(server, "should_exit"):
                return server
    except Exception:
        pass
    return None


async def _shutdown_watcher() -> None:
    """
    Poll for shutdown and broadcast to all events in this context.

    One watcher runs per thread (event loop). Checks two shutdown sources:
    1. AppStatus.should_exit - set when our monkey-patch works
    2. uvicorn Server.should_exit - via signal handler introspection (Issue #132 fix)

    When either becomes True, signals all registered events.
    """
    state = _get_shutdown_state()
    uvicorn_server = _get_uvicorn_server()

    try:
        while True:
            # Check our flag (monkey-patch worked or manually set)
            if AppStatus.should_exit:
                break
            # Check uvicorn's flag directly (monkey-patch failed - Issue #132)
            if (
                AppStatus.enable_automatic_graceful_drain
                and uvicorn_server is not None
                and uvicorn_server.should_exit
            ):
                AppStatus.should_exit = True  # Sync state for consistency
                break
            await anyio.sleep(0.5)

        # Shutdown detected - broadcast to all waiting events
        for event in list(state.events):
            event.set()
    finally:
        # Allow watcher to be restarted if loop is reused
        state.watcher_started = False


def _ensure_watcher_started_on_this_loop() -> None:
    """Ensure the shutdown watcher is running for this thread (event loop)."""
    state = _get_shutdown_state()
    if not state.watcher_started:
        state.watcher_started = True
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_shutdown_watcher())
        except RuntimeError:
            # No running loop - shouldn't happen in normal use
            state.watcher_started = False


class SendTimeoutError(TimeoutError):
    pass


class AppStatus:
    """Helper to capture a shutdown signal from Uvicorn so we can gracefully terminate SSE streams."""

    should_exit = False
    enable_automatic_graceful_drain = True
    original_handler: Optional[Callable] = None

    @staticmethod
    def disable_automatic_graceful_drain():
        """
        Prevent automatic SSE stream termination on server shutdown.

        WARNING: When disabled, you MUST set AppStatus.should_exit = True
        at some point during shutdown, or streams will never close and the
        server will hang indefinitely (or until uvicorn's graceful shutdown
        timeout expires).
        """
        AppStatus.enable_automatic_graceful_drain = False

    @staticmethod
    def enable_automatic_graceful_drain_mode():
        """
        Re-enable automatic SSE stream termination on server shutdown.

        This restores the default behavior where SIGTERM triggers immediate
        stream draining. Call this to undo a previous call to
        disable_automatic_graceful_drain().
        """
        AppStatus.enable_automatic_graceful_drain = True

    @staticmethod
    def handle_exit(*args, **kwargs):
        if AppStatus.enable_automatic_graceful_drain:
            AppStatus.should_exit = True
        if AppStatus.original_handler is not None:
            AppStatus.original_handler(*args, **kwargs)


try:
    from uvicorn.main import Server

    AppStatus.original_handler = Server.handle_exit
    Server.handle_exit = AppStatus.handle_exit  # type: ignore
except ImportError:
    logger.debug(
        "Uvicorn not installed. Graceful shutdown on server termination disabled."
    )

Content = Union[str, bytes, dict, ServerSentEvent, Any]
SyncContentStream = Iterator[Content]
AsyncContentStream = AsyncIterable[Content]
ContentStream = Union[AsyncContentStream, SyncContentStream]


class EventSourceResponse(Response):
    """
    Streaming response that sends data conforming to the SSE (Server-Sent Events) specification.
    """

    DEFAULT_PING_INTERVAL = 15
    DEFAULT_SEPARATOR = "\r\n"

    def __init__(
        self,
        content: ContentStream,
        status_code: int = 200,
        headers: Optional[Mapping[str, str]] = None,
        media_type: str = "text/event-stream",
        background: Optional[BackgroundTask] = None,
        ping: Optional[int] = None,
        sep: Optional[str] = None,
        ping_message_factory: Optional[Callable[[], ServerSentEvent]] = None,
        data_sender_callable: Optional[
            Callable[[], Coroutine[None, None, None]]
        ] = None,
        send_timeout: Optional[float] = None,
        client_close_handler_callable: Optional[
            Callable[[Message], Awaitable[None]]
        ] = None,
    ) -> None:
        # Validate separator
        if sep not in (None, "\r\n", "\r", "\n"):
            raise ValueError(f"sep must be one of: \\r\\n, \\r, \\n, got: {sep}")
        self.sep = sep or self.DEFAULT_SEPARATOR

        # If content is sync, wrap it for async iteration
        if isinstance(content, AsyncIterable):
            self.body_iterator = content
        else:
            self.body_iterator = iterate_in_threadpool(content)

        self.status_code = status_code
        self.media_type = self.media_type if media_type is None else media_type
        self.background = background
        self.data_sender_callable = data_sender_callable
        self.send_timeout = send_timeout

        # Build SSE-specific headers.
        _headers = MutableHeaders()
        if headers is not None:  # pragma: no cover
            _headers.update(headers)

        # "The no-store response directive indicates that any caches of any kind (private or shared)
        # should not store this response."
        # -- https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/Cache-Control
        # allow cache control header to be set by user to support fan out proxies
        # https://www.fastly.com/blog/server-sent-events-fastly

        _headers.setdefault("Cache-Control", "no-store")
        # mandatory for servers-sent events headers
        _headers["Connection"] = "keep-alive"
        _headers["X-Accel-Buffering"] = "no"
        self.init_headers(_headers)

        self.ping_interval = self.DEFAULT_PING_INTERVAL if ping is None else ping
        self.ping_message_factory = ping_message_factory

        self.client_close_handler_callable = client_close_handler_callable

        self.active = True
        # https://github.com/sysid/sse-starlette/pull/55#issuecomment-1732374113
        self._send_lock = anyio.Lock()

    @property
    def ping_interval(self) -> Union[int, float]:
        return self._ping_interval

    @ping_interval.setter
    def ping_interval(self, value: Union[int, float]) -> None:
        if not isinstance(value, (int, float)):
            raise TypeError("ping interval must be int")
        if value < 0:
            raise ValueError("ping interval must be greater than 0")
        self._ping_interval = value

    def enable_compression(self, force: bool = False) -> None:
        raise NotImplementedError("Compression is not supported for SSE streams.")

    async def _stream_response(self, send: Send) -> None:
        """Send out SSE data to the client as it becomes available in the iterator."""
        await send(
            {
                "type": "http.response.start",
                "status": self.status_code,
                "headers": self.raw_headers,
            }
        )

        async for data in self.body_iterator:
            chunk = ensure_bytes(data, self.sep)
            logger.debug("chunk: %s", chunk)
            with anyio.move_on_after(self.send_timeout) as cancel_scope:
                await send(
                    {"type": "http.response.body", "body": chunk, "more_body": True}
                )

            if cancel_scope and cancel_scope.cancel_called:
                if hasattr(self.body_iterator, "aclose"):
                    await self.body_iterator.aclose()
                raise SendTimeoutError()

        async with self._send_lock:
            self.active = False
            await send({"type": "http.response.body", "body": b"", "more_body": False})

    async def _listen_for_disconnect(self, receive: Receive) -> None:
        """Watch for a disconnect message from the client."""
        while self.active:
            message = await receive()
            if message["type"] == "http.disconnect":
                self.active = False
                logger.debug("Got event: http.disconnect. Stop streaming.")
                if self.client_close_handler_callable:
                    await self.client_close_handler_callable(message)
                break

    @staticmethod
    async def _listen_for_exit_signal() -> None:
        """Wait for shutdown signal via the shared watcher."""
        if AppStatus.should_exit:
            return

        _ensure_watcher_started_on_this_loop()

        state = _get_shutdown_state()
        event = anyio.Event()
        state.events.add(event)

        try:
            # Double-check after registration
            if AppStatus.should_exit:
                return
            await event.wait()
        finally:
            state.events.discard(event)

    async def _ping(self, send: Send) -> None:
        """Periodically send ping messages to keep the connection alive on proxies.
        - frequenccy ca every 15 seconds.
        - Alternatively one can send periodically a comment line (one starting with a ':' character)
        """
        while self.active:
            await anyio.sleep(self._ping_interval)
            sse_ping = (
                self.ping_message_factory()
                if self.ping_message_factory
                else ServerSentEvent(
                    comment=f"ping - {datetime.now(timezone.utc)}", sep=self.sep
                )
            )
            ping_bytes = ensure_bytes(sse_ping, self.sep)
            logger.debug("ping: %s", ping_bytes)

            async with self._send_lock:
                if self.active:
                    await send(
                        {
                            "type": "http.response.body",
                            "body": ping_bytes,
                            "more_body": True,
                        }
                    )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Entrypoint for Starlette's ASGI contract. We spin up tasks:
        - _stream_response to push events
        - _ping to keep the connection alive
        - _listen_for_exit_signal to respond to server shutdown
        - _listen_for_disconnect to respond to client disconnect
        """
        async with anyio.create_task_group() as task_group:
            # https://trio.readthedocs.io/en/latest/reference-core.html#custom-supervisors
            async def cancel_on_finish(coro: Callable[[], Awaitable[None]]):
                await coro()
                task_group.cancel_scope.cancel()

            task_group.start_soon(cancel_on_finish, lambda: self._stream_response(send))
            task_group.start_soon(cancel_on_finish, lambda: self._ping(send))
            task_group.start_soon(cancel_on_finish, self._listen_for_exit_signal)

            if self.data_sender_callable:
                task_group.start_soon(self.data_sender_callable)

            # Wait for the client to disconnect last
            task_group.start_soon(
                cancel_on_finish, lambda: self._listen_for_disconnect(receive)
            )

        if self.background is not None:
            await self.background()
