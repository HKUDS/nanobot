"""websockets bassd Socket Mode client

* https://docs.slack.dev/apis/events-api/using-socket-mode/
* https://docs.slack.dev/tools/python-slack-sdk/socket-mode/
* https://pypi.org/project/websockets/

"""

import asyncio
import logging
from asyncio import Future, Lock
from logging import Logger
from asyncio import Queue
from typing import Union, Optional, List, Callable, Awaitable

import websockets
from websockets.exceptions import WebSocketException

try:
    from websockets.asyncio.client import ClientConnection
except ImportError:
    # To keep compatibility with websockets <14.x we use WebSocketClientProtocol
    # To keep compatibility with websockets 8.x, we use this import over .legacy.client
    from websockets import WebSocketClientProtocol as ClientConnection  # type: ignore[no-redef, attr-defined]


from slack_sdk.socket_mode.async_client import AsyncBaseSocketModeClient
from slack_sdk.socket_mode.async_listeners import (
    AsyncWebSocketMessageListener,
    AsyncSocketModeRequestListener,
)
from slack_sdk.socket_mode.request import SocketModeRequest
from slack_sdk.web.async_client import AsyncWebClient

from ..logger.messages import debug_redacted_message_string


def _session_closed(session: Optional[ClientConnection]) -> bool:
    if session is None:
        return True
    if hasattr(session, "closed"):
        # The session is a WebSocketClientProtocol instance
        return session.closed
    # WebSocket close code, defined in https://datatracker.ietf.org/doc/html/rfc6455.html#section-7.1.5
    # None if the connection isn’t closed yet.
    return session.close_code is not None


