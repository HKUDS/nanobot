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
"""This module contains the Builder classes for the telegram.ext module."""

from asyncio import Queue
from collections.abc import Callable, Collection, Coroutine
from pathlib import Path
from typing import TYPE_CHECKING, Any, Generic, TypeVar

import httpx

from telegram._bot import Bot
from telegram._utils.defaultvalue import DEFAULT_FALSE, DEFAULT_NONE, DefaultValue
from telegram._utils.types import (
    BaseUrl,
    DVInput,
    DVType,
    FilePathInput,
    HTTPVersion,
    ODVInput,
    SocketOpt,
)
from telegram.ext._application import Application
from telegram.ext._baseupdateprocessor import BaseUpdateProcessor, SimpleUpdateProcessor
from telegram.ext._contexttypes import ContextTypes
from telegram.ext._extbot import ExtBot
from telegram.ext._jobqueue import JobQueue
from telegram.ext._updater import Updater
from telegram.ext._utils.types import BD, BT, CCT, CD, JQ, UD
from telegram.request import BaseRequest
from telegram.request._httpxrequest import HTTPXRequest

if TYPE_CHECKING:
    from telegram import Update
    from telegram.ext import BasePersistence, BaseRateLimiter, CallbackContext, Defaults
    from telegram.ext._utils.types import RLARGS

# Type hinting is a bit complicated here because we try to get to a sane level of
# leveraging generics and therefore need a number of type variables.
# 'In' stands for input - used in parameters of methods below
# pylint: disable=invalid-name
InBT = TypeVar("InBT", bound=Bot)
InJQ = TypeVar("InJQ", bound=None | JobQueue)
InCCT = TypeVar("InCCT", bound="CallbackContext")
InUD = TypeVar("InUD")
InCD = TypeVar("InCD")
InBD = TypeVar("InBD")
BuilderType = TypeVar("BuilderType", bound="ApplicationBuilder")


_BOT_CHECKS = [
    ("request", "request instance"),
    ("get_updates_request", "get_updates_request instance"),
    ("connection_pool_size", "connection_pool_size"),
    ("proxy", "proxy"),
    ("socket_options", "socket_options"),
    ("pool_timeout", "pool_timeout"),
    ("connect_timeout", "connect_timeout"),
    ("read_timeout", "read_timeout"),
    ("write_timeout", "write_timeout"),
    ("media_write_timeout", "media_write_timeout"),
    ("http_version", "http_version"),
    ("get_updates_connection_pool_size", "get_updates_connection_pool_size"),
    ("get_updates_proxy", "get_updates_proxy"),
    ("get_updates_socket_options", "get_updates_socket_options"),
    ("get_updates_pool_timeout", "get_updates_pool_timeout"),
    ("get_updates_connect_timeout", "get_updates_connect_timeout"),
    ("get_updates_read_timeout", "get_updates_read_timeout"),
    ("get_updates_write_timeout", "get_updates_write_timeout"),
    ("get_updates_http_version", "get_updates_http_version"),
    ("base_file_url", "base_file_url"),
    ("base_url", "base_url"),
    ("token", "token"),
    ("defaults", "defaults"),
    ("arbitrary_callback_data", "arbitrary_callback_data"),
    ("private_key", "private_key"),
    ("rate_limiter", "rate_limiter instance"),
    ("local_mode", "local_mode setting"),
]

_TWO_ARGS_REQ = "The parameter `{}` may only be set, if no {} was set."


