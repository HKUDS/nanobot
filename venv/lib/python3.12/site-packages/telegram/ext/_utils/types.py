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
"""This module contains custom typing aliases.

.. versionadded:: 13.6

Warning:
    Contents of this module are intended to be used internally by the library and *not* by the
    user. Changes to this module are not considered breaking changes and may not be documented in
    the changelog.
"""

from collections.abc import Callable, Coroutine, MutableMapping
from typing import TYPE_CHECKING, Any, TypeVar

if TYPE_CHECKING:
    from telegram import Bot
    from telegram.ext import BaseRateLimiter, CallbackContext, JobQueue

CCT = TypeVar("CCT", bound="CallbackContext[Any, Any, Any, Any]")
"""An instance of :class:`telegram.ext.CallbackContext` or a custom subclass.

.. versionadded:: 13.6
"""

RT = TypeVar("RT")
UT = TypeVar("UT")
HandlerCallback = Callable[[UT, CCT], Coroutine[Any, Any, RT]]
"""Type of a handler callback

    .. versionadded:: 20.0
"""
JobCallback = Callable[[CCT], Coroutine[Any, Any, Any]]
"""Type of a job callback

    .. versionadded:: 20.0
"""

ConversationKey = tuple[int | str, ...]
ConversationDict = MutableMapping[ConversationKey, object]
"""dict[tuple[:obj:`int` | :obj:`str`, ...], :obj:`object` | None]:
    Dicts as maintained by the :class:`telegram.ext.ConversationHandler`.

    .. versionadded:: 13.6
"""

CDCData = tuple[list[tuple[str, float, dict[str, Any]]], dict[str, str]]
"""tuple[list[tuple[:obj:`str`, :obj:`float`, dict[:obj:`str`, :class:`object`]]], \
    dict[:obj:`str`, :obj:`str`]]: Data returned by
    :attr:`telegram.ext.CallbackDataCache.persistence_data`.

    .. versionadded:: 13.6
"""

BT = TypeVar("BT", bound="Bot")
"""Type of the bot.

.. versionadded:: 20.0
"""
UD = TypeVar("UD")
"""Type of the user data for a single user.

.. versionadded:: 13.6
"""
CD = TypeVar("CD")
"""Type of the chat data for a single user.

.. versionadded:: 13.6
"""
BD = TypeVar("BD")
"""Type of the bot data.

.. versionadded:: 13.6
"""
JQ = TypeVar("JQ", bound="None | JobQueue")
"""Type of the job queue.

.. versionadded:: 20.0"""

RL = TypeVar("RL", bound="BaseRateLimiter | None")
"""Type of the rate limiter.

.. versionadded:: 20.0"""

RLARGS = TypeVar("RLARGS")
"""Type of the rate limiter arguments.

.. versionadded:: 20.0"""
FilterDataDict = dict[str, list[Any]]
