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
"""This module contains the MessageReactionHandler class."""

from typing import Final

from telegram import Update
from telegram._utils.defaultvalue import DEFAULT_TRUE
from telegram._utils.types import RT, SCT, DVType
from telegram.ext._handlers.basehandler import BaseHandler
from telegram.ext._utils._update_parsing import parse_chat_id, parse_username
from telegram.ext._utils.types import CCT, HandlerCallback


class MessageReactionHandler(BaseHandler[Update, CCT, RT]):
    """Handler class to handle Telegram updates that contain a message reaction.

    Note:
        The following rules apply to both ``username`` and the ``chat_id`` param groups,
        respectively:

         * If none of them are passed, the handler does not filter the update for that specific
            attribute.
         * If a chat ID **or** a username is passed, the updates will be filtered with that
            specific attribute.
         * If a chat ID **and** a username are passed, an update containing **any** of them will be
            filtered.
         * :attr:`telegram.MessageReactionUpdated.actor_chat` is *not* considered for
           :paramref:`user_id` and :paramref:`user_username` filtering.

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
        message_reaction_types (:obj:`int`, optional): Pass one of
            :attr:`MESSAGE_REACTION_UPDATED`, :attr:`MESSAGE_REACTION_COUNT_UPDATED` or
            :attr:`MESSAGE_REACTION` to specify if this handler should handle only updates with
            :attr:`telegram.Update.message_reaction`,
            :attr:`telegram.Update.message_reaction_count` or both. Defaults to
            :attr:`MESSAGE_REACTION`.
        chat_id (:obj:`int` | Collection[:obj:`int`], optional): Filters reactions to allow
            only those which happen in the specified chat ID(s).
        chat_username (:obj:`str` | Collection[:obj:`str`], optional): Filters reactions to allow
            only those which happen in the specified username(s).
        user_id (:obj:`int` | Collection[:obj:`int`], optional): Filters reactions to allow
            only those which are set by the specified chat ID(s) (this can be the chat itself in
            the case of anonymous users, see the
            :paramref:`telegram.MessageReactionUpdated.actor_chat`).
        user_username (:obj:`str` | Collection[:obj:`str`], optional): Filters reactions to allow
            only those which are set by the specified username(s) (this can be the chat itself in
            the case of anonymous users, see the
            :paramref:`telegram.MessageReactionUpdated.actor_chat`).
        block (:obj:`bool`, optional): Determines whether the return value of the callback should
            be awaited before processing the next handler in
            :meth:`telegram.ext.Application.process_update`. Defaults to :obj:`True`.

            .. seealso:: :wiki:`Concurrency`

    Attributes:
        callback (:term:`coroutine function`): The callback function for this handler.
        message_reaction_types (:obj:`int`): Optional. Specifies if this handler should handle only
            updates with :attr:`telegram.Update.message_reaction`,
            :attr:`telegram.Update.message_reaction_count` or both.
        block (:obj:`bool`): Determines whether the callback will run in a blocking way.

    """

    __slots__ = (
        "_chat_ids",
        "_chat_usernames",
        "_user_ids",
        "_user_usernames",
        "message_reaction_types",
    )

    MESSAGE_REACTION_UPDATED: Final[int] = -1
    """:obj:`int`: Used as a constant to handle only :attr:`telegram.Update.message_reaction`."""
    MESSAGE_REACTION_COUNT_UPDATED: Final[int] = 0
    """:obj:`int`: Used as a constant to handle only
    :attr:`telegram.Update.message_reaction_count`."""
    MESSAGE_REACTION: Final[int] = 1
    """:obj:`int`: Used as a constant to handle both :attr:`telegram.Update.message_reaction`
    and :attr:`telegram.Update.message_reaction_count`."""

    def __init__(
        self: "MessageReactionHandler[CCT, RT]",
        callback: HandlerCallback[Update, CCT, RT],
        chat_id: SCT[int] | None = None,
        chat_username: SCT[str] | None = None,
        user_id: SCT[int] | None = None,
        user_username: SCT[str] | None = None,
        message_reaction_types: int = MESSAGE_REACTION,
        block: DVType[bool] = DEFAULT_TRUE,
    ):
        super().__init__(callback, block=block)
        self.message_reaction_types: int = message_reaction_types

        self._chat_ids = parse_chat_id(chat_id)
        self._chat_usernames = parse_username(chat_username)
        if (user_id or user_username) and message_reaction_types in (
            self.MESSAGE_REACTION,
            self.MESSAGE_REACTION_COUNT_UPDATED,
        ):
            raise ValueError(
                "You can not filter for users and include anonymous reactions. Set "
                "`message_reaction_types` to MESSAGE_REACTION_UPDATED."
            )
        self._user_ids = parse_chat_id(user_id)
        self._user_usernames = parse_username(user_username)

    def check_update(self, update: object) -> bool:
        """Determines whether an update should be passed to this handler's :attr:`callback`.

        Args:
            update (:class:`telegram.Update` | :obj:`object`): Incoming update.

        Returns:
            :obj:`bool`

        """
        if not isinstance(update, Update):
            return False

        if not (update.message_reaction or update.message_reaction_count):
            return False

        if (
            self.message_reaction_types == self.MESSAGE_REACTION_UPDATED
            and update.message_reaction_count
        ):
            return False

        if (
            self.message_reaction_types == self.MESSAGE_REACTION_COUNT_UPDATED
            and update.message_reaction
        ):
            return False

        if not any((self._chat_ids, self._chat_usernames, self._user_ids, self._user_usernames)):
            return True

        # Extract chat and user IDs and usernames from the update for comparison
        chat_id = chat.id if (chat := update.effective_chat) else None
        chat_username = chat.username if chat else None
        user_id = user.id if (user := update.effective_user) else None
        user_username = user.username if user else None

        return (
            bool(self._chat_ids and (chat_id in self._chat_ids))
            or bool(self._chat_usernames and (chat_username in self._chat_usernames))
            or bool(self._user_ids and (user_id in self._user_ids))
            or bool(self._user_usernames and (user_username in self._user_usernames))
        )
