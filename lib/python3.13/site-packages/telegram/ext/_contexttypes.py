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
"""This module contains the auxiliary class ContextTypes."""

from typing import Any, Generic, overload

from telegram.ext._callbackcontext import CallbackContext
from telegram.ext._extbot import ExtBot
from telegram.ext._utils.types import BD, CCT, CD, UD

ADict = dict[Any, Any]


class ContextTypes(Generic[CCT, UD, CD, BD]):
    """
    Convenience class to gather customizable types of the :class:`telegram.ext.CallbackContext`
    interface.

    Examples:
        :any:`ContextTypes Bot <examples.contexttypesbot>`

    .. seealso:: :wiki:`Architecture Overview <Architecture>`,
        :wiki:`Storing Bot, User and Chat Related Data <Storing-bot%2C-user-and-chat-related-data>`

    .. versionadded:: 13.6

    Args:
        context (:obj:`type`, optional): Determines the type of the ``context`` argument of all
            (error-)handler callbacks and job callbacks. Must be a subclass of
            :class:`telegram.ext.CallbackContext`. Defaults to
            :class:`telegram.ext.CallbackContext`.
        bot_data (:obj:`type`, optional): Determines the type of
            :attr:`context.bot_data <CallbackContext.bot_data>` of all (error-)handler callbacks
            and job callbacks. Defaults to :obj:`dict`. Must support instantiating without
            arguments.
        chat_data (:obj:`type`, optional): Determines the type of
            :attr:`context.chat_data <CallbackContext.chat_data>` of all (error-)handler callbacks
            and job callbacks. Defaults to :obj:`dict`. Must support instantiating without
            arguments.
        user_data (:obj:`type`, optional): Determines the type of
            :attr:`context.user_data <CallbackContext.user_data>` of all (error-)handler callbacks
            and job callbacks. Defaults to :obj:`dict`. Must support instantiating without
            arguments.

    """

    DEFAULT_TYPE = CallbackContext[ExtBot[None], ADict, ADict, ADict]
    """Shortcut for the type annotation for the ``context`` argument that's correct for the
    default settings, i.e. if :class:`telegram.ext.ContextTypes` is not used.

    Example:
        .. code:: python

            async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
                ...

    .. versionadded: 20.0
    """

    __slots__ = ("_bot_data", "_chat_data", "_context", "_user_data")

    # overload signatures generated with
    # https://gist.github.com/Bibo-Joshi/399382cda537fb01bd86b13c3d03a956

    @overload
    def __init__(
        self: "ContextTypes[CallbackContext[ExtBot[Any], ADict, ADict, ADict], ADict, ADict, ADict]",  # pylint: disable=line-too-long  # noqa: E501
    ): ...

    @overload
    def __init__(self: "ContextTypes[CCT, ADict, ADict, ADict]", context: type[CCT]): ...

    @overload
    def __init__(
        self: "ContextTypes[CallbackContext[ExtBot[Any], UD, ADict, ADict], UD, ADict, ADict]",
        user_data: type[UD],
    ): ...

    @overload
    def __init__(
        self: "ContextTypes[CallbackContext[ExtBot[Any], ADict, CD, ADict], ADict, CD, ADict]",
        chat_data: type[CD],
    ): ...

    @overload
    def __init__(
        self: "ContextTypes[CallbackContext[ExtBot[Any], ADict, ADict, BD], ADict, ADict, BD]",
        bot_data: type[BD],
    ): ...

    @overload
    def __init__(
        self: "ContextTypes[CCT, UD, ADict, ADict]", context: type[CCT], user_data: type[UD]
    ): ...

    @overload
    def __init__(
        self: "ContextTypes[CCT, ADict, CD, ADict]", context: type[CCT], chat_data: type[CD]
    ): ...

    @overload
    def __init__(
        self: "ContextTypes[CCT, ADict, ADict, BD]", context: type[CCT], bot_data: type[BD]
    ): ...

    @overload
    def __init__(
        self: "ContextTypes[CallbackContext[ExtBot[Any], UD, CD, ADict], UD, CD, ADict]",
        user_data: type[UD],
        chat_data: type[CD],
    ): ...

    @overload
    def __init__(
        self: "ContextTypes[CallbackContext[ExtBot[Any], UD, ADict, BD], UD, ADict, BD]",
        user_data: type[UD],
        bot_data: type[BD],
    ): ...

    @overload
    def __init__(
        self: "ContextTypes[CallbackContext[ExtBot[Any], ADict, CD, BD], ADict, CD, BD]",
        chat_data: type[CD],
        bot_data: type[BD],
    ): ...

    @overload
    def __init__(
        self: "ContextTypes[CCT, UD, CD, ADict]",
        context: type[CCT],
        user_data: type[UD],
        chat_data: type[CD],
    ): ...

    @overload
    def __init__(
        self: "ContextTypes[CCT, UD, ADict, BD]",
        context: type[CCT],
        user_data: type[UD],
        bot_data: type[BD],
    ): ...

    @overload
    def __init__(
        self: "ContextTypes[CCT, ADict, CD, BD]",
        context: type[CCT],
        chat_data: type[CD],
        bot_data: type[BD],
    ): ...

    @overload
    def __init__(
        self: "ContextTypes[CallbackContext[ExtBot[Any], UD, CD, BD], UD, CD, BD]",
        user_data: type[UD],
        chat_data: type[CD],
        bot_data: type[BD],
    ): ...

    @overload
    def __init__(
        self: "ContextTypes[CCT, UD, CD, BD]",
        context: type[CCT],
        user_data: type[UD],
        chat_data: type[CD],
        bot_data: type[BD],
    ): ...

    def __init__(  # type: ignore[misc]
        self,
        context: "type[CallbackContext[ExtBot[Any], ADict, ADict, ADict]]" = CallbackContext,
        bot_data: type[ADict] = dict,
        chat_data: type[ADict] = dict,
        user_data: type[ADict] = dict,
    ):
        if not issubclass(context, CallbackContext):
            raise TypeError("context must be a subclass of CallbackContext.")

        # We make all those only accessible via properties because we don't currently support
        # changing this at runtime, so overriding the attributes doesn't make sense
        self._context = context
        self._bot_data = bot_data
        self._chat_data = chat_data
        self._user_data = user_data

    @property
    def context(self) -> type[CCT]:
        """The type of the ``context`` argument of all (error-)handler callbacks and job
        callbacks.
        """
        return self._context  # type: ignore[return-value]

    @property
    def bot_data(self) -> type[BD]:
        """The type of :attr:`context.bot_data <CallbackContext.bot_data>` of all (error-)handler
        callbacks and job callbacks.
        """
        return self._bot_data  # type: ignore[return-value]

    @property
    def chat_data(self) -> type[CD]:
        """The type of :attr:`context.chat_data <CallbackContext.chat_data>` of all (error-)handler
        callbacks and job callbacks.
        """
        return self._chat_data  # type: ignore[return-value]

    @property
    def user_data(self) -> type[UD]:
        """The type of :attr:`context.user_data <CallbackContext.user_data>` of all (error-)handler
        callbacks and job callbacks.
        """
        return self._user_data  # type: ignore[return-value]