class ApplicationBuilder(Generic[BT, CCT, UD, CD, BD, JQ]):
    """This class serves as initializer for :class:`telegram.ext.Application` via the so called
    `builder pattern`_. To build a :class:`telegram.ext.Application`, one first initializes an
    instance of this class. Arguments for the :class:`telegram.ext.Application` to build are then
    added by subsequently calling the methods of the builder. Finally, the
    :class:`telegram.ext.Application` is built by calling :meth:`build`. In the simplest case this
    can look like the following example.

    Example:
        .. code:: python

            application = ApplicationBuilder().token("TOKEN").build()

    Please see the description of the individual methods for information on which arguments can be
    set and what the defaults are when not called. When no default is mentioned, the argument will
    not be used by default.

    Note:
        * Some arguments are mutually exclusive. E.g. after calling :meth:`token`, you can't set
          a custom bot with :meth:`bot` and vice versa.
        * Unless a custom :class:`telegram.Bot` instance is set via :meth:`bot`, :meth:`build` will
          use :class:`telegram.ext.ExtBot` for the bot.

    .. seealso:: :wiki:`Your First Bot <Extensions---Your-first-Bot>`,
        :wiki:`Builder Pattern <Builder-Pattern>`

    .. versionchanged:: 22.0
        Removed deprecated methods ``proxy_url`` and ``get_updates_proxy_url``.

    .. _`builder pattern`: https://en.wikipedia.org/wiki/Builder_pattern
    """

    __slots__ = (
        "_application_class",
        "_application_kwargs",
        "_arbitrary_callback_data",
        "_base_file_url",
        "_base_url",
        "_bot",
        "_connect_timeout",
        "_connection_pool_size",
        "_context_types",
        "_defaults",
        "_get_updates_connect_timeout",
        "_get_updates_connection_pool_size",
        "_get_updates_http_version",
        "_get_updates_pool_timeout",
        "_get_updates_proxy",
        "_get_updates_read_timeout",
        "_get_updates_request",
        "_get_updates_socket_options",
        "_get_updates_write_timeout",
        "_http_version",
        "_job_queue",
        "_local_mode",
        "_media_write_timeout",
        "_persistence",
        "_pool_timeout",
        "_post_init",
        "_post_shutdown",
        "_post_stop",
        "_private_key",
        "_private_key_password",
        "_proxy",
        "_rate_limiter",
        "_read_timeout",
        "_request",
        "_socket_options",
        "_token",
        "_update_processor",
        "_update_queue",
        "_updater",
        "_write_timeout",
    )

    def __init__(self: "InitApplicationBuilder"):
        self._token: DVType[str] = DefaultValue("")
        self._base_url: DVType[BaseUrl] = DefaultValue("https://api.telegram.org/bot")
        self._base_file_url: DVType[BaseUrl] = DefaultValue("https://api.telegram.org/file/bot")
        self._connection_pool_size: DVInput[int] = DEFAULT_NONE
        self._proxy: DVInput[str | httpx.Proxy | httpx.URL] = DEFAULT_NONE
        self._socket_options: DVInput[Collection[SocketOpt]] = DEFAULT_NONE
        self._connect_timeout: ODVInput[float] = DEFAULT_NONE
        self._read_timeout: ODVInput[float] = DEFAULT_NONE
        self._write_timeout: ODVInput[float] = DEFAULT_NONE
        self._media_write_timeout: ODVInput[float] = DEFAULT_NONE
        self._pool_timeout: ODVInput[float] = DEFAULT_NONE
        self._request: DVInput[BaseRequest] = DEFAULT_NONE
        self._get_updates_connection_pool_size: DVInput[int] = DEFAULT_NONE
        self._get_updates_proxy: DVInput[str | httpx.Proxy | httpx.URL] = DEFAULT_NONE
        self._get_updates_socket_options: DVInput[Collection[SocketOpt]] = DEFAULT_NONE
        self._get_updates_connect_timeout: ODVInput[float] = DEFAULT_NONE
        self._get_updates_read_timeout: ODVInput[float] = DEFAULT_NONE
        self._get_updates_write_timeout: ODVInput[float] = DEFAULT_NONE
        self._get_updates_pool_timeout: ODVInput[float] = DEFAULT_NONE
        self._get_updates_request: DVInput[BaseRequest] = DEFAULT_NONE
        self._get_updates_http_version: DVInput[str] = DefaultValue("1.1")
        self._private_key: ODVInput[bytes] = DEFAULT_NONE
        self._private_key_password: ODVInput[bytes] = DEFAULT_NONE
        self._defaults: ODVInput[Defaults] = DEFAULT_NONE
        self._arbitrary_callback_data: DefaultValue[bool] | int = DEFAULT_FALSE
        self._local_mode: DVType[bool] = DEFAULT_FALSE
        self._bot: DVInput[Bot] = DEFAULT_NONE
        self._update_queue: DVType[Queue[Update | object]] = DefaultValue(Queue())

        try:
            self._job_queue: ODVInput[JobQueue] = DefaultValue(JobQueue())
        except RuntimeError as exc:
            if "PTB must be installed via" not in str(exc):
                raise
            self._job_queue = DEFAULT_NONE

        self._persistence: ODVInput[BasePersistence] = DEFAULT_NONE
        self._context_types: DVType[ContextTypes] = DefaultValue(ContextTypes())
        self._application_class: DVType[type[Application]] = DefaultValue(Application)
        self._application_kwargs: dict[str, object] = {}
        self._update_processor: BaseUpdateProcessor = SimpleUpdateProcessor(
            max_concurrent_updates=1
        )
        self._updater: ODVInput[Updater] = DEFAULT_NONE
        self._post_init: Callable[[Application], Coroutine[Any, Any, None]] | None = None
        self._post_shutdown: Callable[[Application], Coroutine[Any, Any, None]] | None = None
        self._post_stop: Callable[[Application], Coroutine[Any, Any, None]] | None = None
        self._rate_limiter: ODVInput[BaseRateLimiter] = DEFAULT_NONE
        self._http_version: DVInput[str] = DefaultValue("1.1")

    def _build_request(self, get_updates: bool) -> BaseRequest:
        prefix = "_get_updates_" if get_updates else "_"
        if not isinstance(getattr(self, f"{prefix}request"), DefaultValue):
            return getattr(self, f"{prefix}request")

        proxy = DefaultValue.get_value(getattr(self, f"{prefix}proxy"))
        socket_options = DefaultValue.get_value(getattr(self, f"{prefix}socket_options"))
        if get_updates:
            connection_pool_size = (
                DefaultValue.get_value(getattr(self, f"{prefix}connection_pool_size")) or 1
            )
        else:
            connection_pool_size = (
                DefaultValue.get_value(getattr(self, f"{prefix}connection_pool_size")) or 256
            )

        timeouts = {
            "connect_timeout": getattr(self, f"{prefix}connect_timeout"),
            "read_timeout": getattr(self, f"{prefix}read_timeout"),
            "write_timeout": getattr(self, f"{prefix}write_timeout"),
            "pool_timeout": getattr(self, f"{prefix}pool_timeout"),
        }

        if not get_updates:
            timeouts["media_write_timeout"] = self._media_write_timeout

        # Get timeouts that were actually set-
        effective_timeouts = {
            key: value for key, value in timeouts.items() if not isinstance(value, DefaultValue)
        }

        http_version = DefaultValue.get_value(getattr(self, f"{prefix}http_version")) or "1.1"

        return HTTPXRequest(
            connection_pool_size=connection_pool_size,
            proxy=proxy,
            http_version=http_version,  # type: ignore[arg-type]
            socket_options=socket_options,
            **effective_timeouts,
        )

    def _build_ext_bot(self) -> ExtBot:
        if isinstance(self._token, DefaultValue):
            raise RuntimeError("No bot token was set.")

        return ExtBot(
            token=self._token,
            base_url=DefaultValue.get_value(self._base_url),
            base_file_url=DefaultValue.get_value(self._base_file_url),
            private_key=DefaultValue.get_value(self._private_key),
            private_key_password=DefaultValue.get_value(self._private_key_password),
            defaults=DefaultValue.get_value(self._defaults),
            arbitrary_callback_data=DefaultValue.get_value(self._arbitrary_callback_data),
            request=self._build_request(get_updates=False),
            get_updates_request=self._build_request(get_updates=True),
            rate_limiter=DefaultValue.get_value(self._rate_limiter),
            local_mode=DefaultValue.get_value(self._local_mode),
        )

    def _bot_check(self, name: str) -> None:
        if self._bot is not DEFAULT_NONE:
            raise RuntimeError(_TWO_ARGS_REQ.format(name, "bot instance"))

    def _updater_check(self, name: str) -> None:
        if self._updater not in (DEFAULT_NONE, None):
            raise RuntimeError(_TWO_ARGS_REQ.format(name, "updater"))

    def build(
        self: "ApplicationBuilder[BT, CCT, UD, CD, BD, JQ]",
    ) -> Application[BT, CCT, UD, CD, BD, JQ]:
        """Builds a :class:`telegram.ext.Application` with the provided arguments.

        Calls :meth:`telegram.ext.JobQueue.set_application` and
        :meth:`telegram.ext.BasePersistence.set_bot` if appropriate.

        Returns:
            :class:`telegram.ext.Application`
        """
        job_queue = DefaultValue.get_value(self._job_queue)
        persistence = DefaultValue.get_value(self._persistence)
        # If user didn't set updater
        if isinstance(self._updater, DefaultValue) or self._updater is None:
            if isinstance(self._bot, DefaultValue):  # and didn't set a bot
                bot: Bot = self._build_ext_bot()  # build a bot
            else:
                bot = self._bot
            # now also build an updater/update_queue for them
            update_queue = DefaultValue.get_value(self._update_queue)

            if self._updater is None:
                updater = None
            else:
                updater = Updater(bot=bot, update_queue=update_queue)
        else:  # if they set an updater, get all necessary attributes for Application from Updater:
            updater = self._updater
            bot = self._updater.bot
            update_queue = self._updater.update_queue

        application: Application[BT, CCT, UD, CD, BD, JQ] = DefaultValue.get_value(
            self._application_class
        )(
            bot=bot,
            update_queue=update_queue,
            updater=updater,
            update_processor=self._update_processor,
            job_queue=job_queue,
            persistence=persistence,
            context_types=DefaultValue.get_value(self._context_types),
            post_init=self._post_init,
            post_shutdown=self._post_shutdown,
            post_stop=self._post_stop,
            **self._application_kwargs,  # For custom Application subclasses
        )

        if job_queue is not None:
            job_queue.set_application(application)  # type: ignore[arg-type]

        if persistence is not None:
            # This raises an exception if persistence.store_data.callback_data is True
            # but self.bot is not an instance of ExtBot - so no need to check that later on
            persistence.set_bot(bot)

        return application

    def application_class(
        self: BuilderType,
        application_class: type[Application[Any, Any, Any, Any, Any, Any]],
        kwargs: dict[str, object] | None = None,
    ) -> BuilderType:
        """Sets a custom subclass instead of :class:`telegram.ext.Application`. The
        subclass's ``__init__`` should look like this

        .. code:: python

            def __init__(self, custom_arg_1, custom_arg_2, ..., **kwargs):
                super().__init__(**kwargs)
                self.custom_arg_1 = custom_arg_1
                self.custom_arg_2 = custom_arg_2

        Args:
            application_class (:obj:`type`): A subclass of :class:`telegram.ext.Application`
            kwargs (dict[:obj:`str`, :obj:`object`], optional): Keyword arguments for the
                initialization. Defaults to an empty dict.

        Returns:
            :class:`ApplicationBuilder`: The same builder with the updated argument.
        """
        self._application_class = application_class
        self._application_kwargs = kwargs or {}
        return self

    def token(self: BuilderType, token: str) -> BuilderType:
        """Sets the token for :attr:`telegram.ext.Application.bot`.

        Args:
            token (:obj:`str`): The token.

        Returns:
            :class:`ApplicationBuilder`: The same builder with the updated argument.
        """
        self._bot_check("token")
        self._updater_check("token")
        self._token = token
        return self

    def base_url(self: BuilderType, base_url: BaseUrl) -> BuilderType:
        """Sets the base URL for :attr:`telegram.ext.Application.bot`. If not called,
        will default to ``'https://api.telegram.org/bot'``.

        .. seealso:: :paramref:`telegram.Bot.base_url`,
            :wiki:`Local Bot API Server <Local-Bot-API-Server>`, :meth:`base_file_url`

        .. versionchanged:: 21.11
           Supports callable input and string formatting.

        Args:
            base_url (:obj:`str` | Callable[[:obj:`str`], :obj:`str`]): The URL or
                input for the URL as accepted by :paramref:`telegram.Bot.base_url`.

        Returns:
            :class:`ApplicationBuilder`: The same builder with the updated argument.
        """
        self._bot_check("base_url")
        self._updater_check("base_url")
        self._base_url = base_url
        return self

    def base_file_url(self: BuilderType, base_file_url: BaseUrl) -> BuilderType:
        """Sets the base file URL for :attr:`telegram.ext.Application.bot`. If not
        called, will default to ``'https://api.telegram.org/file/bot'``.

        .. seealso:: :paramref:`telegram.Bot.base_file_url`,
            :wiki:`Local Bot API Server <Local-Bot-API-Server>`, :meth:`base_url`

        .. versionchanged:: 21.11
           Supports callable input and string formatting.

        Args:
            base_file_url (:obj:`str` | Callable[[:obj:`str`], :obj:`str`]): The URL or
                input for the URL as accepted by :paramref:`telegram.Bot.base_file_url`.

        Returns:
            :class:`ApplicationBuilder`: The same builder with the updated argument.
        """
        self._bot_check("base_file_url")
        self._updater_check("base_file_url")
        self._base_file_url = base_file_url
        return self

    def _request_check(self, get_updates: bool) -> None:
        prefix = "get_updates_" if get_updates else ""
        name = prefix + "request"

        timeouts = ["connect_timeout", "read_timeout", "write_timeout", "pool_timeout"]
        if not get_updates:
            timeouts.append("media_write_timeout")

        # Code below tests if it's okay to set a Request object. Only okay if no other request args
        # or instances containing a Request were set previously
        for attr in timeouts:
            if not isinstance(getattr(self, f"_{prefix}{attr}"), DefaultValue):
                raise RuntimeError(_TWO_ARGS_REQ.format(name, attr))

        if not isinstance(getattr(self, f"_{prefix}connection_pool_size"), DefaultValue):
            raise RuntimeError(_TWO_ARGS_REQ.format(name, "connection_pool_size"))

        if not isinstance(getattr(self, f"_{prefix}proxy"), DefaultValue):
            raise RuntimeError(_TWO_ARGS_REQ.format(name, "proxy"))

        if not isinstance(getattr(self, f"_{prefix}socket_options"), DefaultValue):
            raise RuntimeError(_TWO_ARGS_REQ.format(name, "socket_options"))

        if not isinstance(getattr(self, f"_{prefix}http_version"), DefaultValue):
            raise RuntimeError(_TWO_ARGS_REQ.format(name, "http_version"))

        self._bot_check(name)

        if self._updater not in (DEFAULT_NONE, None):
            raise RuntimeError(_TWO_ARGS_REQ.format(name, "updater instance"))

    def _request_param_check(self, name: str, get_updates: bool) -> None:
        if get_updates and self._get_updates_request is not DEFAULT_NONE:
            raise RuntimeError(  # disallow request args for get_updates if Request for that is set
                _TWO_ARGS_REQ.format(f"get_updates_{name}", "get_updates_request instance")
            )
        if self._request is not DEFAULT_NONE:  # disallow request args if request is set
            raise RuntimeError(_TWO_ARGS_REQ.format(name, "request instance"))

        if self._bot is not DEFAULT_NONE:  # disallow request args if bot is set (has Request)
            raise RuntimeError(
                _TWO_ARGS_REQ.format(
                    f"get_updates_{name}" if get_updates else name, "bot instance"
                )
            )

        if self._updater not in (DEFAULT_NONE, None):  # disallow request args for updater(has bot)
            raise RuntimeError(
                _TWO_ARGS_REQ.format(f"get_updates_{name}" if get_updates else name, "updater")
            )

    def request(self: BuilderType, request: BaseRequest) -> BuilderType:
        """Sets a :class:`telegram.request.BaseRequest` instance for the
        :paramref:`telegram.Bot.request` parameter of :attr:`telegram.ext.Application.bot`.

        .. seealso:: :meth:`get_updates_request`

        Args:
            request (:class:`telegram.request.BaseRequest`): The request instance.

        Returns:
            :class:`ApplicationBuilder`: The same builder with the updated argument.
        """
        self._request_check(get_updates=False)
        self._request = request
        return self

    def connection_pool_size(self: BuilderType, connection_pool_size: int) -> BuilderType:
        """Sets the size of the connection pool for the
        :paramref:`~telegram.request.HTTPXRequest.connection_pool_size` parameter of
        :attr:`telegram.Bot.request`. Defaults to ``256``.

        .. include:: inclusions/pool_size_tip.rst

        .. seealso:: :meth:`get_updates_connection_pool_size`

        Args:
            connection_pool_size (:obj:`int`): The size of the connection pool.

        Returns:
            :class:`ApplicationBuilder`: The same builder with the updated argument.
        """
        self._request_param_check(name="connection_pool_size", get_updates=False)
        self._connection_pool_size = connection_pool_size
        return self

    def proxy(self: BuilderType, proxy: str | httpx.Proxy | httpx.URL) -> BuilderType:
        """Sets the proxy for the :paramref:`~telegram.request.HTTPXRequest.proxy`
        parameter of :attr:`telegram.Bot.request`. Defaults to :obj:`None`.

        .. seealso:: :meth:`get_updates_proxy`

        .. versionadded:: 20.7

        Args:
            proxy (:obj:`str` | ``httpx.Proxy`` | ``httpx.URL``): The URL to a proxy
                server, a ``httpx.Proxy`` object or a ``httpx.URL`` object. See
                :paramref:`telegram.request.HTTPXRequest.proxy` for more information.

        Returns:
            :class:`ApplicationBuilder`: The same builder with the updated argument.
        """
        self._request_param_check(name="proxy", get_updates=False)
        self._proxy = proxy
        return self

    def socket_options(self: BuilderType, socket_options: Collection[SocketOpt]) -> BuilderType:
        """Sets the options for the :paramref:`~telegram.request.HTTPXRequest.socket_options`
        parameter of :attr:`telegram.Bot.request`. Defaults to :obj:`None`.

        .. seealso:: :meth:`get_updates_socket_options`

        .. versionadded:: 20.7

        Args:
            socket_options (Collection[:obj:`tuple`], optional): Socket options. See
                :paramref:`telegram.request.HTTPXRequest.socket_options` for more information.

        Returns:
            :class:`ApplicationBuilder`: The same builder with the updated argument.
        """
        self._request_param_check(name="socket_options", get_updates=False)
        self._socket_options = socket_options
        return self

    def connect_timeout(self: BuilderType, connect_timeout: float | None) -> BuilderType:
        """Sets the connection attempt timeout for the
        :paramref:`~telegram.request.HTTPXRequest.connect_timeout` parameter of
        :attr:`telegram.Bot.request`. Defaults to ``5.0``.

        .. seealso:: :meth:`get_updates_connect_timeout`

        Args:
            connect_timeout (:obj:`float`): See
                :paramref:`telegram.request.HTTPXRequest.connect_timeout` for more information.

        Returns:
            :class:`ApplicationBuilder`: The same builder with the updated argument.
        """
        self._request_param_check(name="connect_timeout", get_updates=False)
        self._connect_timeout = connect_timeout
        return self

    def read_timeout(self: BuilderType, read_timeout: float | None) -> BuilderType:
        """Sets the waiting timeout for the
        :paramref:`~telegram.request.HTTPXRequest.read_timeout` parameter of
        :attr:`telegram.Bot.request`. Defaults to ``5.0``.

        .. seealso:: :meth:`get_updates_read_timeout`

        Args:
            read_timeout (:obj:`float`): See
                :paramref:`telegram.request.HTTPXRequest.read_timeout` for more information.

        Returns:
            :class:`ApplicationBuilder`: The same builder with the updated argument.
        """
        self._request_param_check(name="read_timeout", get_updates=False)
        self._read_timeout = read_timeout
        return self

    def write_timeout(self: BuilderType, write_timeout: float | None) -> BuilderType:
        """Sets the write operation timeout for the
        :paramref:`~telegram.request.HTTPXRequest.write_timeout` parameter of
        :attr:`telegram.Bot.request`. Defaults to ``5.0``.

        .. seealso:: :meth:`get_updates_write_timeout`

        Args:
            write_timeout (:obj:`float`): See
                :paramref:`telegram.request.HTTPXRequest.write_timeout` for more information.

        Returns:
            :class:`ApplicationBuilder`: The same builder with the updated argument.
        """
        self._request_param_check(name="write_timeout", get_updates=False)
        self._write_timeout = write_timeout
        return self

    def media_write_timeout(self: BuilderType, media_write_timeout: float | None) -> BuilderType:
        """Sets the media write operation timeout for the
        :paramref:`~telegram.request.HTTPXRequest.media_write_timeout` parameter of
        :attr:`telegram.Bot.request`. Defaults to ``20``.

        .. versionadded:: 21.0

        Args:
            media_write_timeout (:obj:`float`): See
                :paramref:`telegram.request.HTTPXRequest.media_write_timeout` for more information.

        Returns:
            :class:`ApplicationBuilder`: The same builder with the updated argument.
        """
        self._request_param_check(name="media_write_timeout", get_updates=False)
        self._media_write_timeout = media_write_timeout
        return self

    def pool_timeout(self: BuilderType, pool_timeout: float | None) -> BuilderType:
        """Sets the connection pool's connection freeing timeout for the
        :paramref:`~telegram.request.HTTPXRequest.pool_timeout` parameter of
        :attr:`telegram.Bot.request`. Defaults to ``1.0``.

        .. include:: inclusions/pool_size_tip.rst

        .. seealso:: :meth:`get_updates_pool_timeout`

        Args:
            pool_timeout (:obj:`float`): See
                :paramref:`telegram.request.HTTPXRequest.pool_timeout` for more information.

        Returns:
            :class:`ApplicationBuilder`: The same builder with the updated argument.
        """
        self._request_param_check(name="pool_timeout", get_updates=False)
        self._pool_timeout = pool_timeout
        return self

    def http_version(self: BuilderType, http_version: HTTPVersion) -> BuilderType:
        """Sets the HTTP protocol version which is used for the
        :paramref:`~telegram.request.HTTPXRequest.http_version` parameter of
        :attr:`telegram.Bot.request`. By default, HTTP/1.1 is used.

        .. seealso:: :meth:`get_updates_http_version`

        Note:
            Users have observed stability issues with HTTP/2, which happen due to how the `h2
            library handles <https://github.com/python-hyper/h2/issues/1181>`_ cancellations of
            keepalive connections. See `#3556 <https://github.com/python-telegram-bot/
            python-telegram-bot/issues/3556>`_ for a discussion.

            If you want to use HTTP/2, you must install PTB with the optional requirement
            ``http2``, i.e.

            .. code-block:: bash

               pip install "python-telegram-bot[http2]"

            Keep in mind that the HTTP/1.1 implementation may be considered the `"more
            robust option at this time" <https://www.python-httpx.org/http2#enabling-http2>`_.

        .. versionadded:: 20.1
        .. versionchanged:: 20.2
            Reset the default version to 1.1.

        Args:
            http_version (:obj:`str`): Pass ``"2"`` or ``"2.0"`` if you'd like to use HTTP/2 for
                making requests to Telegram. Defaults to ``"1.1"``, in which case HTTP/1.1 is used.

                .. versionchanged:: 20.5
                    Accept ``"2"`` as a valid value.

        Returns:
            :class:`ApplicationBuilder`: The same builder with the updated argument.
        """
        self._request_param_check(name="http_version", get_updates=False)
        self._http_version = http_version
        return self

    def get_updates_request(self: BuilderType, get_updates_request: BaseRequest) -> BuilderType:
        """Sets a :class:`telegram.request.BaseRequest` instance for the
        :paramref:`~telegram.Bot.get_updates_request` parameter of
        :attr:`telegram.ext.Application.bot`.

        .. seealso:: :meth:`request`

        Args:
            get_updates_request (:class:`telegram.request.BaseRequest`): The request instance.

        Returns:
            :class:`ApplicationBuilder`: The same builder with the updated argument.
        """
        self._request_check(get_updates=True)
        self._get_updates_request = get_updates_request
        return self

    def get_updates_connection_pool_size(
        self: BuilderType, get_updates_connection_pool_size: int
    ) -> BuilderType:
        """Sets the size of the connection pool for the
        :paramref:`telegram.request.HTTPXRequest.connection_pool_size` parameter which is used
        for the :meth:`telegram.Bot.get_updates` request. Defaults to ``1``.

        .. seealso:: :meth:`connection_pool_size`

        Args:
            get_updates_connection_pool_size (:obj:`int`): The size of the connection pool.

        Returns:
            :class:`ApplicationBuilder`: The same builder with the updated argument.
        """
        self._request_param_check(name="connection_pool_size", get_updates=True)
        self._get_updates_connection_pool_size = get_updates_connection_pool_size
        return self

    def get_updates_proxy(
        self: BuilderType, get_updates_proxy: str | httpx.Proxy | httpx.URL
    ) -> BuilderType:
        """Sets the proxy for the :paramref:`telegram.request.HTTPXRequest.proxy`
        parameter which is used for :meth:`telegram.Bot.get_updates`. Defaults to :obj:`None`.

        .. seealso:: :meth:`proxy`

        .. versionadded:: 20.7

        Args:
            proxy (:obj:`str` | ``httpx.Proxy`` | ``httpx.URL``): The URL to a proxy server,
                a ``httpx.Proxy`` object or a ``httpx.URL`` object. See
                :paramref:`telegram.request.HTTPXRequest.proxy` for more information.

        Returns:
            :class:`ApplicationBuilder`: The same builder with the updated argument.
        """
        self._request_param_check(name="proxy", get_updates=True)
        self._get_updates_proxy = get_updates_proxy
        return self

    def get_updates_socket_options(
        self: BuilderType, get_updates_socket_options: Collection[SocketOpt]
    ) -> BuilderType:
        """Sets the options for the :paramref:`~telegram.request.HTTPXRequest.socket_options`
        parameter of :paramref:`telegram.Bot.get_updates_request`. Defaults to :obj:`None`.

        .. seealso:: :meth:`socket_options`

        .. versionadded:: 20.7

        Args:
            get_updates_socket_options (Collection[:obj:`tuple`], optional): Socket options. See
                :paramref:`telegram.request.HTTPXRequest.socket_options` for more information.

        Returns:
            :class:`ApplicationBuilder`: The same builder with the updated argument.
        """
        self._request_param_check(name="socket_options", get_updates=True)
        self._get_updates_socket_options = get_updates_socket_options
        return self

    def get_updates_connect_timeout(
        self: BuilderType, get_updates_connect_timeout: float | None
    ) -> BuilderType:
        """Sets the connection attempt timeout for the
        :paramref:`telegram.request.HTTPXRequest.connect_timeout` parameter which is used for
        the :meth:`telegram.Bot.get_updates` request. Defaults to ``5.0``.

        .. seealso:: :meth:`connect_timeout`

        Args:
            get_updates_connect_timeout (:obj:`float`): See
                :paramref:`telegram.request.HTTPXRequest.connect_timeout` for more information.

        Returns:
            :class:`ApplicationBuilder`: The same builder with the updated argument.
        """
        self._request_param_check(name="connect_timeout", get_updates=True)
        self._get_updates_connect_timeout = get_updates_connect_timeout
        return self

    def get_updates_read_timeout(
        self: BuilderType, get_updates_read_timeout: float | None
    ) -> BuilderType:
        """Sets the waiting timeout for the
        :paramref:`telegram.request.HTTPXRequest.read_timeout` parameter which is used for the
        :meth:`telegram.Bot.get_updates` request. Defaults to ``5.0``.

        .. seealso:: :meth:`read_timeout`

        Args:
            get_updates_read_timeout (:obj:`float`): See
                :paramref:`telegram.request.HTTPXRequest.read_timeout` for more information.

        Returns:
            :class:`ApplicationBuilder`: The same builder with the updated argument.
        """
        self._request_param_check(name="read_timeout", get_updates=True)
        self._get_updates_read_timeout = get_updates_read_timeout
        return self

    def get_updates_write_timeout(
        self: BuilderType, get_updates_write_timeout: float | None
    ) -> BuilderType:
        """Sets the write operation timeout for the
        :paramref:`telegram.request.HTTPXRequest.write_timeout` parameter which is used for
        the :meth:`telegram.Bot.get_updates` request. Defaults to ``5.0``.

        .. seealso:: :meth:`write_timeout`

        Args:
            get_updates_write_timeout (:obj:`float`): See
                :paramref:`telegram.request.HTTPXRequest.write_timeout` for more information.

        Returns:
            :class:`ApplicationBuilder`: The same builder with the updated argument.
        """
        self._request_param_check(name="write_timeout", get_updates=True)
        self._get_updates_write_timeout = get_updates_write_timeout
        return self

    def get_updates_pool_timeout(
        self: BuilderType, get_updates_pool_timeout: float | None
    ) -> BuilderType:
        """Sets the connection pool's connection freeing timeout for the
        :paramref:`~telegram.request.HTTPXRequest.pool_timeout` parameter which is used for the
        :meth:`telegram.Bot.get_updates` request. Defaults to ``1.0``.

        .. seealso:: :meth:`pool_timeout`

        Args:
            get_updates_pool_timeout (:obj:`float`): See
                :paramref:`telegram.request.HTTPXRequest.pool_timeout` for more information.

        Returns:
            :class:`ApplicationBuilder`: The same builder with the updated argument.
        """
        self._request_param_check(name="pool_timeout", get_updates=True)
        self._get_updates_pool_timeout = get_updates_pool_timeout
        return self

    def get_updates_http_version(
        self: BuilderType, get_updates_http_version: HTTPVersion
    ) -> BuilderType:
        """Sets the HTTP protocol version which is used for the
        :paramref:`~telegram.request.HTTPXRequest.http_version` parameter which is used in the
        :meth:`telegram.Bot.get_updates` request. By default, HTTP/1.1 is used.

        .. seealso:: :meth:`http_version`

        Note:
            Users have observed stability issues with HTTP/2, which happen due to how the `h2
            library handles <https://github.com/python-hyper/h2/issues/1181>`_ cancellations of
            keepalive connections. See `#3556 <https://github.com/python-telegram-bot/
            python-telegram-bot/issues/3556>`_ for a discussion.

            You will also need to install the http2 dependency. Keep in mind that the HTTP/1.1
            implementation may be considered the `"more robust option at this time"
            <https://www.python-httpx.org/http2#enabling-http2>`_.

            .. code-block:: bash

               pip install httpx[http2]

        .. versionadded:: 20.1
        .. versionchanged:: 20.2
            Reset the default version to 1.1.

        Args:
            get_updates_http_version (:obj:`str`): Pass ``"2"`` or ``"2.0"`` if you'd like to use
                HTTP/2 for making requests to Telegram. Defaults to ``"1.1"``, in which case
                HTTP/1.1 is used.

                .. versionchanged:: 20.5
                    Accept ``"2"`` as a valid value.

        Returns:
            :class:`ApplicationBuilder`: The same builder with the updated argument.
        """
        self._request_param_check(name="http_version", get_updates=True)
        self._get_updates_http_version = get_updates_http_version
        return self

    def private_key(
        self: BuilderType,
        private_key: bytes | FilePathInput,
        password: bytes | FilePathInput | None = None,
    ) -> BuilderType:
        """Sets the private key and corresponding password for decryption of telegram passport data
        for :attr:`telegram.ext.Application.bot`.

        Examples:
            :any:`Passport Bot <examples.passportbot>`

        .. seealso:: :wiki:`Telegram Passports <Telegram-Passport>`

        Args:
            private_key (:obj:`bytes` | :obj:`str` | :obj:`pathlib.Path`): The private key or the
                file path of a file that contains the key. In the latter case, the file's content
                will be read automatically.
            password (:obj:`bytes` | :obj:`str` | :obj:`pathlib.Path`, optional): The corresponding
                password or the file path of a file that contains the password. In the latter case,
                the file's content will be read automatically.

        Returns:
            :class:`ApplicationBuilder`: The same builder with the updated argument.
        """
        self._bot_check("private_key")
        self._updater_check("private_key")

        self._private_key = (
            private_key if isinstance(private_key, bytes) else Path(private_key).read_bytes()
        )
        if password is None or isinstance(password, bytes):
            self._private_key_password = password
        else:
            self._private_key_password = Path(password).read_bytes()

        return self

    def defaults(self: BuilderType, defaults: "Defaults") -> BuilderType:
        """Sets the :class:`telegram.ext.Defaults` instance for
        :attr:`telegram.ext.Application.bot`.

        .. seealso:: :wiki:`Adding Defaults to Your Bot <Adding-defaults-to-your-bot>`

        Args:
            defaults (:class:`telegram.ext.Defaults`): The defaults instance.

        Returns:
            :class:`ApplicationBuilder`: The same builder with the updated argument.
        """
        self._bot_check("defaults")
        self._updater_check("defaults")
        self._defaults = defaults
        return self

    def arbitrary_callback_data(
        self: BuilderType, arbitrary_callback_data: bool | int
    ) -> BuilderType:
        """Specifies whether :attr:`telegram.ext.Application.bot` should allow arbitrary objects as
        callback data for :class:`telegram.InlineKeyboardButton` and how many keyboards should be
        cached in memory. If not called, only strings can be used as callback data and no data will
        be stored in memory.

        Important:
            If you want to use this feature, you must install PTB with the optional requirement
            ``callback-data``, i.e.

            .. code-block:: bash

               pip install "python-telegram-bot[callback-data]"

        Examples:
            :any:`Arbitrary callback_data Bot <examples.arbitrarycallbackdatabot>`

        .. seealso:: :wiki:`Arbitrary callback_data <Arbitrary-callback_data>`

        Args:
            arbitrary_callback_data (:obj:`bool` | :obj:`int`): If :obj:`True` is passed, the
                default cache size of ``1024`` will be used. Pass an integer to specify a different
                cache size.

        Returns:
            :class:`ApplicationBuilder`: The same builder with the updated argument.
        """
        self._bot_check("arbitrary_callback_data")
        self._updater_check("arbitrary_callback_data")
        self._arbitrary_callback_data = arbitrary_callback_data
        return self

    def local_mode(self: BuilderType, local_mode: bool) -> BuilderType:
        """Specifies the value for :paramref:`~telegram.Bot.local_mode` for the
        :attr:`telegram.ext.Application.bot`.
        If not called, will default to :obj:`False`.

        .. seealso:: :wiki:`Local Bot API Server <Local-Bot-API-Server>`

        Args:
            local_mode (:obj:`bool`): Whether the bot should run in local mode.

        Returns:
            :class:`ApplicationBuilder`: The same builder with the updated argument.
        """
        self._bot_check("local_mode")
        self._updater_check("local_mode")
        self._local_mode = local_mode
        return self

    def bot(
        self: "ApplicationBuilder[BT, CCT, UD, CD, BD, JQ]",
        bot: InBT,
    ) -> "ApplicationBuilder[InBT, CCT, UD, CD, BD, JQ]":
        """Sets a :class:`telegram.Bot` instance for
        :attr:`telegram.ext.Application.bot`. Instances of subclasses like
        :class:`telegram.ext.ExtBot` are also valid.

        Args:
            bot (:class:`telegram.Bot`): The bot.

        Returns:
            :class:`ApplicationBuilder`: The same builder with the updated argument.
        """
        self._updater_check("bot")
        for attr, error in _BOT_CHECKS:
            if not isinstance(getattr(self, f"_{attr}"), DefaultValue):
                raise RuntimeError(_TWO_ARGS_REQ.format("bot", error))
        self._bot = bot
        return self  # type: ignore[return-value]

    def update_queue(self: BuilderType, update_queue: "Queue[object]") -> BuilderType:
        """Sets a :class:`asyncio.Queue` instance for
        :attr:`telegram.ext.Application.update_queue`, i.e. the queue that the application will
        fetch updates from. Will also be used for the :attr:`telegram.ext.Application.updater`.
        If not called, a queue will be instantiated.

        .. seealso:: :attr:`telegram.ext.Updater.update_queue`

        Args:
            update_queue (:class:`asyncio.Queue`): The queue.

        Returns:
            :class:`ApplicationBuilder`: The same builder with the updated argument.
        """
        if self._updater not in (DEFAULT_NONE, None):
            raise RuntimeError(_TWO_ARGS_REQ.format("update_queue", "updater instance"))
        self._update_queue = update_queue
        return self

    def concurrent_updates(
        self: BuilderType, concurrent_updates: "bool | int | BaseUpdateProcessor"
    ) -> BuilderType:
        """Specifies if and how many updates may be processed concurrently instead of one by one.
        If not called, updates will be processed one by one.

        Warning:
            Processing updates concurrently is not recommended when stateful handlers like
            :class:`telegram.ext.ConversationHandler` are used. Only use this if you are sure
            that your bot does not (explicitly or implicitly) rely on updates being processed
            sequentially.

        .. include:: inclusions/pool_size_tip.rst

        .. seealso:: :attr:`telegram.ext.Application.concurrent_updates`

        Args:
            concurrent_updates (:obj:`bool` | :obj:`int` | :class:`BaseUpdateProcessor`): Passing
                :obj:`True` will allow for ``256`` updates to be processed concurrently using
                :class:`telegram.ext.SimpleUpdateProcessor`. Pass an integer to specify a different
                number of updates that may be processed concurrently. Pass an instance of
                :class:`telegram.ext.BaseUpdateProcessor` to use that instance for handling updates
                concurrently.

                .. versionchanged:: 20.4
                    Now accepts :class:`BaseUpdateProcessor` instances.

        Returns:
            :class:`ApplicationBuilder`: The same builder with the updated argument.
        """
        # Check if concurrent updates is bool and convert to integer
        if concurrent_updates is True:
            concurrent_updates = 256
        elif concurrent_updates is False:
            concurrent_updates = 1

        # If `concurrent_updates` is an integer, create a `SimpleUpdateProcessor`
        # instance with that integer value; otherwise, raise an error if the value
        # is negative
        if isinstance(concurrent_updates, int):
            concurrent_updates = SimpleUpdateProcessor(concurrent_updates)

        # Assign default value of concurrent_updates if it is instance of
        # `BaseUpdateProcessor`
        self._update_processor: BaseUpdateProcessor = concurrent_updates  # type: ignore[no-redef]
        return self

    def job_queue(
        self: "ApplicationBuilder[BT, CCT, UD, CD, BD, JQ]",
        job_queue: InJQ,
    ) -> "ApplicationBuilder[BT, CCT, UD, CD, BD, InJQ]":
        """Sets a :class:`telegram.ext.JobQueue` instance for
        :attr:`telegram.ext.Application.job_queue`. If not called, a job queue will be
        instantiated if the requirements of :class:`telegram.ext.JobQueue` are installed.

        Examples:
            :any:`Timer Bot <examples.timerbot>`

        .. seealso:: :wiki:`Job Queue <Extensions---JobQueue>`

        Note:
            * :meth:`telegram.ext.JobQueue.set_application` will be called automatically by
              :meth:`build`.
            * The job queue will be automatically started and stopped by
              :meth:`telegram.ext.Application.start` and :meth:`telegram.ext.Application.stop`,
              respectively.
            * When passing :obj:`None` or when the requirements of :class:`telegram.ext.JobQueue`
              are not installed, :attr:`telegram.ext.ConversationHandler.conversation_timeout`
              can not be used, as this uses :attr:`telegram.ext.Application.job_queue` internally.

        Args:
            job_queue (:class:`telegram.ext.JobQueue`): The job queue. Pass :obj:`None` if you
                don't want to use a job queue.

        Returns:
            :class:`ApplicationBuilder`: The same builder with the updated argument.
        """
        self._job_queue = job_queue
        return self  # type: ignore[return-value]

    def persistence(
        self: BuilderType, persistence: "BasePersistence[Any, Any, Any]"
    ) -> BuilderType:
        """Sets a :class:`telegram.ext.BasePersistence` instance for
        :attr:`telegram.ext.Application.persistence`.

        Note:
            When using a persistence, note that all
            data stored in :attr:`context.user_data <telegram.ext.CallbackContext.user_data>`,
            :attr:`context.chat_data <telegram.ext.CallbackContext.chat_data>`,
            :attr:`context.bot_data <telegram.ext.CallbackContext.bot_data>` and
            in :attr:`telegram.ext.ExtBot.callback_data_cache` must be copyable with
            :func:`copy.deepcopy`. This is due to the data being deep copied before handing it over
            to the persistence in order to avoid race conditions.

        Examples:
            :any:`Persistent Conversation Bot <examples.persistentconversationbot>`

        .. seealso:: :wiki:`Making Your Bot Persistent <Making-your-bot-persistent>`

        Warning:
            If a :class:`telegram.ext.ContextTypes` instance is set via :meth:`context_types`,
            the persistence instance must use the same types!

        Args:
            persistence (:class:`telegram.ext.BasePersistence`): The persistence instance.

        Returns:
            :class:`ApplicationBuilder`: The same builder with the updated argument.
        """
        self._persistence = persistence
        return self

    def context_types(
        self: "ApplicationBuilder[BT, CCT, UD, CD, BD, JQ]",
        context_types: "ContextTypes[InCCT, InUD, InCD, InBD]",
    ) -> "ApplicationBuilder[BT, InCCT, InUD, InCD, InBD, JQ]":
        """Sets a :class:`telegram.ext.ContextTypes` instance for
        :attr:`telegram.ext.Application.context_types`.

        Examples:
            :any:`Context Types Bot <examples.contexttypesbot>`

        Args:
            context_types (:class:`telegram.ext.ContextTypes`): The context types.

        Returns:
            :class:`ApplicationBuilder`: The same builder with the updated argument.
        """
        self._context_types = context_types
        return self  # type: ignore[return-value]

    def updater(self: BuilderType, updater: Updater | None) -> BuilderType:
        """Sets a :class:`telegram.ext.Updater` instance for
        :attr:`telegram.ext.Application.updater`. The :attr:`telegram.ext.Updater.bot` and
        :attr:`telegram.ext.Updater.update_queue` will be used for
        :attr:`telegram.ext.Application.bot` and :attr:`telegram.ext.Application.update_queue`,
        respectively.

        Args:
            updater (:class:`telegram.ext.Updater` | :obj:`None`): The updater instance or
                :obj:`None` if no updater should be used.

        Returns:
            :class:`ApplicationBuilder`: The same builder with the updated argument.
        """
        if updater is None:
            self._updater = updater
            return self

        for attr, error in (
            (self._bot, "bot instance"),
            (self._update_queue, "update_queue"),
        ):
            if not isinstance(attr, DefaultValue):
                raise RuntimeError(_TWO_ARGS_REQ.format("updater", error))

        for attr_name, error in _BOT_CHECKS:
            if not isinstance(getattr(self, f"_{attr_name}"), DefaultValue):
                raise RuntimeError(_TWO_ARGS_REQ.format("updater", error))

        self._updater = updater
        return self

    def post_init(
        self: BuilderType, post_init: Callable[[Application], Coroutine[Any, Any, None]]
    ) -> BuilderType:
        """
        Sets a callback to be executed by :meth:`Application.run_polling` and
        :meth:`Application.run_webhook` *after* executing :meth:`Application.initialize` but
        *before* executing :meth:`Updater.start_polling` or :meth:`Updater.start_webhook`,
        respectively.

        Tip:
            This can be used for custom startup logic that requires to await coroutines, e.g.
            setting up the bots commands via :meth:`~telegram.Bot.set_my_commands`.

        Example:
            .. code::

                async def post_init(application: Application) -> None:
                    await application.bot.set_my_commands([('start', 'Starts the bot')])

                application = Application.builder().token("TOKEN").post_init(post_init).build()

        Note:
            |post_methods_note|

        .. seealso:: :meth:`post_stop`, :meth:`post_shutdown`

        Args:
            post_init (:term:`coroutine function`): The custom callback. Must be a
                :term:`coroutine function` and must accept exactly one positional argument, which
                is the :class:`~telegram.ext.Application`::

                    async def post_init(application: Application) -> None:

        Returns:
            :class:`ApplicationBuilder`: The same builder with the updated argument.
        """
        self._post_init = post_init
        return self

    def post_shutdown(
        self: BuilderType, post_shutdown: Callable[[Application], Coroutine[Any, Any, None]]
    ) -> BuilderType:
        """
        Sets a callback to be executed by :meth:`Application.run_polling` and
        :meth:`Application.run_webhook` *after* executing :meth:`Updater.shutdown`
        and :meth:`Application.shutdown`.

        Tip:
            This can be used for custom shutdown logic that requires to await coroutines, e.g.
            closing a database connection

        Example:
            .. code::

                async def post_shutdown(application: Application) -> None:
                    await application.bot_data['database'].close()

                application = Application.builder()
                                        .token("TOKEN")
                                        .post_shutdown(post_shutdown)
                                        .build()

        Note:
            |post_methods_note|

        .. seealso:: :meth:`post_init`, :meth:`post_stop`

        Args:
            post_shutdown (:term:`coroutine function`): The custom callback. Must be a
                :term:`coroutine function` and must accept exactly one positional argument, which
                is the :class:`~telegram.ext.Application`::

                    async def post_shutdown(application: Application) -> None:

        Returns:
            :class:`ApplicationBuilder`: The same builder with the updated argument.
        """
        self._post_shutdown = post_shutdown
        return self

    def post_stop(
        self: BuilderType, post_stop: Callable[[Application], Coroutine[Any, Any, None]]
    ) -> BuilderType:
        """
        Sets a callback to be executed by :meth:`Application.run_polling` and
        :meth:`Application.run_webhook` *after* executing :meth:`Updater.stop`
        and :meth:`Application.stop`.

        .. versionadded:: 20.1

        Tip:
            This can be used for custom stop logic that requires to await coroutines, e.g.
            sending message to a chat before shutting down the bot.

        Hint:
            The callback will be called only, if :meth:`Application.stop` was indeed called
            successfully. For example, if the application is stopped early by calling
            :meth:`Application.stop_running` within :meth:`post_init`, then the set callback will
            *not* be called.

        Example:
            .. code::

                async def post_stop(application: Application) -> None:
                    await application.bot.send_message(123456, "Shutting down...")

                application = Application.builder()
                                        .token("TOKEN")
                                        .post_stop(post_stop)
                                        .build()

        Note:
            |post_methods_note|

        .. seealso:: :meth:`post_init`, :meth:`post_shutdown`

        Args:
            post_stop (:term:`coroutine function`): The custom callback. Must be a
                :term:`coroutine function` and must accept exactly one positional argument, which
                is the :class:`~telegram.ext.Application`::

                    async def post_stop(application: Application) -> None:

        Returns:
            :class:`ApplicationBuilder`: The same builder with the updated argument.
        """
        self._post_stop = post_stop
        return self

    def rate_limiter(
        self: "ApplicationBuilder[BT, CCT, UD, CD, BD, JQ]",
        rate_limiter: "BaseRateLimiter[RLARGS]",
    ) -> "ApplicationBuilder[ExtBot[RLARGS], CCT, UD, CD, BD, JQ]":
        """Sets a :class:`telegram.ext.BaseRateLimiter` instance for the
        :paramref:`telegram.ext.ExtBot.rate_limiter` parameter of
        :attr:`telegram.ext.Application.bot`.

        Args:
            rate_limiter (:class:`telegram.ext.BaseRateLimiter`): The rate limiter.

        Returns:
            :class:`ApplicationBuilder`: The same builder with the updated argument.
        """
        self._bot_check("rate_limiter")
        self._updater_check("rate_limiter")
        self._rate_limiter = rate_limiter
        return self  # type: ignore[return-value]


InitApplicationBuilder = (  # This is defined all the way down here so that its type is inferred
    ApplicationBuilder[  # by Pylance correctly.
        ExtBot[None],
        ContextTypes.DEFAULT_TYPE,
        dict[Any, Any],
        dict[Any, Any],
        dict[Any, Any],
        JobQueue[ContextTypes.DEFAULT_TYPE],
    ]
)
