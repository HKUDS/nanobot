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
"""This module contains classes that represent Telegram errors.

.. versionchanged:: 20.0
    Replaced ``Unauthorized`` by :class:`Forbidden`.
"""

import datetime as dtm

from telegram._utils.argumentparsing import to_timedelta
from telegram._utils.datetime import get_timedelta_value
from telegram._utils.types import TimePeriod

__all__ = (
    "BadRequest",
    "ChatMigrated",
    "Conflict",
    "EndPointNotFound",
    "Forbidden",
    "InvalidToken",
    "NetworkError",
    "PassportDecryptionError",
    "RetryAfter",
    "TelegramError",
    "TimedOut",
)


class TelegramError(Exception):
    """
    Base class for Telegram errors.

    Tip:
        Objects of this type can be serialized via Python's :mod:`pickle` module and pickled
        objects from one version of PTB are usually loadable in future versions. However, we can
        not guarantee that this compatibility will always be provided. At least a manual one-time
        conversion of the data may be needed on major updates of the library.

    .. seealso:: :wiki:`Exceptions, Warnings and Logging <Exceptions%2C-Warnings-and-Logging>`
    """

    __slots__ = ("message",)

    def __init__(self, message: str):
        super().__init__()

        msg = message.removeprefix("Error: ")
        msg = msg.removeprefix("[Error]: ")
        msg = msg.removeprefix("Bad Request: ")
        if msg != message:
            # api_error - capitalize the msg...
            msg = msg.capitalize()
        self.message: str = msg

    def __str__(self) -> str:
        """Gives the string representation of exceptions message.

        Returns:
           :obj:`str`
        """
        return self.message

    def __repr__(self) -> str:
        """Gives an unambiguous string representation of the exception.

        Returns:
           :obj:`str`
        """
        return f"{self.__class__.__name__}('{self.message}')"

    def __reduce__(self) -> tuple[type, tuple[str]]:
        """Defines how to serialize the exception for pickle.

        .. seealso::
               :py:meth:`object.__reduce__`, :mod:`pickle`.

        Returns:
            :obj:`tuple`
        """
        return self.__class__, (self.message,)


class Forbidden(TelegramError):
    """Raised when the bot has not enough rights to perform the requested action.

    Examples:
        :any:`Raw API Bot <examples.rawapibot>`

    .. versionchanged:: 20.0
        This class was previously named ``Unauthorized``.
    """

    __slots__ = ()


class InvalidToken(TelegramError):
    """Raised when the token is invalid.

    Args:
        message (:obj:`str`, optional): Any additional information about the exception.

            .. versionadded:: 20.0
    """

    __slots__ = ()

    def __init__(self, message: str | None = None) -> None:
        super().__init__("Invalid token" if message is None else message)


class EndPointNotFound(TelegramError):
    """Raised when the requested endpoint is not found. Only relevant for
    :meth:`telegram.Bot.do_api_request`.

    .. versionadded:: 20.8
    """

    __slots__ = ()


class NetworkError(TelegramError):
    """Base class for exceptions due to networking errors.

    Tip:
        This exception (and its subclasses) usually originates from the networking backend
        used by :class:`~telegram.request.HTTPXRequest`, or a custom implementation of
        :class:`~telegram.request.BaseRequest`. In this case, the original exception can be
        accessed via the ``__cause__``
        `attribute <https://docs.python.org/3/library/exceptions.html#exception-context>`_.

    Examples:
        :any:`Raw API Bot <examples.rawapibot>`

    .. seealso::
        :wiki:`Handling network errors <Handling-network-errors>`
    """

    __slots__ = ()


class BadRequest(NetworkError):
    """Raised when Telegram could not process the request correctly."""

    __slots__ = ()


class TimedOut(NetworkError):
    """Raised when a request took too long to finish.

    .. seealso::
        :wiki:`Handling network errors <Handling-network-errors>`

    Args:
        message (:obj:`str`, optional): Any additional information about the exception.

            .. versionadded:: 20.0
    """

    __slots__ = ()

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or "Timed out")


class ChatMigrated(TelegramError):
    """
    Raised when the requested group chat migrated to supergroup and has a new chat id.

    .. seealso::
        :wiki:`Storing Bot, User and Chat Related Data <Storing-bot%2C-user-and-chat-related-data>`

    Args:
        new_chat_id (:obj:`int`): The new chat id of the group.

    Attributes:
        new_chat_id (:obj:`int`): The new chat id of the group.

    """

    __slots__ = ("new_chat_id",)

    def __init__(self, new_chat_id: int):
        super().__init__(f"Group migrated to supergroup. New chat id: {new_chat_id}")
        self.new_chat_id: int = new_chat_id

    def __reduce__(self) -> tuple[type, tuple[int]]:  # type: ignore[override]
        return self.__class__, (self.new_chat_id,)


class RetryAfter(TelegramError):
    """
    Raised when flood limits where exceeded.

    .. versionchanged:: 20.0
       :attr:`retry_after` is now an integer to comply with the Bot API.

    Args:
        retry_after (:obj:`int` | :class:`datetime.timedelta`): Time in seconds, after which the
            bot can retry the request.

            .. versionchanged:: v22.2
                |time-period-input|

    Attributes:
        retry_after (:obj:`int` | :class:`datetime.timedelta`): Time in seconds, after which the
            bot can retry the request.

            .. deprecated:: v22.2
                |time-period-int-deprecated|

    """

    __slots__ = ("_retry_after",)

    def __init__(self, retry_after: TimePeriod):
        self._retry_after: dtm.timedelta = to_timedelta(retry_after)

        if isinstance(self.retry_after, int):
            super().__init__(f"Flood control exceeded. Retry in {self.retry_after} seconds")
        else:
            super().__init__(f"Flood control exceeded. Retry in {self.retry_after!s}")

    @property
    def retry_after(self) -> int | dtm.timedelta:  # noqa: D102
        # Diableing D102 because docstring for `retry_after` is present at the class's level
        return get_timedelta_value(  # type: ignore[return-value]
            self._retry_after, attribute="retry_after"
        )

    def __reduce__(self) -> tuple[type, tuple[float]]:  # type: ignore[override]
        # Until support for `int` time periods is lifted, leave pickle behaviour the same
        # tag: deprecated: v22.2
        return self.__class__, (int(self._retry_after.total_seconds()),)


class Conflict(TelegramError):
    """Raised when a long poll or webhook conflicts with another one."""

    __slots__ = ()

    def __reduce__(self) -> tuple[type, tuple[str]]:
        return self.__class__, (self.message,)


class PassportDecryptionError(TelegramError):
    """Something went wrong with decryption.

    .. versionchanged:: 20.0
        This class was previously named ``TelegramDecryptionError`` and was available via
        ``telegram.TelegramDecryptionError``.
    """

    __slots__ = ("_msg",)

    def __init__(self, message: str | Exception):
        super().__init__(f"PassportDecryptionError: {message}")
        self._msg = str(message)

    def __reduce__(self) -> tuple[type, tuple[str]]:
        return self.__class__, (self._msg,)
