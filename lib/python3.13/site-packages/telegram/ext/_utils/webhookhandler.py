#!/usr/bin/env python
#
# A library that provides a Python interface to the Telegram Bot API
# Copyright (C) 2015-2026
# Leandro Toledo de Souza <devs@python-telegram-bot.org>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Lesser Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Lesser Public License for more details.
#
# You should have received a copy of the GNU Lesser Public License
# along with this program.  If not, see [http://www.gnu.org/licenses/].
# pylint: disable=missing-module-docstring
import asyncio
import json
from http import HTTPStatus
from pathlib import Path
from socket import socket
from ssl import SSLContext
from types import TracebackType
from typing import TYPE_CHECKING

# Instead of checking for ImportError here, we do that in `updater.py`, where we import from
# this module. Doing it here would be tricky, as the classes below subclass tornado classes
import tornado.web
from tornado.httpserver import HTTPServer

try:
    from tornado.netutil import bind_unix_socket

    UNIX_AVAILABLE = True
except ImportError:
    UNIX_AVAILABLE = False

from telegram import Update
from telegram._utils.logging import get_logger
from telegram.ext._extbot import ExtBot

if TYPE_CHECKING:
    from telegram import Bot

# This module is not visible to users, so we log as Updater
_LOGGER = get_logger(__name__, class_name="Updater")


class WebhookServer:
    """Thin wrapper around ``tornado.httpserver.HTTPServer``."""

    __slots__ = (
        "_http_server",
        "_server_lock",
        "_shutdown_lock",
        "is_running",
        "listen",
        "port",
        "unix",
    )

    def __init__(
        self,
        listen: str,
        port: int,
        webhook_app: "WebhookAppClass",
        ssl_ctx: SSLContext | None,
        unix: str | Path | socket | None = None,
    ):
        if unix and not UNIX_AVAILABLE:
            raise RuntimeError("This OS does not support binding unix sockets.")
        self._http_server = HTTPServer(webhook_app, ssl_options=ssl_ctx)
        self.listen = listen
        self.port = port
        self.is_running = False
        self.unix = None
        if unix and isinstance(unix, socket):
            self.unix = unix
        elif unix:
            self.unix = bind_unix_socket(str(unix))
        self._server_lock = asyncio.Lock()
        self._shutdown_lock = asyncio.Lock()

    async def serve_forever(self, ready: asyncio.Event | None = None) -> None:
        async with self._server_lock:
            if self.unix:
                self._http_server.add_socket(self.unix)
            else:
                self._http_server.listen(self.port, address=self.listen)

            self.is_running = True
            if ready is not None:
                ready.set()

            _LOGGER.debug("Webhook Server started.")

    async def shutdown(self) -> None:
        async with self._shutdown_lock:
            if not self.is_running:
                _LOGGER.debug("Webhook Server is already shut down. Returning")
                return
            self.is_running = False
            self._http_server.stop()
            await self._http_server.close_all_connections()
            _LOGGER.debug("Webhook Server stopped")


class WebhookAppClass(tornado.web.Application):
    """Application used in the Webserver"""

    def __init__(
        self,
        webhook_path: str,
        bot: "Bot",
        update_queue: asyncio.Queue,
        secret_token: str | None = None,
    ):
        self.shared_objects = {
            "bot": bot,
            "update_queue": update_queue,
            "secret_token": secret_token,
        }
        handlers = [(rf"{webhook_path}/?", TelegramHandler, self.shared_objects)]
        tornado.web.Application.__init__(self, handlers)  # type: ignore

    def log_request(self, handler: tornado.web.RequestHandler) -> None:
        """Overrides the default implementation since we have our own logging setup."""


# pylint: disable=abstract-method
class TelegramHandler(tornado.web.RequestHandler):
    """BaseHandler that processes incoming requests from Telegram"""

    __slots__ = ("bot", "secret_token", "update_queue")

    SUPPORTED_METHODS = ("POST",)  # type: ignore[assignment]

    def initialize(self, bot: "Bot", update_queue: asyncio.Queue, secret_token: str) -> None:
        """Initialize for each request - that's the interface provided by tornado"""
        # pylint: disable=attribute-defined-outside-init
        self.bot = bot
        self.update_queue = update_queue
        self.secret_token = secret_token
        if secret_token:
            _LOGGER.debug(
                "The webhook server has a secret token, expecting it in incoming requests now"
            )

    def set_default_headers(self) -> None:
        """Sets default headers"""
        self.set_header("Content-Type", 'application/json; charset="utf-8"')

    async def post(self) -> None:
        """Handle incoming POST request"""
        _LOGGER.debug("Webhook triggered")
        self._validate_post()

        json_string = self.request.body.decode()
        data = json.loads(json_string)
        self.set_status(HTTPStatus.OK)
        _LOGGER.debug("Webhook received data: %s", json_string)

        try:
            update = Update.de_json(data, self.bot)
        except Exception as exc:
            _LOGGER.critical(
                "Something went wrong processing the data received from Telegram. "
                "Received data was *not* processed! Received data was: %r",
                data,
                exc_info=exc,
            )
            raise tornado.web.HTTPError(
                HTTPStatus.BAD_REQUEST, reason="Update could not be processed"
            ) from exc

        if update:
            _LOGGER.debug(
                "Received Update with ID %d on Webhook",
                # For some reason pylint thinks update is a general TelegramObject
                update.update_id,  # pylint: disable=no-member
            )

            # handle arbitrary callback data, if necessary
            if isinstance(self.bot, ExtBot):
                self.bot.insert_callback_data(update)

            await self.update_queue.put(update)

    def _validate_post(self) -> None:
        """Only accept requests with content type JSON"""
        ct_header = self.request.headers.get("Content-Type", None)
        if ct_header != "application/json":
            raise tornado.web.HTTPError(HTTPStatus.FORBIDDEN)
        # verifying that the secret token is the one the user set when the user set one
        if self.secret_token is not None:
            token = self.request.headers.get("X-Telegram-Bot-Api-Secret-Token")
            if not token:
                _LOGGER.debug("Request did not include the secret token")
                raise tornado.web.HTTPError(
                    HTTPStatus.FORBIDDEN, reason="Request did not include the secret token"
                )
            if token != self.secret_token:
                _LOGGER.debug("Request had the wrong secret token: %s", token)
                raise tornado.web.HTTPError(
                    HTTPStatus.FORBIDDEN, reason="Request had the wrong secret token"
                )

    def log_exception(
        self,
        typ: type[BaseException] | None,
        value: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Override the default logging and instead use our custom logging."""
        _LOGGER.debug(
            "%s - %s",
            self.request.remote_ip,
            "Exception in TelegramHandler",
            exc_info=(typ, value, tb) if typ and value and tb else value,
        )
