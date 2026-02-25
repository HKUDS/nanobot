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
"""This module contains the ChatBoostHandler class."""

from typing import Final

from telegram import Update
from telegram.ext._handlers.basehandler import BaseHandler
from telegram.ext._utils._update_parsing import parse_chat_id, parse_username
from telegram.ext._utils.types import CCT, RT, HandlerCallback


class ChatBoostHandler(BaseHandler[Update, CCT, RT]):
    """
    Handler class to handle Telegram updates that contain a chat boost.

    Warning:
        When setting :paramref:`block` to :obj:`False`, you cannot rely on adding custom
        attributes to :class:`telegram.ext.CallbackContext`. See its docs for more info.

    .. versionadded:: 20.8

    Args:
        callback (:term:`coroutine function`): The callback function for this handler. Will be
            called when :meth:`check_update` has determined that an update should be processed by
            this handler. Callback signature::

                async def callback(update: Update, context: CallbackContext)

            The return value of the callback is usually ignored except for the special case of
            :class:`telegram.ext.ConversationHandler`.
        chat_boost_types (:obj:`int`, optional): Pass one of
            :attr:`CHAT_BOOST`, :attr:`REMOVED_CHAT_BOOST` or
            :attr:`ANY_CHAT_BOOST` to specify if this handler should handle only updates with
            :attr:`telegram.Update.chat_boost`,
            :attr:`telegram.Update.removed_chat_boost` or both. Defaults to
            :attr:`CHAT_BOOST`.
        chat_id (:obj:`int` | Collection[:obj:`int`], optional): Filters reactions to allow
            only those which happen in the specified chat ID(s).
        chat_username (:obj:`str` | Collection[:obj:`str`], optional): Filters reactions to allow
            only those which happen in the specified username(s).
        block (:obj:`bool`, optional): Determines whether the return value of the callback should
            be awaited before processing the next handler in
            :meth:`telegram.ext.Application.process_update`. Defaults to :obj:`True`.

            .. seealso:: :wiki:`Concurrency`

    Attributes:
        callback (:term:`coroutine function`): The callback function for this handler.
        chat_boost_types (:obj:`int`): Optional. Specifies if this handler should handle only
            updates with :attr:`telegram.Update.chat_boost`,
            :attr:`telegram.Update.removed_chat_boost` or both.
        block (:obj:`bool`): Determines whether the callback will run in a blocking way.
    """

    __slots__ = (
        "_chat_ids",
        "_chat_usernames",
        "chat_boost_types",
    )

    CHAT_BOOST: Final[int] = -1
    """ :obj:`int`: Used as a constant to handle only :attr:`telegram.Update.chat_boost`."""
    REMOVED_CHAT_BOOST: Final[int] = 0
    """:obj:`int`: Used as a constant to handle only :attr:`telegram.Update.removed_chat_boost`."""
    ANY_CHAT_BOOST: Final[int] = 1
    """:obj:`int`: Used as a constant to handle both :attr:`telegram.Update.chat_boost`
    and :attr:`telegram.Update.removed_chat_boost`."""

    def __init__(
        self: "ChatBoostHandler[CCT, RT]",
        callback: HandlerCallback[Update, CCT, RT],
        chat_boost_types: int = CHAT_BOOST,
        chat_id: int | None = None,
        chat_username: str | None = None,
        block: bool = True,
    ):
        super().__init__(callback, block=block)
        self.chat_boost_types: int = chat_boost_types
        self._chat_ids = parse_chat_id(chat_id)
        self._chat_usernames = parse_username(chat_username)

    def check_update(self, update: object) -> bool:
        """Determines whether an update should be passed to this handler's :attr:`callback`.

        Args:
            update (:class:`telegram.Update` | :obj:`object`): Incoming update.

        Returns:
            :obj:`bool`

        """
        if not isinstance(update, Update):
            return False

        if not (update.chat_boost or update.removed_chat_boost):
            return False

        if self.chat_boost_types == self.CHAT_BOOST and not update.chat_boost:
            return False

        if self.chat_boost_types == self.REMOVED_CHAT_BOOST and not update.removed_chat_boost:
            return False

        if not any((self._chat_ids, self._chat_usernames)):
            return True

        # Extract chat and user IDs and usernames from the update for comparison
        chat_id = chat.id if (chat := update.effective_chat) else None
        chat_username = chat.username if chat else None

        return bool(self._chat_ids and (chat_id in self._chat_ids)) or bool(
            self._chat_usernames and (chat_username in self._chat_usernames)
        )
