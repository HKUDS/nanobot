"""websocket-client bassd Socket Mode client

* https://docs.slack.dev/apis/events-api/using-socket-mode/
* https://docs.slack.dev/tools/python-slack-sdk/socket-mode/
* https://pypi.org/project/websocket-client/

"""

import logging
from concurrent.futures.thread import ThreadPoolExecutor
from logging import Logger
from queue import Queue
from threading import Lock
from typing import Callable, List, Optional, Tuple, Union

import websocket
from websocket import WebSocketApp, WebSocketException

from slack_sdk.socket_mode.client import BaseSocketModeClient
from slack_sdk.socket_mode.interval_runner import IntervalRunner
from slack_sdk.socket_mode.listeners import (
    WebSocketMessageListener,
    SocketModeRequestListener,
)
from slack_sdk.socket_mode.request import SocketModeRequest
from slack_sdk.web import WebClient

from ..logger.messages import debug_redacted_message_string


class SocketModeClient(BaseSocketModeClient):
    logger: Logger
    web_client: WebClient
    app_token: str
    wss_uri: Optional[str]  # type: ignore[assignment]
    message_queue: Queue
    message_listeners: List[
        Union[
            WebSocketMessageListener,
            Callable[["BaseSocketModeClient", dict, Optional[str]], None],
        ]
    ]
    socket_mode_request_listeners: List[
        Union[
            SocketModeRequestListener,
            Callable[["BaseSocketModeClient", SocketModeRequest], None],
        ]
    ]

    current_app_monitor: IntervalRunner
    current_app_monitor_started: bool
    message_processor: IntervalRunner
    message_workers: ThreadPoolExecutor

    current_session: Optional[WebSocketApp]
    current_session_runner: IntervalRunner

    auto_reconnect_enabled: bool
    default_auto_reconnect_enabled: bool

    closed: bool
    connect_operation_lock: Lock

    on_open_listeners: List[Callable[[WebSocketApp], None]]
    on_message_listeners: List[Callable[[WebSocketApp, str], None]]
    on_error_listeners: List[Callable[[WebSocketApp, Exception], None]]
    on_close_listeners: List[Callable[[WebSocketApp], None]]

    def __init__(
        self,
        app_token: str,
        logger: Optional[Logger] = None,
        web_client: Optional[WebClient] = None,
        auto_reconnect_enabled: bool = True,
        ping_interval: float = 10,
        concurrency: int = 10,
        trace_enabled: bool = False,
        http_proxy_host: Optional[str] = None,
        http_proxy_port: Optional[int] = None,
        http_proxy_auth: Optional[Tuple[str, str]] = None,
        proxy_type: Optional[str] = None,
        on_open_listeners: Optional[List[Callable[[WebSocketApp], None]]] = None,
        on_message_listeners: Optional[List[Callable[[WebSocketApp, str], None]]] = None,
        on_error_listeners: Optional[List[Callable[[WebSocketApp, Exception], None]]] = None,
        on_close_listeners: Optional[List[Callable[[WebSocketApp], None]]] = None,
    ):
        """

        Args:
            app_token: App-level token
            logger: Custom logger
            web_client: Web API client
            auto_reconnect_enabled: True if automatic reconnection is enabled (default: True)
            ping_interval: interval for ping-pong with Slack servers (seconds)
            concurrency: the size of thread pool (default: 10)
            http_proxy_host: the HTTP proxy host
            http_proxy_port: the HTTP proxy port
            http_proxy_auth: the HTTP proxy username & password
            proxy_type: the HTTP proxy type
            on_open_listeners: listener functions for on_open
            on_message_listeners: listener functions for on_message
            on_error_listeners: listener functions for on_error
            on_close_listeners: listener functions for on_close
        """
        self.app_token = app_token
        self.logger = logger or logging.getLogger(__name__)
        self.web_client = web_client or WebClient()
        self.default_auto_reconnect_enabled = auto_reconnect_enabled
        self.auto_reconnect_enabled = self.default_auto_reconnect_enabled
        self.ping_interval = ping_interval
        self.wss_uri = None
        self.message_queue = Queue()
        self.message_listeners = []
        self.socket_mode_request_listeners = []

        self.current_session = None
        self.current_session_runner = IntervalRunner(self._run_current_session, 0.5).start()

        self.current_app_monitor_started = False
        self.current_app_monitor = IntervalRunner(self._monitor_current_session, self.ping_interval)

        self.closed = False
        self.connect_operation_lock = Lock()

        self.message_processor = IntervalRunner(self.process_messages, 0.001).start()
        self.message_workers = ThreadPoolExecutor(max_workers=concurrency)

        # NOTE: only global settings is provided by the library
        websocket.enableTrace(trace_enabled)

        self.http_proxy_host = http_proxy_host
        self.http_proxy_port = http_proxy_port
        self.http_proxy_auth = http_proxy_auth
        self.proxy_type = proxy_type

        self.on_open_listeners = on_open_listeners or []
        self.on_message_listeners = on_message_listeners or []
        self.on_error_listeners = on_error_listeners or []
        self.on_close_listeners = on_close_listeners or []

    def is_connected(self) -> bool:
        return self.current_session is not None and self.current_session.sock is not None

    def connect(self) -> None:
        def on_open(ws: WebSocketApp):
            if self.logger.level <= logging.DEBUG:
                self.logger.debug("on_open invoked")
            for listener in self.on_open_listeners:
                listener(ws)

        def on_message(ws: WebSocketApp, message: str):
            if self.logger.level <= logging.DEBUG:
                self.logger.debug(f"on_message invoked: (message: {debug_redacted_message_string(message)})")
            self.enqueue_message(message)
            for listener in self.on_message_listeners:
                listener(ws, message)

        def on_error(ws: WebSocketApp, error: Exception):
            self.logger.error(f"on_error invoked (error: {type(error).__name__}, message: {error})")
            for listener in self.on_error_listeners:
                listener(ws, error)

        def on_close(
            ws: WebSocketApp,
            close_status_code: Optional[int] = None,
            close_msg: Optional[str] = None,
        ):
            if self.logger.level <= logging.DEBUG:
                self.logger.debug(f"on_close invoked: (code: {close_status_code}, message: {close_msg})")
            if self.auto_reconnect_enabled:
                self.logger.info("Received CLOSE event. Reconnecting...")
                self.connect_to_new_endpoint()
            for listener in self.on_close_listeners:
                listener(ws)

        old_session: Optional[WebSocketApp] = self.current_session

        if self.wss_uri is None:
            self.wss_uri = self.issue_new_wss_url()

        self.current_session = websocket.WebSocketApp(
            self.wss_uri,
            on_open=on_open,
            on_message=on_message,
            on_error=on_error,
            on_close=on_close,
        )
        self.auto_reconnect_enabled = self.default_auto_reconnect_enabled

        if not self.current_app_monitor_started:
            self.current_app_monitor_started = True
            self.current_app_monitor.start()

        if old_session is not None:
            old_session.close()

        self.logger.info("A new session has been established")

    def disconnect(self) -> None:
        if self.current_session is not None:
            self.current_session.close()

    def send_message(self, message: str) -> None:
        if self.logger.level <= logging.DEBUG:
            self.logger.debug(f"Sending a message: {message}")
        try:
            self.current_session.send(message)  # type: ignore[union-attr]
        except WebSocketException as e:
            # We rarely get this exception while replacing the underlying WebSocket connections.
            # We can do one more try here as the self.current_session should be ready now.
            if self.logger.level <= logging.DEBUG:
                self.logger.debug(
                    f"Failed to send a message (error: {e}, message: {message})"
                    " as the underlying connection was replaced. Retrying the same request only one time..."
                )
            # Although acquiring self.connect_operation_lock also for the first method call is the safest way,
            # we avoid synchronizing a lot for better performance. That's why we are doing a retry here.
            with self.connect_operation_lock:
                if self.is_connected():
                    self.current_session.send(message)  # type: ignore[union-attr]
                else:
                    self.logger.warning(
                        f"The current session (session id: {self.session_id()}) is no longer active. "  # type: ignore[attr-defined] # noqa: E501
                        "Failed to send a message"
                    )
                    raise e

    def close(self) -> None:
        self.closed = True
        self.auto_reconnect_enabled = False
        self.disconnect()
        self.current_app_monitor.shutdown()
        self.message_processor.shutdown()
        self.message_workers.shutdown()

    def _run_current_session(self):
        if self.current_session is not None:
            try:
                self.logger.info("Starting to receive messages from a new connection")
                self.current_session.run_forever(
                    ping_interval=self.ping_interval,
                    http_proxy_host=self.http_proxy_host,
                    http_proxy_port=self.http_proxy_port,
                    http_proxy_auth=self.http_proxy_auth,
                    proxy_type=self.proxy_type,
                )
                self.logger.info("Stopped receiving messages from a connection")
            except Exception as e:
                self.logger.exception(f"Failed to start or stop the current session: {e}")
                # To let the monitoring job detect the connection issue, closing this session
                if self.current_session is not None:
                    self.current_session.close()

    def _monitor_current_session(self):
        if self.current_app_monitor_started:
            try:
                if self.auto_reconnect_enabled and (self.current_session is None or self.current_session.sock is None):
                    self.logger.info("The session seems to be already closed. Reconnecting...")
                    self.connect_to_new_endpoint()
            except Exception as e:
                self.logger.error(
                    "Failed to check the current session or reconnect to the server "
                    f"(error: {type(e).__name__}, message: {e})"
                )
