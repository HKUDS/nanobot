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
"""This module contains the MessageHandler class."""

from typing import TYPE_CHECKING, Any, TypeVar

from telegram import Update
from telegram._utils.defaultvalue import DEFAULT_TRUE
from telegram._utils.types import DVType
from telegram.ext import filters as filters_module
from telegram.ext._handlers.basehandler import BaseHandler
from telegram.ext._utils.types import CCT, HandlerCallback

if TYPE_CHECKING:
    from telegram.ext import Application

RT = TypeVar("RT")


class MessageHandler(BaseHandler[Update, CCT, RT]):
    """Handler class to handle Telegram messages. They might contain text, media or status
    updates.

    Warning:
        When setting :paramref:`block` to :obj:`False`, you cannot rely on adding custom
        attributes to :class:`telegram.ext.CallbackContext`. See its docs for more info.

    Args:
        filters (:class:`telegram.ext.filters.BaseFilter`): A filter inheriting from
            :class:`telegram.ext.filters.BaseFilter`. Standard filters can be found in
            :mod:`telegram.ext.filters`. Filters can be combined using bitwise
            operators (& for and, | for or, ~ for not). Passing :obj:`None` is a shortcut
            to passing :class:`telegram.ext.filters.ALL`.

            .. seealso:: :wiki:`Advanced Filters <Extensions---Advanced-Filters>`
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

    Attributes:
        filters (:class:`telegram.ext.filters.BaseFilter`): Only allow updates with these Filters.
            See :mod:`telegram.ext.filters` for a full list of all available filters.
        callback (:term:`coroutine function`): The callback function for this handler.
        block (:obj:`bool`): Determines whether the return value of the callback should be
            awaited before processing the next handler in
            :meth:`telegram.ext.Application.process_update`.

    """

    __slots__ = ("filters",)

    def __init__(
        self: "MessageHandler[CCT, RT]",
        filters: filters_module.BaseFilter | None,
        callback: HandlerCallback[Update, CCT, RT],
        block: DVType[bool] = DEFAULT_TRUE,
    ):
        super().__init__(callback, block=block)
        self.filters: filters_module.BaseFilter = (
            filters if filters is not None else filters_module.ALL
        )

    def check_update(self, update: object) -> bool | dict[str, list[Any]] | None:
        """Determines whether an update should be passed to this handler's :attr:`callback`.

        Args:
            update (:class:`telegram.Update` | :obj:`object`): Incoming update.

        Returns:
            :obj:`bool`

        """
        if isinstance(update, Update):
            return self.filters.check_update(update) or False
        return None

    def collect_additional_context(
        self,
        context: CCT,
        update: Update,  # noqa: ARG002
        application: "Application[Any, CCT, Any, Any, Any, Any]",  # noqa: ARG002
        check_result: bool | dict[str, object] | None,
    ) -> None:
        """Adds possible output of data filters to the :class:`CallbackContext`."""
        if isinstance(check_result, dict):
            context.update(check_result)