class SocketModeClient(AsyncBaseSocketModeClient):
    logger: Logger
    web_client: AsyncWebClient
    app_token: str
    wss_uri: Optional[str]  # type: ignore[assignment]
    auto_reconnect_enabled: bool
    message_queue: Queue
    message_listeners: List[
        Union[
            AsyncWebSocketMessageListener,
            Callable[["AsyncBaseSocketModeClient", dict, Optional[str]], Awaitable[None]],
        ]
    ]
    socket_mode_request_listeners: List[
        Union[
            AsyncSocketModeRequestListener,
            Callable[["AsyncBaseSocketModeClient", SocketModeRequest], Awaitable[None]],
        ]
    ]

    message_receiver: Optional[Future]
    message_processor: Future

    ping_interval: float
    trace_enabled: bool

    current_session: Optional[ClientConnection]
    current_session_monitor: Optional[Future]

    default_auto_reconnect_enabled: bool
    closed: bool
    connect_operation_lock: Lock

    def __init__(
        self,
        app_token: str,
        logger: Optional[Logger] = None,
        web_client: Optional[AsyncWebClient] = None,
        auto_reconnect_enabled: bool = True,
        ping_interval: float = 10,
        trace_enabled: bool = False,
    ):
        """Socket Mode client

        Args:
            app_token: App-level token
            logger: Custom logger
            web_client: Web API client
            auto_reconnect_enabled: True if automatic reconnection is enabled (default: True)
            ping_interval: interval for ping-pong with Slack servers (seconds)
            trace_enabled: True if more verbose logs to see what's happening under the hood
        """
        self.app_token = app_token
        self.logger = logger or logging.getLogger(__name__)
        self.web_client = web_client or AsyncWebClient()
        self.closed = False
        self.connect_operation_lock = Lock()
        self.default_auto_reconnect_enabled = auto_reconnect_enabled
        self.auto_reconnect_enabled = self.default_auto_reconnect_enabled
        self.ping_interval = ping_interval
        self.trace_enabled = trace_enabled
        self.wss_uri = None
        self.message_queue = Queue()
        self.message_listeners = []
        self.socket_mode_request_listeners = []
        self.current_session = None
        self.current_session_monitor = None

        self.message_receiver = None
        self.message_processor = asyncio.ensure_future(self.process_messages())

    async def monitor_current_session(self) -> None:
        # In the asyncio runtime, accessing a shared object (self.current_session here) from
        # multiple tasks can cause race conditions and errors.
        # To avoid such, we access only the session that is active when this loop starts.
        session: ClientConnection = self.current_session  # type: ignore[assignment]
        session_id: str = await self.session_id()
        if self.logger.level <= logging.DEBUG:
            self.logger.debug(f"A new monitor_current_session() execution loop for {session_id} started")
        try:
            while not self.closed:
                if session != self.current_session:
                    if self.logger.level <= logging.DEBUG:
                        self.logger.debug(f"The monitor_current_session task for {session_id} is now cancelled")
                    break
                await asyncio.sleep(self.ping_interval)
                try:
                    if self.auto_reconnect_enabled and _session_closed(session=session):
                        self.logger.info(f"The session ({session_id}) seems to be already closed. Reconnecting...")
                        await self.connect_to_new_endpoint()
                except Exception as e:
                    self.logger.error(
                        "Failed to check the current session or reconnect to the server "
                        f"(error: {type(e).__name__}, message: {e}, session: {session_id})"
                    )
        except asyncio.CancelledError:
            if self.logger.level <= logging.DEBUG:
                self.logger.debug(f"The monitor_current_session task for {session_id} is now cancelled")
            raise

    async def receive_messages(self) -> None:
        # In the asyncio runtime, accessing a shared object (self.current_session here) from
        # multiple tasks can cause race conditions and errors.
        # To avoid such, we access only the session that is active when this loop starts.
        session: ClientConnection = self.current_session  # type: ignore[assignment]
        session_id: str = await self.session_id()
        consecutive_error_count = 0
        if self.logger.level <= logging.DEBUG:
            self.logger.debug(f"A new receive_messages() execution loop with {session_id} started")
        try:
            while not self.closed:
                if session != self.current_session:
                    if self.logger.level <= logging.DEBUG:
                        self.logger.debug(f"The running receive_messages task for {session_id} is now cancelled")
                    break
                try:
                    message = await session.recv()
                    if message is not None:
                        if isinstance(message, bytes):
                            message = message.decode("utf-8")
                        if self.logger.level <= logging.DEBUG:
                            self.logger.debug(
                                f"Received message: {debug_redacted_message_string(message)}, session: {session_id}"
                            )
                        await self.enqueue_message(message)
                    consecutive_error_count = 0
                except Exception as e:
                    consecutive_error_count += 1
                    self.logger.error(
                        f"Failed to receive or enqueue a message: {type(e).__name__}, error: {e}, session: {session_id}"
                    )
                    if isinstance(e, websockets.ConnectionClosedError):
                        await asyncio.sleep(self.ping_interval)
                    else:
                        await asyncio.sleep(consecutive_error_count)
        except asyncio.CancelledError:
            if self.logger.level <= logging.DEBUG:
                self.logger.debug(f"The running receive_messages task for {session_id} is now cancelled")
            raise

    async def is_connected(self) -> bool:
        return not self.closed and not _session_closed(self.current_session)

    async def session_id(self) -> str:
        return self.build_session_id(self.current_session)  # type: ignore[arg-type]

    async def connect(self):
        if self.wss_uri is None:
            self.wss_uri = await self.issue_new_wss_url()
        old_session: Optional[ClientConnection] = None if self.current_session is None else self.current_session
        # NOTE: websockets does not support proxy settings
        self.current_session = await websockets.connect(
            uri=self.wss_uri,
            ping_interval=self.ping_interval,
        )
        session_id = await self.session_id()
        self.auto_reconnect_enabled = self.default_auto_reconnect_enabled
        self.logger.info(f"A new session ({session_id}) has been established")

        if self.current_session_monitor is not None:
            self.current_session_monitor.cancel()
        self.current_session_monitor = asyncio.ensure_future(self.monitor_current_session())

        if self.logger.level <= logging.DEBUG:
            self.logger.debug(f"A new monitor_current_session() executor has been recreated for {session_id}")

        if self.message_receiver is not None:
            self.message_receiver.cancel()
        self.message_receiver = asyncio.ensure_future(self.receive_messages())

        if self.logger.level <= logging.DEBUG:
            self.logger.debug(f"A new receive_messages() executor has been recreated for {session_id}")

        if old_session is not None:
            await old_session.close()
            old_session_id = self.build_session_id(old_session)
            self.logger.info(f"The old session ({old_session_id}) has been abandoned")

    async def disconnect(self):
        if self.current_session is not None:
            await self.current_session.close()

    async def send_message(self, message: str):
        session = self.current_session
        session_id = self.build_session_id(session)  # type: ignore[arg-type]
        if self.logger.level <= logging.DEBUG:
            self.logger.debug(f"Sending a message: {message}, session: {session_id}")
        try:
            await session.send(message)  # type: ignore[union-attr]
        except WebSocketException as e:
            # We rarely get this exception while replacing the underlying WebSocket connections.
            # We can do one more try here as the self.current_session should be ready now.
            if self.logger.level <= logging.DEBUG:
                self.logger.debug(
                    f"Failed to send a message (error: {e}, message: {message}, session: {session_id})"
                    " as the underlying connection was replaced. Retrying the same request only one time..."
                )
            # Although acquiring self.connect_operation_lock also for the first method call is the safest way,
            # we avoid synchronizing a lot for better performance. That's why we are doing a retry here.
            try:
                if await self.is_connected():
                    await self.current_session.send(message)  # type: ignore[union-attr]
                else:
                    self.logger.warning(f"The current session ({session_id}) is no longer active. Failed to send a message")
                    raise e
            finally:
                if self.connect_operation_lock.locked() is True:
                    self.connect_operation_lock.release()

    async def close(self):
        self.closed = True
        self.auto_reconnect_enabled = False
        await self.disconnect()
        self.message_processor.cancel()
        if self.current_session_monitor is not None:
            self.current_session_monitor.cancel()
        if self.message_receiver is not None:
            self.message_receiver.cancel()

    @classmethod
    def build_session_id(cls, session: ClientConnection) -> str:
        if session is None:
            return ""
        return "s_" + str(hash(session))
