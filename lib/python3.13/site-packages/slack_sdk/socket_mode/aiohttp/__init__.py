"""aiohttp based Socket Mode client

* https://docs.slack.dev/apis/events-api/using-socket-mode/
* https://docs.slack.dev/tools/python-slack-sdk/socket-mode/
* https://pypi.org/project/aiohttp/

"""

import asyncio
import logging
import time
from asyncio import AbstractEventLoop
from asyncio import Future, Lock
from asyncio import Queue
from logging import Logger
from typing import Union, Optional, List, Callable, Awaitable

import aiohttp
from aiohttp import ClientWebSocketResponse, WSMessage, WSMsgType, ClientConnectionError

from slack_sdk.proxy_env_variable_loader import load_http_proxy_from_env
from slack_sdk.socket_mode.async_client import AsyncBaseSocketModeClient
from slack_sdk.socket_mode.async_listeners import (
    AsyncWebSocketMessageListener,
    AsyncSocketModeRequestListener,
)
from slack_sdk.socket_mode.request import SocketModeRequest
from slack_sdk.web.async_client import AsyncWebClient


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

    proxy: Optional[str]
    ping_interval: float
    trace_enabled: bool

    last_ping_pong_time: Optional[float]
    current_session: Optional[ClientWebSocketResponse]
    current_session_monitor: Optional[Future]

    default_auto_reconnect_enabled: bool
    closed: bool
    stale: bool
    connect_operation_lock: Lock

    on_message_listeners: List[Callable[[WSMessage], Awaitable[None]]]
    on_error_listeners: List[Callable[[WSMessage], Awaitable[None]]]
    on_close_listeners: List[Callable[[WSMessage], Awaitable[None]]]

    def __init__(
        self,
        app_token: str,
        logger: Optional[Logger] = None,
        web_client: Optional[AsyncWebClient] = None,
        proxy: Optional[str] = None,
        auto_reconnect_enabled: bool = True,
        ping_interval: float = 5,
        trace_enabled: bool = False,
        on_message_listeners: Optional[List[Callable[[WSMessage], Awaitable[None]]]] = None,
        on_error_listeners: Optional[List[Callable[[WSMessage], Awaitable[None]]]] = None,
        on_close_listeners: Optional[List[Callable[[WSMessage], Awaitable[None]]]] = None,
        loop: Optional[AbstractEventLoop] = None,
    ):
        """Socket Mode client

        Args:
            app_token: App-level token
            logger: Custom logger
            web_client: Web API client
            auto_reconnect_enabled: True if automatic reconnection is enabled (default: True)
            ping_interval: interval for ping-pong with Slack servers (seconds)
            trace_enabled: True if more verbose logs to see what's happening under the hood
            proxy: the HTTP proxy URL
            on_message_listeners: listener functions for on_message
            on_error_listeners: listener functions for on_error
            on_close_listeners: listener functions for on_close
            loop: an existing asyncio event loop
        """
        self.app_token = app_token
        self.logger = logger or logging.getLogger(__name__)
        self.web_client = web_client or AsyncWebClient()
        self.closed = False
        self.stale = False
        self.connect_operation_lock = Lock()
        self.proxy = proxy
        if self.proxy is None or len(self.proxy.strip()) == 0:
            env_variable = load_http_proxy_from_env(self.logger)
            if env_variable is not None:
                self.proxy = env_variable

        self.default_auto_reconnect_enabled = auto_reconnect_enabled
        self.auto_reconnect_enabled = self.default_auto_reconnect_enabled
        self.ping_interval = ping_interval
        self.trace_enabled = trace_enabled
        self.last_ping_pong_time = None

        self.wss_uri = None
        self.message_queue = Queue()
        self.message_listeners = []
        self.socket_mode_request_listeners = []
        self.current_session = None
        self.current_session_monitor = None

        # https://docs.aiohttp.org/en/stable/client_reference.html
        # Unless you are connecting to a large, unknown number of different servers
        # over the lifetime of your application,
        # it is suggested you use a single session for the lifetime of your application
        # to benefit from connection pooling.
        self.aiohttp_client_session = aiohttp.ClientSession(loop=loop)

        self.on_message_listeners = on_message_listeners or []
        self.on_error_listeners = on_error_listeners or []
        self.on_close_listeners = on_close_listeners or []

        self.message_receiver = None
        self.message_processor = asyncio.ensure_future(self.process_messages())

    async def monitor_current_session(self) -> None:
        # In the asyncio runtime, accessing a shared object (self.current_session here) from
        # multiple tasks can cause race conditions and errors.
        # To avoid such, we access only the session that is active when this loop starts.
        session: ClientWebSocketResponse = self.current_session  # type: ignore[assignment]
        session_id: str = self.build_session_id(session)

        if self.logger.level <= logging.DEBUG:
            self.logger.debug(f"A new monitor_current_session() execution loop for {session_id} started")
        try:
            logging_interval = 100
            counter_for_logging = 0

            while not self.closed:
                if session != self.current_session:
                    if self.logger.level <= logging.DEBUG:
                        self.logger.debug(f"The monitor_current_session task for {session_id} is now cancelled")
                    break
                try:
                    if self.trace_enabled and self.logger.level <= logging.DEBUG:
                        # The logging here is for detailed investigation on potential issues in this client.
                        # If you don't see this log for a while, it means that
                        # this receive_messages execution is no longer working for some reason.
                        counter_for_logging += 1
                        if counter_for_logging >= logging_interval:
                            counter_for_logging = 0
                            log_message = (
                                "#monitor_current_session method has been verifying if this session is active "
                                f"(session: {session_id}, logging interval: {logging_interval})"
                            )
                            self.logger.debug(log_message)

                    await asyncio.sleep(self.ping_interval)

                    if session is not None and session.closed is False:
                        t = time.time()
                        if self.last_ping_pong_time is None:
                            self.last_ping_pong_time = float(t)
                        try:
                            await session.ping(f"sdk-ping-pong:{t}".encode("utf-8"))
                        except Exception as e:
                            # The ping() method can fail for some reason.
                            # To establish a new connection even in this scenario,
                            # we ignore the exception here.
                            self.logger.warning(f"Failed to send a ping message ({session_id}): {e}")

                    if self.auto_reconnect_enabled:
                        should_reconnect = False
                        if session is None or session.closed:
                            self.logger.info(f"The session ({session_id}) seems to be already closed. Reconnecting...")
                            should_reconnect = True

                        if await self.is_ping_pong_failing():
                            disconnected_seconds = int(time.time() - self.last_ping_pong_time)  # type: ignore[operator]
                            self.logger.info(
                                f"The session ({session_id}) seems to be stale. Reconnecting..."
                                f" reason: disconnected for {disconnected_seconds}+ seconds)"
                            )
                            self.stale = True
                            self.last_ping_pong_time = None
                            should_reconnect = True

                        if should_reconnect is True or not await self.is_connected():
                            await self.connect_to_new_endpoint()

                except Exception as e:
                    self.logger.error(
                        f"Failed to check the current session ({session_id}) or reconnect to the server "
                        f"(error: {type(e).__name__}, message: {e})"
                    )
        except asyncio.CancelledError:
            if self.logger.level <= logging.DEBUG:
                self.logger.debug(f"The monitor_current_session task for {session_id} is now cancelled")
            raise

    async def receive_messages(self) -> None:
        # In the asyncio runtime, accessing a shared object (self.current_session here) from
        # multiple tasks can cause race conditions and errors.
        # To avoid such, we access only the session that is active when this loop starts.
        session = self.current_session
        session_id = self.build_session_id(session)  # type: ignore[arg-type]
        if self.logger.level <= logging.DEBUG:
            self.logger.debug(f"A new receive_messages() execution loop with {session_id} started")
        try:
            consecutive_error_count = 0
            logging_interval = 100
            counter_for_logging = 0

            while not self.closed:
                if session != self.current_session:
                    if self.logger.level <= logging.DEBUG:
                        self.logger.debug(f"The running receive_messages task for {session_id} is now cancelled")
                    break
                try:
                    message: WSMessage = await session.receive()  # type: ignore[union-attr]
                    # just in case, checking if the value is not None
                    if message is not None:
                        if self.logger.level <= logging.DEBUG:
                            # The following logging prints every single received message
                            # except empty message data ones.
                            m_type = WSMsgType(message.type)
                            message_type = m_type.name if m_type is not None else message.type
                            message_data = message.data
                            if isinstance(message_data, bytes):
                                message_data = message_data.decode("utf-8")
                            if message_data is not None and isinstance(message_data, (str, bytes)) and len(message_data) > 0:
                                # To skip the empty message that Slack server-side often sends
                                self.logger.debug(
                                    f"Received message "
                                    f"(type: {message_type}, "
                                    f"data: {message_data}, "
                                    f"extra: {message.extra}, "
                                    f"session: {session_id})"
                                )

                            if self.trace_enabled:
                                # The logging here is for detailed trouble shooting of potential issues in this client.
                                # If you don't see this log for a while, it can mean that
                                # this receive_messages execution is no longer working for some reason.
                                counter_for_logging += 1
                                if counter_for_logging >= logging_interval:
                                    counter_for_logging = 0
                                    log_message = (
                                        "#receive_messages method has been working without any issues "
                                        f"(session: {session_id}, logging interval: {logging_interval})"
                                    )
                                    self.logger.debug(log_message)

                        if message.type == WSMsgType.TEXT:
                            message_data = message.data
                            await self.enqueue_message(message_data)
                            for listener in self.on_message_listeners:
                                await listener(message)
                        elif message.type == WSMsgType.CLOSE:
                            if self.auto_reconnect_enabled:
                                self.logger.info(f"Received CLOSE event from {session_id}. Reconnecting...")
                                await self.connect_to_new_endpoint()
                            for listener in self.on_close_listeners:
                                await listener(message)
                        elif message.type == WSMsgType.ERROR:
                            for listener in self.on_error_listeners:
                                await listener(message)
                        elif message.type == WSMsgType.CLOSED:
                            await asyncio.sleep(self.ping_interval)
                            continue
                        elif message.type == WSMsgType.PING:
                            await session.pong(message.data)  # type: ignore[union-attr]
                            continue
                        elif message.type == WSMsgType.PONG:
                            if message.data is not None:
                                str_message_data = message.data.decode("utf-8")
                                elements = str_message_data.split(":")
                                if len(elements) == 2 and elements[0] == "sdk-ping-pong":
                                    try:
                                        self.last_ping_pong_time = float(elements[1])
                                    except Exception as e:
                                        self.logger.warning(
                                            f"Failed to parse the last_ping_pong_time value from {str_message_data}"
                                            f" - error : {e}, session: {session_id}"
                                        )
                            continue

                    consecutive_error_count = 0

                except Exception as e:
                    consecutive_error_count += 1
                    self.logger.error(f"Failed to receive or enqueue a message: {type(e).__name__}, {e} ({session_id})")
                    if isinstance(e, ClientConnectionError):
                        await asyncio.sleep(self.ping_interval)
                    else:
                        await asyncio.sleep(consecutive_error_count)
        except asyncio.CancelledError:
            if self.logger.level <= logging.DEBUG:
                self.logger.debug(f"The running receive_messages task for {session_id} is now cancelled")
            raise

    async def is_ping_pong_failing(self) -> bool:
        if self.last_ping_pong_time is None:
            return False
        disconnected_seconds = int(time.time() - self.last_ping_pong_time)
        return disconnected_seconds >= (self.ping_interval * 4)

    async def is_connected(self) -> bool:
        connected: bool = (
            not self.closed
            and not self.stale
            and self.current_session is not None
            and not self.current_session.closed
            and not await self.is_ping_pong_failing()
        )
        if self.logger.level <= logging.DEBUG and connected is False:
            # Prints more detailed information about the inactive connection
            is_ping_pong_failing = await self.is_ping_pong_failing()
            session_id = await self.session_id()
            self.logger.debug(
                "Inactive connection detected ("
                f"session_id: {session_id}, "
                f"closed: {self.closed}, "
                f"stale: {self.stale}, "
                f"current_session.closed: {self.current_session and self.current_session.closed}, "
                f"is_ping_pong_failing: {is_ping_pong_failing}"
                ")"
            )
        return connected

    async def session_id(self) -> str:
        return self.build_session_id(self.current_session)  # type: ignore[arg-type]

    async def connect(self):
        # This loop is used to ensure when a new session is created,
        # a new monitor and a new message receiver are also created.
        # If a new session is created but we failed to create the new
        # monitor or the new message, we should try it.
        while True:
            try:
                old_session: Optional[ClientWebSocketResponse] = (
                    None if self.current_session is None else self.current_session
                )

                # If the old session is broken (e.g. reset by peer), it might fail to close it.
                # We don't want to retry when this kind of cases happen.
                try:
                    # We should close old session before create a new one. Because when disconnect
                    # reason is `too_many_websockets`, we need to close the old one first to
                    # to decrease the number of connections.
                    self.auto_reconnect_enabled = False
                    if old_session is not None:
                        await old_session.close()
                        old_session_id = self.build_session_id(old_session)
                        self.logger.info(f"The old session ({old_session_id}) has been abandoned")
                except Exception as e:
                    self.logger.exception(f"Failed to close the old session : {e}")

                if self.wss_uri is None:
                    # If the underlying WSS URL does not exist,
                    # acquiring a new active WSS URL from the server-side first
                    self.wss_uri = await self.issue_new_wss_url()

                self.current_session = await self.aiohttp_client_session.ws_connect(
                    self.wss_uri,
                    autoping=False,
                    heartbeat=self.ping_interval,
                    proxy=self.proxy,
                    ssl=self.web_client.ssl,
                )
                session_id: str = await self.session_id()
                self.auto_reconnect_enabled = self.default_auto_reconnect_enabled
                self.stale = False
                self.logger.info(f"A new session ({session_id}) has been established")

                # The first ping from the new connection
                if self.logger.level <= logging.DEBUG:
                    self.logger.debug(f"Sending a ping message with the newly established connection ({session_id})...")
                t = time.time()
                await self.current_session.ping(f"sdk-ping-pong:{t}".encode("utf-8"))

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
                break
            except Exception as e:
                self.logger.exception(f"Failed to connect (error: {e}); Retrying...")
                await asyncio.sleep(self.ping_interval)

    async def disconnect(self):
        if self.current_session is not None:
            await self.current_session.close()
        session_id = await self.session_id()
        self.logger.info(f"The current session ({session_id}) has been abandoned by disconnect() method call")

    async def send_message(self, message: str):
        session_id = await self.session_id()
        if self.logger.level <= logging.DEBUG:
            self.logger.debug(f"Sending a message: {message} from session: {session_id}")
        try:
            await self.current_session.send_str(message)  # type: ignore[union-attr]
        except ConnectionError as e:
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
                await self.connect_operation_lock.acquire()
                if await self.is_connected():
                    await self.current_session.send_str(message)  # type: ignore[union-attr]
                else:
                    self.logger.warning(
                        f"The current session ({session_id}) is no longer active. " "Failed to send a message"
                    )
                    raise e
            finally:
                if self.connect_operation_lock.locked() is True:
                    self.connect_operation_lock.release()

    async def close(self):
        self.closed = True
        self.auto_reconnect_enabled = False
        await self.disconnect()
        if self.message_processor is not None:
            self.message_processor.cancel()
        if self.current_session_monitor is not None:
            self.current_session_monitor.cancel()
        if self.message_receiver is not None:
            self.message_receiver.cancel()
        if self.aiohttp_client_session is not None:
            await self.aiohttp_client_session.close()

    @classmethod
    def build_session_id(cls, session: ClientWebSocketResponse) -> str:
        if session is None:
            return ""
        return "s_" + str(hash(session))
