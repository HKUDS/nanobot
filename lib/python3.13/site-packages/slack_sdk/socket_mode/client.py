import json
import logging
import time
from queue import Queue, Empty
from concurrent.futures.thread import ThreadPoolExecutor
from logging import Logger
from threading import Lock
from typing import Dict, Union, Any, Optional, List, Callable

from slack_sdk.errors import SlackApiError
from slack_sdk.socket_mode.interval_runner import IntervalRunner
from slack_sdk.socket_mode.listeners import (
    WebSocketMessageListener,
    SocketModeRequestListener,
)
from slack_sdk.socket_mode.request import SocketModeRequest
from slack_sdk.socket_mode.response import SocketModeResponse
from slack_sdk.web import WebClient


class BaseSocketModeClient:
    logger: Logger
    web_client: WebClient
    app_token: str
    wss_uri: str
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

    message_processor: IntervalRunner
    message_workers: ThreadPoolExecutor

    closed: bool
    connect_operation_lock: Lock

    def issue_new_wss_url(self) -> str:
        try:
            response = self.web_client.apps_connections_open(app_token=self.app_token)
            return response["url"]
        except SlackApiError as e:
            if e.response["error"] == "ratelimited":
                # NOTE: ratelimited errors rarely occur with this endpoint
                delay = int(e.response.headers.get("Retry-After", "30"))  # Tier1
                self.logger.info(f"Rate limited. Retrying in {delay} seconds...")
                time.sleep(delay)
                # Retry to issue a new WSS URL
                return self.issue_new_wss_url()
            else:
                # other errors
                self.logger.error(f"Failed to retrieve WSS URL: {e}")
                raise e

    def is_connected(self) -> bool:
        return False

    def connect(self) -> None:
        raise NotImplementedError()

    def disconnect(self) -> None:
        raise NotImplementedError()

    def connect_to_new_endpoint(self, force: bool = False):
        try:
            self.connect_operation_lock.acquire(blocking=True, timeout=5)
            if force or not self.is_connected():
                self.logger.info("Connecting to a new endpoint...")
                self.wss_uri = self.issue_new_wss_url()
                self.connect()
                self.logger.info("Connected to a new endpoint...")
        finally:
            self.connect_operation_lock.release()

    def close(self) -> None:
        self.closed = True
        self.disconnect()

    def send_message(self, message: str) -> None:
        raise NotImplementedError()

    def send_socket_mode_response(self, response: Union[Dict[str, Any], SocketModeResponse]) -> None:
        if isinstance(response, SocketModeResponse):
            self.send_message(json.dumps(response.to_dict()))
        else:
            self.send_message(json.dumps(response))

    def enqueue_message(self, message: str):
        self.message_queue.put(message)
        if self.logger.level <= logging.DEBUG:
            self.logger.debug(f"A new message enqueued (current queue size: {self.message_queue.qsize()})")

    def process_message(self):
        try:
            raw_message = self.message_queue.get(timeout=1)
            if self.logger.level <= logging.DEBUG:
                self.logger.debug(f"A message dequeued (current queue size: {self.message_queue.qsize()})")

            if raw_message is not None:
                message: dict = {}
                if raw_message.startswith("{"):
                    message = json.loads(raw_message)
                if message.get("type") == "disconnect":
                    self.connect_to_new_endpoint(force=True)
                else:

                    def _run_message_listeners():
                        self.run_message_listeners(message, raw_message)

                    self.message_workers.submit(_run_message_listeners)
        except Empty:
            pass

    def run_message_listeners(self, message: dict, raw_message: str) -> None:
        type, envelope_id = message.get("type"), message.get("envelope_id")
        if self.logger.level <= logging.DEBUG:
            self.logger.debug(f"Message processing started (type: {type}, envelope_id: {envelope_id})")
        try:
            # just in case, adding the same logic to reconnect here
            if message.get("type") == "disconnect":
                self.connect_to_new_endpoint(force=True)
                return

            for listener in self.message_listeners:
                try:
                    listener(self, message, raw_message)  # type: ignore[call-arg, arg-type, misc]
                except Exception as e:
                    self.logger.exception(f"Failed to run a message listener: {e}")

            if len(self.socket_mode_request_listeners) > 0:
                request = SocketModeRequest.from_dict(message)
                if request is not None:
                    for listener in self.socket_mode_request_listeners:  # type: ignore[assignment]
                        try:
                            listener(self, request)  # type: ignore[call-arg, arg-type]
                        except Exception as e:
                            self.logger.exception(f"Failed to run a request listener: {e}")
        except Exception as e:
            self.logger.exception(f"Failed to run message listeners: {e}")
        finally:
            if self.logger.level <= logging.DEBUG:
                self.logger.debug(f"Message processing completed (type: {type}, envelope_id: {envelope_id})")

    def process_messages(self) -> None:
        while not self.closed:
            try:
                self.process_message()
            except Exception as e:
                self.logger.exception(f"Failed to process a message: {e}")
