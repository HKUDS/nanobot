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
# along with this program. If not, see [http://www.gnu.org/licenses/].
"""This module contains the PaidMediaPurchased class."""

from telegram import Update
from telegram._utils.defaultvalue import DEFAULT_TRUE
from telegram._utils.types import SCT, DVType
from telegram.ext._handlers.basehandler import BaseHandler
from telegram.ext._utils._update_parsing import parse_chat_id, parse_username
from telegram.ext._utils.types import CCT, RT, HandlerCallback


class PaidMediaPurchasedHandler(BaseHandler[Update, CCT, RT]):
    """Handler class to handle Telegram
    :attr:`purchased paid media <telegram.Update.purchased_paid_media>`.

    .. versionadded:: 21.6

    Args:
        callback (:term:`coroutine function`): The callback function for this handler. Will be
            called when :meth:`check_update` has determined that an update should be processed by
            this handler. Callback signature::

                async def callback(update: Update, context: CallbackContext)
        user_id (:obj:`int` | Collection[:obj:`int`], optional): Filters requests to allow only
            those which are from the specified user ID(s).

        username (:obj:`str` | Collection[:obj:`str`], optional): Filters requests to allow only
            those which are from the specified username(s).

        block (:obj:`bool`, optional): Determines whether the return value of the callback should
            be awaited before processing the next handler in
            :meth:`telegram.ext.Application.process_update`. Defaults to :obj:`True`.

            .. seealso:: :wiki:`Concurrency`
    Attributes:
        callback (:term:`coroutine function`): The callback function for this handler.
        block (:obj:`bool`): Determines whether the return value of the callback should be
            awaited before processing the next handler in
            :meth:`telegram.ext.Application.process_update`.
    """

    __slots__ = (
        "_user_ids",
        "_usernames",
    )

    def __init__(
        self: "PaidMediaPurchasedHandler[CCT, RT]",
        callback: HandlerCallback[Update, CCT, RT],
        user_id: SCT[int] | None = None,
        username: SCT[str] | None = None,
        block: DVType[bool] = DEFAULT_TRUE,
    ):
        super().__init__(callback, block=block)

        self._user_ids = parse_chat_id(user_id)
        self._usernames = parse_username(username)

    def check_update(self, update: object) -> bool:
        """Determines whether an update should be passed to this handler's :attr:`callback`.

        Args:
            update (:class:`telegram.Update` | :obj:`object`): Incoming update.

        Returns:
            :obj:`bool`

        """
        if not isinstance(update, Update) or not update.purchased_paid_media:
            return False

        if not self._user_ids and not self._usernames:
            return True
        if update.purchased_paid_media.from_user.id in self._user_ids:
            return True
        return update.purchased_paid_media.from_user.username in self._usernames
