import asyncio
import json
import logging
from asyncio import Queue, Lock
from asyncio.futures import Future
from logging import Logger
from typing import Dict, Union, Any, Optional, List, Callable, Awaitable

from slack_sdk.errors import SlackApiError
from slack_sdk.socket_mode.async_listeners import (
    AsyncWebSocketMessageListener,
    AsyncSocketModeRequestListener,
)
from slack_sdk.socket_mode.request import SocketModeRequest
from slack_sdk.socket_mode.response import SocketModeResponse
from slack_sdk.web.async_client import AsyncWebClient


class AsyncBaseSocketModeClient:
    logger: Logger
    web_client: AsyncWebClient
    app_token: str
    wss_uri: str
    auto_reconnect_enabled: bool
    trace_enabled: bool
    closed: bool
    connect_operation_lock: Lock

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

    async def issue_new_wss_url(self) -> str:
        try:
            response = await self.web_client.apps_connections_open(app_token=self.app_token)
            return response["url"]
        except SlackApiError as e:
            if e.response["error"] == "ratelimited":
                # NOTE: ratelimited errors rarely occur with this endpoint
                delay = int(e.response.headers.get("Retry-After", "30"))  # Tier1
                self.logger.info(f"Rate limited. Retrying in {delay} seconds...")
                await asyncio.sleep(delay)
                # Retry to issue a new WSS URL
                return await self.issue_new_wss_url()
            else:
                # other errors
                self.logger.error(f"Failed to retrieve WSS URL: {e}")
                raise e

    async def is_connected(self) -> bool:
        return False

    async def session_id(self) -> str:
        return ""

    async def connect(self):
        raise NotImplementedError()

    async def disconnect(self):
        raise NotImplementedError()

    async def connect_to_new_endpoint(self, force: bool = False):
        session_id = await self.session_id()
        try:
            await self.connect_operation_lock.acquire()
            if self.trace_enabled:
                self.logger.debug(f"For reconnection, the connect_operation_lock was acquired (session: {session_id})")
            if force or not await self.is_connected():
                self.wss_uri = await self.issue_new_wss_url()
                await self.connect()
        finally:
            if self.connect_operation_lock.locked() is True:
                self.connect_operation_lock.release()
                if self.trace_enabled:
                    self.logger.debug(f"The connect_operation_lock for reconnection was released (session: {session_id})")

    async def close(self):
        self.closed = True
        await self.disconnect()

    async def send_message(self, message: str):
        raise NotImplementedError()

    async def send_socket_mode_response(self, response: Union[Dict[str, Any], SocketModeResponse]):
        if isinstance(response, SocketModeResponse):
            await self.send_message(json.dumps(response.to_dict()))
        else:
            await self.send_message(json.dumps(response))

    async def enqueue_message(self, message: str):
        await self.message_queue.put(message)
        if self.logger.level <= logging.DEBUG:
            queue_size = self.message_queue.qsize()
            session_id = await self.session_id()
            self.logger.debug(f"A new message enqueued (current queue size: {queue_size}, session: {session_id})")

    async def process_messages(self):
        session_id = await self.session_id()
        try:
            while not self.closed:
                try:
                    await self.process_message()
                except asyncio.CancelledError:
                    # if self.closed is True, the connection is already closed
                    # In this case, we can ignore the exception here
                    if not self.closed:
                        raise
                except Exception as e:
                    self.logger.exception(f"Failed to process a message: {e}, session: {session_id}")
        except asyncio.CancelledError:
            if self.trace_enabled:
                self.logger.debug(f"The running process_messages task for {session_id} is now cancelled")
            raise

    async def process_message(self):
        raw_message = await self.message_queue.get()
        if raw_message is not None:
            message: dict = {}
            if raw_message.startswith("{"):
                message = json.loads(raw_message)
            _: Future[None] = asyncio.ensure_future(self.run_message_listeners(message, raw_message))

    async def run_message_listeners(self, message: dict, raw_message: str) -> None:
        session_id = await self.session_id()
        type, envelope_id = message.get("type"), message.get("envelope_id")
        if self.logger.level <= logging.DEBUG:
            self.logger.debug(
                f"Message processing started (type: {type}, envelope_id: {envelope_id}, session: {session_id})"
            )
        try:
            if message.get("type") == "disconnect":
                await self.connect_to_new_endpoint(force=True)
                return

            for listener in self.message_listeners:
                try:
                    await listener(self, message, raw_message)  # type: ignore[call-arg, arg-type, misc]
                except Exception as e:
                    self.logger.exception(f"Failed to run a message listener: {e}, session: {session_id}")

            if len(self.socket_mode_request_listeners) > 0:
                request = SocketModeRequest.from_dict(message)
                if request is not None:
                    for listener in self.socket_mode_request_listeners:  # type: ignore[assignment]
                        try:
                            await listener(self, request)  # type: ignore[call-arg, arg-type]
                        except Exception as e:
                            self.logger.exception(f"Failed to run a request listener: {e}, session: {session_id}")
        except Exception as e:
            self.logger.exception(f"Failed to run message listeners: {e}, session: {session_id}")
        finally:
            if self.logger.level <= logging.DEBUG:
                self.logger.debug(
                    f"Message processing completed ("
                    f"type: {type}, "
                    f"envelope_id: {envelope_id}, "
                    f"session: {session_id})"
                )
