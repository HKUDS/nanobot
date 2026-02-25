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
"""This module contains an abstract class to make POST and GET requests."""

import abc
import json
from contextlib import AbstractAsyncContextManager
from http import HTTPStatus
from types import TracebackType
from typing import Final, TypeVar, final

from telegram._utils.defaultvalue import DEFAULT_NONE as _DEFAULT_NONE
from telegram._utils.defaultvalue import DefaultValue
from telegram._utils.logging import get_logger
from telegram._utils.strings import TextEncoding
from telegram._utils.types import JSONDict, ODVInput
from telegram._version import __version__ as ptb_ver
from telegram.error import (
    BadRequest,
    ChatMigrated,
    Conflict,
    Forbidden,
    InvalidToken,
    NetworkError,
    RetryAfter,
    TelegramError,
)
from telegram.request._requestdata import RequestData

RT = TypeVar("RT", bound="BaseRequest")

_LOGGER = get_logger(__name__, class_name="BaseRequest")


class BaseRequest(
    AbstractAsyncContextManager["BaseRequest"],
    abc.ABC,
):
    """Abstract interface class that allows python-telegram-bot to make requests to the Bot API.
    Can be implemented via different asyncio HTTP libraries. An implementation of this class
    must implement all abstract methods and properties.

    Instances of this class can be used as asyncio context managers, where

    .. code:: python

        async with request_object:
            # code

    is roughly equivalent to

    .. code:: python

        try:
            await request_object.initialize()
            # code
        finally:
            await request_object.shutdown()

    .. seealso:: :meth:`__aenter__` and :meth:`__aexit__`.

    Tip:
        JSON encoding and decoding is done with the standard library's :mod:`json` by default.
        To use a custom library for this, you can override :meth:`parse_json_payload` and implement
        custom logic to encode the keys of :attr:`telegram.request.RequestData.parameters`.

    .. seealso:: :wiki:`Architecture Overview <Architecture>`,
        :wiki:`Builder Pattern <Builder-Pattern>`

    .. versionadded:: 20.0
    """

    __slots__ = ()

    USER_AGENT: Final[str] = f"python-telegram-bot v{ptb_ver} (https://python-telegram-bot.org)"
    """:obj:`str`: A description that can be used as user agent for requests made to the Bot API.
    """
    DEFAULT_NONE: Final[DefaultValue[None]] = _DEFAULT_NONE
    """:class:`object`: A special object that indicates that an argument of a function was not
    explicitly passed. Used for the timeout parameters of :meth:`post` and :meth:`do_request`.

    Example:
        When calling ``request.post(url)``, ``request`` should use the default timeouts set on
        initialization. When calling ``request.post(url, connect_timeout=5, read_timeout=None)``,
        ``request`` should use ``5`` for the connect timeout and :obj:`None` for the read timeout.

        Use ``if parameter is (not) BaseRequest.DEFAULT_NONE:`` to check if the parameter was set.
    """

    async def __aenter__(self: RT) -> RT:
        """|async_context_manager| :meth:`initializes <initialize>` the Request.

        Returns:
            The initialized Request instance.

        Raises:
            :exc:`Exception`: If an exception is raised during initialization, :meth:`shutdown`
                is called in this case.
        """
        try:
            await self.initialize()
        except Exception:
            await self.shutdown()
            raise
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """|async_context_manager| :meth:`shuts down <shutdown>` the Request."""
        # Make sure not to return `True` so that exceptions are not suppressed
        # https://docs.python.org/3/reference/datamodel.html?#object.__aexit__
        await self.shutdown()

    @property
    @abc.abstractmethod
    def read_timeout(self) -> float | None:
        """This property must return the default read timeout in seconds used by this class.
        More precisely, the returned value should be the one used when
        :paramref:`post.read_timeout` of :meth:post` is not passed/equal to :attr:`DEFAULT_NONE`.

        .. versionadded:: 20.7
        .. versionchanged:: 22.0
            This property is now required to be implemented by subclasses.

        Returns:
            :obj:`float` | :obj:`None`: The read timeout in seconds.
        """

    @abc.abstractmethod
    async def initialize(self) -> None:
        """Initialize resources used by this class. Must be implemented by a subclass."""

    @abc.abstractmethod
    async def shutdown(self) -> None:
        """Stop & clear resources used by this class. Must be implemented by a subclass."""

    @final
    async def post(
        self,
        url: str,
        request_data: RequestData | None = None,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
    ) -> JSONDict | list[JSONDict] | bool:
        """Makes a request to the Bot API handles the return code and parses the answer.

        Warning:
            This method will be called by the methods of :class:`telegram.Bot` and should *not* be
            called manually.

        Args:
            url (:obj:`str`): The URL to request.
            request_data (:class:`telegram.request.RequestData`, optional): An object containing
                information about parameters and files to upload for the request.
            read_timeout (:obj:`float` | :obj:`None`, optional): If passed, specifies the maximum
                amount of time (in seconds) to wait for a response from Telegram's server instead
                of the time specified during creating of this object. Defaults to
                :attr:`DEFAULT_NONE`.
            write_timeout (:obj:`float` | :obj:`None`, optional): If passed, specifies the maximum
                amount of time (in seconds) to wait for a write operation to complete (in terms of
                a network socket; i.e. POSTing a request or uploading a file) instead of the time
                specified during creating of this object. Defaults to :attr:`DEFAULT_NONE`.
            connect_timeout (:obj:`float` | :obj:`None`, optional): If passed, specifies the
                maximum amount of time (in seconds) to wait for a connection attempt to a server
                to succeed instead of the time specified during creating of this object. Defaults
                to :attr:`DEFAULT_NONE`.
            pool_timeout (:obj:`float` | :obj:`None`, optional): If passed, specifies the maximum
                amount of time (in seconds) to wait for a connection to become available instead
                of the time specified during creating of this object. Defaults to
                :attr:`DEFAULT_NONE`.

        Returns:
          The JSON response of the Bot API.

        """
        result = await self._request_wrapper(
            url=url,
            method="POST",
            request_data=request_data,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
        )
        json_data = self.parse_json_payload(result)
        # For successful requests, the results are in the 'result' entry
        # see https://core.telegram.org/bots/api#making-requests
        return json_data["result"]

    @final
    async def retrieve(
        self,
        url: str,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
    ) -> bytes:
        """Retrieve the contents of a file by its URL.

        Warning:
            This method will be called by the methods of :class:`telegram.Bot` and should *not* be
            called manually.

        Args:
            url (:obj:`str`): The web location we want to retrieve.
            read_timeout (:obj:`float` | :obj:`None`, optional): If passed, specifies the maximum
                amount of time (in seconds) to wait for a response from Telegram's server instead
                of the time specified during creating of this object. Defaults to
                :attr:`DEFAULT_NONE`.
            write_timeout (:obj:`float` | :obj:`None`, optional): If passed, specifies the maximum
                amount of time (in seconds) to wait for a write operation to complete (in terms of
                a network socket; i.e. POSTing a request or uploading a file) instead of the time
                specified during creating of this object. Defaults to :attr:`DEFAULT_NONE`.
            connect_timeout (:obj:`float` | :obj:`None`, optional): If passed, specifies the
                maximum amount of time (in seconds) to wait for a connection attempt to a server
                to succeed instead of the time specified during creating of this object. Defaults
                to :attr:`DEFAULT_NONE`.
            pool_timeout (:obj:`float` | :obj:`None`, optional): If passed, specifies the maximum
                amount of time (in seconds) to wait for a connection to become available instead
                of the time specified during creating of this object. Defaults to
                :attr:`DEFAULT_NONE`.

        Returns:
            :obj:`bytes`: The files contents.

        """
        return await self._request_wrapper(
            url=url,
            method="GET",
            read_timeout=read_timeout,
            write_timeout=write_timeout,
            connect_timeout=connect_timeout,
            pool_timeout=pool_timeout,
        )

    async def _request_wrapper(
        self,
        url: str,
        method: str,
        request_data: RequestData | None = None,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
    ) -> bytes:
        """Wraps the real implementation request method.

        Performs the following tasks:
        * Handle the various HTTP response codes.
        * Parse the Telegram server response.

        Args:
            url (:obj:`str`): The URL to request.
            method (:obj:`str`): HTTP method (i.e. 'POST', 'GET', etc.).
            request_data (:class:`telegram.request.RequestData`, optional): An object containing
                information about parameters and files to upload for the request.
            read_timeout (:obj:`float` | :obj:`None`, optional): If passed, specifies the maximum
                amount of time (in seconds) to wait for a response from Telegram's server instead
                of the time specified during creating of this object. Defaults to
                :attr:`DEFAULT_NONE`.
            write_timeout (:obj:`float` | :obj:`None`, optional): If passed, specifies the maximum
                amount of time (in seconds) to wait for a write operation to complete (in terms of
                a network socket; i.e. POSTing a request or uploading a file) instead of the time
                specified during creating of this object. Defaults to :attr:`DEFAULT_NONE`.
            connect_timeout (:obj:`float` | :obj:`None`, optional): If passed, specifies the
                maximum amount of time (in seconds) to wait for a connection attempt to a server
                to succeed instead of the time specified during creating of this object. Defaults
                to :attr:`DEFAULT_NONE`.
            pool_timeout (:obj:`float` | :obj:`None`, optional): If passed, specifies the maximum
                amount of time (in seconds) to wait for a connection to become available instead
                of the time specified during creating of this object. Defaults to
                :attr:`DEFAULT_NONE`.

        Returns:
            bytes: The payload part of the HTTP server response.

        Raises:
            TelegramError

        """
        try:
            code, payload = await self.do_request(
                url=url,
                method=method,
                request_data=request_data,
                read_timeout=read_timeout,
                write_timeout=write_timeout,
                connect_timeout=connect_timeout,
                pool_timeout=pool_timeout,
            )
        except TelegramError:
            raise
        except Exception as exc:
            raise NetworkError(f"Unknown error in HTTP implementation: {exc!r}") from exc

        if HTTPStatus.OK <= code <= 299:
            # 200-299 range are HTTP success statuses
            # starting with Py 3.12 we can use `HTTPStatus.is_success`
            return payload

        try:
            message = f"{HTTPStatus(code).phrase} ({code})"
        except ValueError:
            message = f"Unknown HTTPError ({code})"

        parsing_exception: TelegramError | None = None

        try:
            response_data = self.parse_json_payload(payload)
        except TelegramError as exc:
            message += f". Parsing the server response {payload!r} failed"
            parsing_exception = exc
        else:
            message = response_data.get("description") or message

            # In some special cases, we can raise more informative exceptions:
            # see https://core.telegram.org/bots/api#responseparameters and
            # https://core.telegram.org/bots/api#making-requests
            # TGs response also has the fields 'ok' and 'error_code'.
            # However, we rather rely on the HTTP status code for now.
            parameters = response_data.get("parameters")
            if parameters:
                migrate_to_chat_id = parameters.get("migrate_to_chat_id")
                if migrate_to_chat_id:
                    raise ChatMigrated(migrate_to_chat_id)
                retry_after = parameters.get("retry_after")
                if retry_after:
                    raise RetryAfter(retry_after)

                message += f". The server response contained unknown parameters: {parameters}"

        if code == HTTPStatus.FORBIDDEN:  # 403
            exception: TelegramError = Forbidden(message)
        elif code in (HTTPStatus.NOT_FOUND, HTTPStatus.UNAUTHORIZED):  # 404 and 401
            # TG returns 404 Not found for
            #   1) malformed tokens
            #   2) correct tokens but non-existing method, e.g. api.tg.org/botTOKEN/unkonwnMethod
            # 2) is relevant only for Bot.do_api_request, where we have special handing for it.
            # TG returns 401 Unauthorized for correctly formatted tokens that are not valid
            exception = InvalidToken(message)
        elif code == HTTPStatus.BAD_REQUEST:  # 400
            exception = BadRequest(message)
        elif code == HTTPStatus.CONFLICT:  # 409
            exception = Conflict(message)
        elif code == HTTPStatus.BAD_GATEWAY:  # 502
            exception = NetworkError(message)
        else:
            exception = NetworkError(message)

        if parsing_exception:
            raise exception from parsing_exception
        raise exception

    @staticmethod
    def parse_json_payload(payload: bytes) -> JSONDict:
        """Parse the JSON returned from Telegram.

        Tip:
            By default, this method uses the standard library's :func:`json.loads` and
            ``errors="replace"`` in :meth:`bytes.decode`.
            You can override it to customize either of these behaviors.

        Args:
            payload (:obj:`bytes`): The UTF-8 encoded JSON payload as returned by Telegram.

        Returns:
            dict: A JSON parsed as Python dict with results.

        Raises:
            TelegramError: If loading the JSON data failed
        """
        decoded_s = payload.decode(TextEncoding.UTF_8, "replace")
        try:
            return json.loads(decoded_s)
        except ValueError as exc:
            _LOGGER.exception('Can not load invalid JSON data: "%s"', decoded_s)
            raise TelegramError("Invalid server response") from exc

    @abc.abstractmethod
    async def do_request(
        self,
        url: str,
        method: str,
        request_data: RequestData | None = None,
        read_timeout: ODVInput[float] = DEFAULT_NONE,
        write_timeout: ODVInput[float] = DEFAULT_NONE,
        connect_timeout: ODVInput[float] = DEFAULT_NONE,
        pool_timeout: ODVInput[float] = DEFAULT_NONE,
    ) -> tuple[int, bytes]:
        """Makes a request to the Bot API. Must be implemented by a subclass.

        Warning:
            This method will be called by :meth:`post` and :meth:`retrieve`. It should *not* be
            called manually.

        Args:
            url (:obj:`str`): The URL to request.
            method (:obj:`str`): HTTP method (i.e. ``'POST'``, ``'GET'``, etc.).
            request_data (:class:`telegram.request.RequestData`, optional): An object containing
                information about parameters and files to upload for the request.
            read_timeout (:obj:`float` | :obj:`None`, optional): If passed, specifies the maximum
                amount of time (in seconds) to wait for a response from Telegram's server instead
                of the time specified during creating of this object. Defaults to
                :attr:`DEFAULT_NONE`.
            write_timeout (:obj:`float` | :obj:`None`, optional): If passed, specifies the maximum
                amount of time (in seconds) to wait for a write operation to complete (in terms of
                a network socket; i.e. POSTing a request or uploading a file) instead of the time
                specified during creating of this object. Defaults to :attr:`DEFAULT_NONE`.
            connect_timeout (:obj:`float` | :obj:`None`, optional): If passed, specifies the
                maximum amount of time (in seconds) to wait for a connection attempt to a server
                to succeed instead of the time specified during creating of this object. Defaults
                to :attr:`DEFAULT_NONE`.
            pool_timeout (:obj:`float` | :obj:`None`, optional): If passed, specifies the maximum
                amount of time (in seconds) to wait for a connection to become available instead
                of the time specified during creating of this object. Defaults to
                :attr:`DEFAULT_NONE`.

        Returns:
            tuple[:obj:`int`, :obj:`bytes`]: The HTTP return code & the payload part of the server
            response.
        """
