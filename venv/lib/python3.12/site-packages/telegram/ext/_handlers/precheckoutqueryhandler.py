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
"""This module contains the PreCheckoutQueryHandler class."""

import re
from re import Pattern
from typing import TypeVar

from telegram import Update
from telegram._utils.defaultvalue import DEFAULT_TRUE
from telegram._utils.types import DVType
from telegram.ext._handlers.basehandler import BaseHandler
from telegram.ext._utils.types import CCT, HandlerCallback

RT = TypeVar("RT")


class PreCheckoutQueryHandler(BaseHandler[Update, CCT, RT]):
    """Handler class to handle Telegram :attr:`telegram.Update.pre_checkout_query`.

    Warning:
        When setting :paramref:`block` to :obj:`False`, you cannot rely on adding custom
        attributes to :class:`telegram.ext.CallbackContext`. See its docs for more info.

    Examples:
        :any:`Payment Bot <examples.paymentbot>`

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
        pattern (:obj:`str` | :func:`re.Pattern <re.compile>`, optional): Optional. Regex pattern
            to test :attr:`telegram.PreCheckoutQuery.invoice_payload` against.

            .. versionadded:: 20.8

    Attributes:
        callback (:term:`coroutine function`): The callback function for this handler.
        block (:obj:`bool`): Determines whether the callback will run in a blocking way..
        pattern (:obj:`str` | :func:`re.Pattern <re.compile>`, optional): Optional. Regex pattern
            to test :attr:`telegram.PreCheckoutQuery.invoice_payload` against.

            .. versionadded:: 20.8

    """

    __slots__ = ("pattern",)

    def __init__(
        self: "PreCheckoutQueryHandler[CCT, RT]",
        callback: HandlerCallback[Update, CCT, RT],
        block: DVType[bool] = DEFAULT_TRUE,
        pattern: str | Pattern[str] | None = None,
    ):
        super().__init__(callback, block=block)

        self.pattern: Pattern[str] | None = re.compile(pattern) if pattern is not None else None

    def check_update(self, update: object) -> bool:
        """Determines whether an update should be passed to this handler's :attr:`callback`.

        Args:
            update (:class:`telegram.Update` | :obj:`object`): Incoming update.

        Returns:
            :obj:`bool`

        """
        if isinstance(update, Update) and update.pre_checkout_query:
            invoice_payload = update.pre_checkout_query.invoice_payload
            if self.pattern:
                if self.pattern.match(invoice_payload):
                    return True
            else:
                return True
        return False
