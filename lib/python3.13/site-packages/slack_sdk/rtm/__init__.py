"""A Python module for interacting with Slack's RTM API."""

import asyncio
import collections
import inspect
import logging
import os
import random
import signal
from asyncio import Future
from ssl import SSLContext
from threading import current_thread, main_thread
from typing import Any, Union, Sequence
from typing import Optional, Callable, DefaultDict

import aiohttp

import slack_sdk.errors as client_err
from slack_sdk.aiohttp_version_checker import validate_aiohttp_version
from slack_sdk.web.legacy_client import LegacyWebClient as WebClient


validate_aiohttp_version(aiohttp.__version__)


class RTMClient(object):
    """An RTMClient allows apps to communicate with the Slack Platform's RTM API.

    The event-driven architecture of this client allows you to simply
    link callbacks to their corresponding events. When an event occurs
    this client executes your callback while passing along any
    information it receives.

    Attributes:
        token (str): A string specifying an xoxp or xoxb token.
        run_async (bool): A boolean specifying if the client should
            be run in async mode. Default is False.
        auto_reconnect (bool): When true the client will automatically
            reconnect when (not manually) disconnected. Default is True.
        ssl (SSLContext): To use SSL support, pass an SSLContext object here.
            Default is None.
        proxy (str): To use proxy support, pass the string of the proxy server.
            e.g. "http://proxy.com"
            Authentication credentials can be passed in proxy URL.
            e.g. "http://user:pass@some.proxy.com"
            Default is None.
        timeout (int): The amount of seconds the session should wait before timing out.
            Default is 30.
        base_url (str): The base url for all HTTP requests.
            Note: This is only used in the WebClient.
            Default is "https://slack.com/api/".
        connect_method (str): An string specifying if the client
            will connect with `rtm.connect` or `rtm.start`.
            Default is `rtm.connect`.
        ping_interval (int): automatically send "ping" command every
            specified period of seconds. If set to 0, do not send automatically.
            Default is 30.
        loop (AbstractEventLoop): An event loop provided by asyncio.
            If None is specified we attempt to use the current loop
            with `get_event_loop`. Default is None.

    Methods:
        ping: Sends a ping message over the websocket to Slack.
        typing: Sends a typing indicator to the specified channel.
        on: Stores and links callbacks to websocket and Slack events.
        run_on: Decorator that stores and links callbacks to websocket and Slack events.
        start: Starts an RTM Session with Slack.
        stop: Closes the websocket connection and ensures it won't reconnect.

    Example:
    ```python
    import os
    from slack import RTMClient

    @RTMClient.run_on(event="message")
    def say_hello(**payload):
        data = payload['data']
        web_client = payload['web_client']
        if 'Hello' in data['text']:
            channel_id = data['channel']
            thread_ts = data['ts']
            user = data['user']

            web_client.chat_postMessage(
                channel=channel_id,
                text=f"Hi <@{user}>!",
                thread_ts=thread_ts
            )

    slack_token = os.environ["SLACK_API_TOKEN"]
    rtm_client = RTMClient(token=slack_token)
    rtm_client.start()
    ```

    Note:
        The initial state returned when establishing an RTM connection will
        be available as the data in payload for the 'open' event. This data is not and
        will not be stored on the RTM Client.

        Any attributes or methods prefixed with _underscores are
        intended to be "private" internal use only. They may be changed or
        removed at anytime.
    """

    _callbacks: DefaultDict = collections.defaultdict(list)

    def __init__(
        self,
        *,
        token: str,
        run_async: Optional[bool] = False,
        auto_reconnect: Optional[bool] = True,
        ssl: Optional[SSLContext] = None,
        proxy: Optional[str] = None,
        timeout: Optional[int] = 30,
        base_url: Optional[str] = WebClient.BASE_URL,
        connect_method: Optional[str] = None,
        ping_interval: Optional[int] = 30,
        loop: Optional[asyncio.AbstractEventLoop] = None,
        headers: Optional[dict] = {},
    ):
        self.token = token.strip()
        self.run_async = run_async
        self.auto_reconnect = auto_reconnect
        self.ssl = ssl
        self.proxy = proxy
        self.timeout = timeout
        self.base_url = base_url
        self.connect_method = connect_method
        self.ping_interval = ping_interval
        self.headers = headers
        self._event_loop = loop or asyncio.get_event_loop()
        self._web_client = None
        self._websocket = None
        self._session = None
        self._logger = logging.getLogger(__name__)
        self._last_message_id = 0
        self._connection_attempts = 0
        self._stopped = False
        self._web_client = WebClient(
            token=self.token,
            base_url=self.base_url,  # type: ignore[arg-type]
            timeout=self.timeout,  # type: ignore[arg-type]
            ssl=self.ssl,
            proxy=self.proxy,
            run_async=self.run_async,  # type: ignore[arg-type]
            loop=self._event_loop,
            session=self._session,
            headers=self.headers,
        )

    @staticmethod
    def run_on(*, event: str):
        """A decorator to store and link a callback to an event."""

        def decorator(callback):
            RTMClient.on(event=event, callback=callback)
            return callback

        return decorator

    @classmethod
    def on(cls, *, event: str, callback: Callable):
        """Stores and links the callback(s) to the event.

        Args:
            event (str): A string that specifies a Slack or websocket event.
                e.g. 'channel_joined' or 'open'
            callback (Callable): Any object or a list of objects that can be called.
                e.g. <function say_hello at 0x101234567> or
                [<function say_hello at 0x10123>,<function say_bye at 0x10456>]

        Raises:
            SlackClientError: The specified callback is not callable.
            SlackClientError: The callback must accept keyword arguments (**kwargs).
        """
        if isinstance(callback, list):
            for cb in callback:
                cls._validate_callback(cb)
            previous_callbacks = cls._callbacks[event]
            cls._callbacks[event] = list(set(previous_callbacks + callback))
        else:
            cls._validate_callback(callback)
            cls._callbacks[event].append(callback)

    def start(self) -> Union[asyncio.Future, Any]:
        """Starts an RTM Session with Slack.

        Makes an authenticated call to Slack's RTM API to retrieve
        a websocket URL and then connects to the message server.
        As events stream-in we run any associated callbacks stored
        on the client.

        If 'auto_reconnect' is specified we
        retrieve a new url and reconnect any time the connection
        is lost unintentionally or an exception is thrown.

        Raises:
            SlackApiError: Unable to retrieve RTM URL from Slack.
        """
        # Not yet implemented: Add Windows support for graceful shutdowns.
        if os.name != "nt" and current_thread() == main_thread():
            signals = (signal.SIGHUP, signal.SIGTERM, signal.SIGINT)
            for s in signals:
                self._event_loop.add_signal_handler(s, self.stop)

        future: Future[Any] = asyncio.ensure_future(self._connect_and_read(), loop=self._event_loop)

        if self.run_async:
            return future
        return self._event_loop.run_until_complete(future)

    def stop(self):
        """Closes the websocket connection and ensures it won't reconnect.

        If your application outputs the following errors,
        call #async_stop() instead and await for the completion on your application side.

        asyncio/base_events.py:641: RuntimeWarning:
          coroutine 'ClientWebSocketResponse.close' was never awaited self._ready.clear()
        """
        self._logger.debug("The Slack RTMClient is shutting down.")
        self._stopped = True
        self._close_websocket()

    async def async_stop(self):
        """Closes the websocket connection and ensures it won't reconnect."""
        self._logger.debug("The Slack RTMClient is shutting down.")
        remaining_futures = self._close_websocket()
        for future in remaining_futures:
            await future
        self._stopped = True

    def send_over_websocket(self, *, payload: dict):
        """Sends a message to Slack over the WebSocket connection.

        Note:
            The RTM API only supports posting simple messages formatted using
            our default message formatting mode. It does not support
            attachments or other message formatting modes. For this reason
            we recommend users send messages via the Web API methods.
            e.g. web_client.chat_postMessage()

            If the message "id" is not specified in the payload, it'll be added.

        Args:
            payload (dict): The message to send over the wesocket.
            e.g.
            {
                "id": 1,
                "type": "typing",
                "channel": "C024BE91L"
            }

        Raises:
            SlackClientNotConnectedError: Websocket connection is closed.
        """
        return asyncio.ensure_future(self._send_json(payload), loop=self._event_loop)

    async def _send_json(self, payload):
        if self._websocket is None or self._event_loop is None:
            raise client_err.SlackClientNotConnectedError("Websocket connection is closed.")
        if "id" not in payload:
            payload["id"] = self._next_msg_id()

        return await self._websocket.send_json(payload)

    async def ping(self):
        """Sends a ping message over the websocket to Slack.

        Not all web browsers support the WebSocket ping spec,
        so the RTM protocol also supports ping/pong messages.

        Raises:
            SlackClientNotConnectedError: Websocket connection is closed.
        """
        payload = {"id": self._next_msg_id(), "type": "ping"}
        await self._send_json(payload=payload)

    async def typing(self, *, channel: str):
        """Sends a typing indicator to the specified channel.

        This indicates that this app is currently
        writing a message to send to a channel.

        Args:
            channel (str): The channel id. e.g. 'C024BE91L'

        Raises:
            SlackClientNotConnectedError: Websocket connection is closed.
        """
        payload = {"id": self._next_msg_id(), "type": "typing", "channel": channel}
        await self._send_json(payload=payload)

    @staticmethod
    def _validate_callback(callback):
        """Checks if the specified callback is callable and accepts a kwargs param.

        Args:
            callback (obj): Any object or a list of objects that can be called.
                e.g. <function say_hello at 0x101234567>

        Raises:
            SlackClientError: The specified callback is not callable.
            SlackClientError: The callback must accept keyword arguments (**kwargs).
        """

        cb_name = callback.__name__ if hasattr(callback, "__name__") else callback
        if not callable(callback):
            msg = "The specified callback '{}' is not callable.".format(cb_name)
            raise client_err.SlackClientError(msg)
        callback_params = inspect.signature(callback).parameters.values()
        if not any(param for param in callback_params if param.kind == param.VAR_KEYWORD):
            msg = "The callback '{}' must accept keyword arguments (**kwargs).".format(cb_name)
            raise client_err.SlackClientError(msg)

    def _next_msg_id(self):
        """Retrieves the next message id.

        When sending messages to Slack every event should
        have a unique (for that connection) positive integer ID.

        Returns:
            An integer representing the message id. e.g. 98
        """
        self._last_message_id += 1
        return self._last_message_id

    async def _connect_and_read(self):
        """Retrieves the WS url and connects to Slack's RTM API.

        Makes an authenticated call to Slack's Web API to retrieve
        a websocket URL. Then connects to the message server and
        reads event messages as they come in.

        If 'auto_reconnect' is specified we
        retrieve a new url and reconnect any time the connection
        is lost unintentionally or an exception is thrown.

        Raises:
            SlackApiError: Unable to retrieve RTM URL from Slack.
            websockets.exceptions: Errors thrown by the 'websockets' library.
        """
        while not self._stopped:
            try:
                self._connection_attempts += 1
                async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self.timeout)) as session:
                    self._session = session
                    url, data = await self._retrieve_websocket_info()
                    async with session.ws_connect(
                        url,
                        heartbeat=self.ping_interval,
                        ssl=self.ssl,
                        proxy=self.proxy,
                    ) as websocket:
                        self._logger.debug("The Websocket connection has been opened.")
                        self._websocket = websocket
                        await self._dispatch_event(event="open", data=data)
                        await self._read_messages()
                        # The websocket has been disconnected, or self._stopped is True
                        if not self._stopped and not self.auto_reconnect:
                            self._logger.warning("Not reconnecting the Websocket because auto_reconnect is False")
                            return
                        # No need to wait exponentially here, since the connection was
                        # established OK, but timed out, or was closed remotely
            except (
                client_err.SlackClientNotConnectedError,
                client_err.SlackApiError,
                # Not yet implemented: Catch websocket exceptions thrown by aiohttp.
            ) as exception:
                await self._dispatch_event(event="error", data=exception)
                error_code = exception.response.get("error", None) if hasattr(exception, "response") else None
                if (
                    self.auto_reconnect
                    and not self._stopped
                    and error_code != "invalid_auth"  # "invalid_auth" is unrecoverable
                ):
                    await self._wait_exponentially(exception)
                    continue
                self._logger.exception("The Websocket encountered an error. Closing the connection...")
                self._close_websocket()
                raise

    async def _read_messages(self):
        """Process messages received on the WebSocket connection."""
        while not self._stopped and self._websocket is not None:
            try:
                # Wait for a message to be received, but timeout after a second so that
                # we can check if the socket has been closed, or if self._stopped is
                # True
                message = await self._websocket.receive(timeout=1)
            except asyncio.TimeoutError:
                if not self._websocket.closed:
                    # We didn't receive a message within the timeout interval, but
                    # aiohttp hasn't closed the socket, so ping responses must still be
                    # returning
                    continue
                self._logger.warning(
                    "Websocket was closed (%s).",
                    self._websocket.close_code if self._websocket else "",
                )
                await self._dispatch_event(
                    event="error",
                    data=self._websocket.exception() if self._websocket else "",
                )
                self._websocket = None
                await self._dispatch_event(event="close")
                return

            if message.type == aiohttp.WSMsgType.TEXT:
                try:
                    payload = message.json()
                    event = payload.pop("type", "Unknown")
                    await self._dispatch_event(event, data=payload)
                except Exception as err:
                    data = message.data if message else message
                    self._logger.info(f"Caught a raised exception ({err}) while dispatching a TEXT message ({data})")
                    # Raised exceptions here happen in users' code and were just unhandled.
                    # As they're not intended for closing current WebSocket connection,
                    # this exception should not be propagated to higher level (#_connect_and_read()).
                    continue
            elif message.type == aiohttp.WSMsgType.ERROR:
                self._logger.error("Received an error on the websocket: %r", message)
                await self._dispatch_event(event="error", data=message)
            elif message.type in (
                aiohttp.WSMsgType.CLOSE,
                aiohttp.WSMsgType.CLOSING,
                aiohttp.WSMsgType.CLOSED,
            ):
                self._logger.warning("Websocket was closed.")
                self._websocket = None
                await self._dispatch_event(event="close")
            else:
                self._logger.debug("Received unhandled message type: %r", message)

    async def _dispatch_event(self, event, data=None):
        """Dispatches the event and executes any associated callbacks.

        Note: To prevent the app from crashing due to callback errors. We
        catch all exceptions and send all data to the logger.

        Args:
            event (str): The type of event. e.g. 'bot_added'
            data (dict): The data Slack sent. e.g.
            {
                "type": "bot_added",
                "bot": {
                    "id": "B024BE7LH",
                    "app_id": "A4H1JB4AZ",
                    "name": "hugbot"
                }
            }
        """
        if self._logger.level <= logging.DEBUG:
            self._logger.debug("Received an event: '%s' - %s", event, data)
        for callback in self._callbacks[event]:
            self._logger.debug(
                "Running %s callbacks for event: '%s'",
                len(self._callbacks[event]),
                event,
            )
            try:
                if self._stopped and event not in ["close", "error"]:
                    # Don't run callbacks if client was stopped unless they're
                    # close/error callbacks.
                    break

                if inspect.iscoroutinefunction(callback):
                    await callback(rtm_client=self, web_client=self._web_client, data=data)
                else:
                    if self.run_async is True:
                        raise client_err.SlackRequestError(
                            f'The callback "{callback.__name__}" is NOT a coroutine. '
                            "Running such with run_async=True is unsupported. "
                            "Consider adding async/await to the method "
                            "or going with run_async=False if your app is not really non-blocking."
                        )
                    payload = {
                        "rtm_client": self,
                        "web_client": self._web_client,
                        "data": data,
                    }
                    callback(**payload)
            except Exception as err:
                name = callback.__name__
                module = callback.__module__
                msg = f"When calling '#{name}()' in the '{module}' module the following error was raised: {err}"
                self._logger.error(msg)
                raise

    async def _retrieve_websocket_info(self):
        """Retrieves the WebSocket info from Slack.

        Returns:
            A tuple of websocket information.
            e.g.
            (
                "wss://...",
                {
                    "self": {"id": "U01234ABC","name": "robotoverlord"},
                    "team": {
                        "domain": "exampledomain",
                        "id": "T123450FP",
                        "name": "ExampleName"
                    }
                }
            )

        Raises:
            SlackApiError: Unable to retrieve RTM URL from Slack.
        """
        if self._web_client is None:
            self._web_client = WebClient(
                token=self.token,
                base_url=self.base_url,
                timeout=self.timeout,
                ssl=self.ssl,
                proxy=self.proxy,
                run_async=True,
                loop=self._event_loop,
                session=self._session,
                headers=self.headers,
            )
        self._logger.debug("Retrieving websocket info.")
        use_rtm_start = self.connect_method in ["rtm.start", "rtm_start"]
        if self.run_async:
            if use_rtm_start:
                resp = await self._web_client.rtm_start()
            else:
                resp = await self._web_client.rtm_connect()
        else:
            if use_rtm_start:
                resp = self._web_client.rtm_start()
            else:
                resp = self._web_client.rtm_connect()

        url = resp.get("url")
        if url is None:
            msg = "Unable to retrieve RTM URL from Slack."
            raise client_err.SlackApiError(message=msg, response=resp)
        return url, resp.data

    async def _wait_exponentially(self, exception, max_wait_time=300):
        """Wait exponentially longer for each connection attempt.

        Calculate the number of seconds to wait and then add
        a random number of milliseconds to avoid coincidental
        synchronized client retries. Wait up to the maximum amount
        of wait time specified via 'max_wait_time'. However,
        if Slack returned how long to wait use that.
        """
        if hasattr(exception, "response"):
            wait_time = exception.response.get("headers", {}).get(
                "Retry-After",
                min((2**self._connection_attempts) + random.random(), max_wait_time),
            )
            self._logger.debug("Waiting %s seconds before reconnecting.", wait_time)
            await asyncio.sleep(float(wait_time))

    def _close_websocket(self) -> Sequence[Future]:
        """Closes the websocket connection."""
        futures = []
        close_method = getattr(self._websocket, "close", None)
        if callable(close_method):
            future = asyncio.ensure_future(close_method(), loop=self._event_loop)
            futures.append(future)
        self._websocket = None
        event_f = asyncio.ensure_future(self._dispatch_event(event="close"), loop=self._event_loop)
        futures.append(event_f)
        return futures
