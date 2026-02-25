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
"""This module contains the ChosenInlineResultHandler class."""

import re
from re import Match, Pattern
from typing import TYPE_CHECKING, Any, TypeVar, cast

from telegram import Update
from telegram._utils.defaultvalue import DEFAULT_TRUE
from telegram._utils.types import DVType
from telegram.ext._handlers.basehandler import BaseHandler
from telegram.ext._utils.types import CCT, HandlerCallback

RT = TypeVar("RT")

if TYPE_CHECKING:
    from telegram.ext import Application


class ChosenInlineResultHandler(BaseHandler[Update, CCT, RT]):
    """Handler class to handle Telegram updates that contain
    :attr:`telegram.Update.chosen_inline_result`.

    Warning:
        When setting :paramref:`block` to :obj:`False`, you cannot rely on adding custom
        attributes to :class:`telegram.ext.CallbackContext`. See its docs for more info.

    Args:
        callback (:term:`coroutine function`): The callback function for this handler. Will be
            called when :meth:`check_update` has determined that an update should be processed by
            this handler. Callback signature::

                async def callback(update: Update, context: CallbackContext)

            The return value of the callback is usually ignored except for the special case of
            :class:`telegram.ext.ConversationHandler`.
        block (:obj:`bool`, optional): Determines whether the return value of the callback should
            be awaited before processing the next handler in
            :meth:`telegram.ext.Application.process_update`. Defaults to :obj:`True`.

            .. seealso:: :wiki:`Concurrency`
        pattern (:obj:`str` | :func:`re.Pattern <re.compile>`, optional): Regex pattern. If not
            :obj:`None`, :func:`re.match`
            is used on :attr:`telegram.ChosenInlineResult.result_id` to determine if an update
            should be handled by this handler. This is accessible in the callback as
            :attr:`telegram.ext.CallbackContext.matches`.

            .. versionadded:: 13.6
    Attributes:
        callback (:term:`coroutine function`): The callback function for this handler.
        block (:obj:`bool`): Determines whether the return value of the callback should be
            awaited before processing the next handler in
            :meth:`telegram.ext.Application.process_update`.
        pattern (`Pattern`): Optional. Regex pattern to test
            :attr:`telegram.ChosenInlineResult.result_id` against.

            .. versionadded:: 13.6

    """

    __slots__ = ("pattern",)

    def __init__(
        self: "ChosenInlineResultHandler[CCT, RT]",
        callback: HandlerCallback[Update, CCT, RT],
        block: DVType[bool] = DEFAULT_TRUE,
        pattern: str | Pattern[str] | None = None,
    ):
        super().__init__(callback, block=block)

        if isinstance(pattern, str):
            pattern = re.compile(pattern)

        self.pattern: str | Pattern[str] | None = pattern

    def check_update(self, update: object) -> bool | object | None:
        """Determines whether an update should be passed to this handler's :attr:`callback`.

        Args:
            update (:class:`telegram.Update` | :obj:`object`): Incoming update.

        Returns:
            :obj:`bool` | :obj:`re.match`

        """
        if isinstance(update, Update) and update.chosen_inline_result:
            if self.pattern:
                if match := re.match(self.pattern, update.chosen_inline_result.result_id):
                    return match
            else:
                return True
        return None

    def collect_additional_context(
        self,
        context: CCT,
        update: Update,  # noqa: ARG002
        application: "Application[Any, CCT, Any, Any, Any, Any]",  # noqa: ARG002
        check_result: bool | Match[str],
    ) -> None:
        """This function adds the matched regex pattern result to
        :attr:`telegram.ext.CallbackContext.matches`.
        """
        if self.pattern:
            check_result = cast("Match", check_result)
            context.matches = [check_result]
