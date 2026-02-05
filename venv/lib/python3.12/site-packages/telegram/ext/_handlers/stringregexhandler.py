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
"""This module contains the StringRegexHandler class."""

import re
from re import Match, Pattern
from typing import TYPE_CHECKING, Any, TypeVar

from telegram._utils.defaultvalue import DEFAULT_TRUE
from telegram._utils.types import DVType
from telegram.ext._handlers.basehandler import BaseHandler
from telegram.ext._utils.types import CCT, HandlerCallback

if TYPE_CHECKING:
    from telegram.ext import Application

RT = TypeVar("RT")


class StringRegexHandler(BaseHandler[str, CCT, RT]):
    """Handler class to handle string updates based on a regex which checks the update content.

    Read the documentation of the :mod:`re` module for more information. The :func:`re.match`
    function is used to determine if an update should be handled by this handler.

    Note:
        This handler is not used to handle Telegram :class:`telegram.Update`, but strings manually
        put in the queue. For example to send messages with the bot using command line or API.

    Warning:
        When setting :paramref:`block` to :obj:`False`, you cannot rely on adding custom
        attributes to :class:`telegram.ext.CallbackContext`. See its docs for more info.

    Args:
        pattern (:obj:`str` | :func:`re.Pattern <re.compile>`): The regex pattern.
        callback (:term:`coroutine function`): The callback function for this handler. Will be
            called when :meth:`check_update` has determined that an update should be processed by
            this handler. Callback signature::

                async def callback(update: str, context: CallbackContext)

            The return value of the callback is usually ignored except for the special case of
            :class:`telegram.ext.ConversationHandler`.
        block (:obj:`bool`, optional): Determines whether the return value of the callback should
            be awaited before processing the next handler in
            :meth:`telegram.ext.Application.process_update`. Defaults to :obj:`True`.

            .. seealso:: :wiki:`Concurrency`

    Attributes:
        pattern (:obj:`str` | :func:`re.Pattern <re.compile>`): The regex pattern.
        callback (:term:`coroutine function`): The callback function for this handler.
        block (:obj:`bool`): Determines whether the return value of the callback should be
            awaited before processing the next handler in
            :meth:`telegram.ext.Application.process_update`.

    """

    __slots__ = ("pattern",)

    def __init__(
        self: "StringRegexHandler[CCT, RT]",
        pattern: str | Pattern[str],
        callback: HandlerCallback[str, CCT, RT],
        block: DVType[bool] = DEFAULT_TRUE,
    ):
        super().__init__(callback, block=block)

        if isinstance(pattern, str):
            pattern = re.compile(pattern)

        self.pattern: str | Pattern[str] = pattern

    def check_update(self, update: object) -> Match[str] | None:
        """Determines whether an update should be passed to this handler's :attr:`callback`.

        Args:
            update (:obj:`object`): The incoming update.

        Returns:
            :obj:`None` | :obj:`re.match`

        """
        if isinstance(update, str) and (match := re.match(self.pattern, update)):
            return match
        return None

    def collect_additional_context(
        self,
        context: CCT,
        update: str,  # noqa: ARG002
        application: "Application[Any, CCT, Any, Any, Any, Any]",  # noqa: ARG002
        check_result: Match[str] | None,
    ) -> None:
        """Add the result of ``re.match(pattern, update)`` to :attr:`CallbackContext.matches` as
        list with one element.
        """
        if self.pattern and check_result:
            context.matches = [check_result]
