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
"""This module contains an object that represents a Telegram ReplyKeyboardRemove."""

from telegram._telegramobject import TelegramObject
from telegram._utils.types import JSONDict


class ReplyKeyboardRemove(TelegramObject):
    """
    Upon receiving a message with this object, Telegram clients will remove the current custom
    keyboard and display the default letter-keyboard. By default, custom keyboards are displayed
    until a new keyboard is sent by a bot. An exception is made for one-time keyboards that are
    hidden immediately after the user presses a button (see :class:`telegram.ReplyKeyboardMarkup`).
    Not supported in channels and for messages sent on behalf of a Telegram Business account.

    Note:
        User will not be able to summon this keyboard; if you want to hide the keyboard from
        sight but keep it accessible, use :attr:`telegram.ReplyKeyboardMarkup.one_time_keyboard`.

    Examples:
        * Example usage: A user votes in a poll, bot returns confirmation message in reply to
          the vote and removes the keyboard for that user, while still showing the keyboard with
          poll options to users who haven't voted yet.
        * :any:`Conversation Bot <examples.conversationbot>`
        * :any:`Conversation Bot 2 <examples.conversationbot2>`

    Args:
        selective (:obj:`bool`, optional): Use this parameter if you want to remove the keyboard
            for specific users only. Targets:

            1) Users that are @mentioned in the text of the :class:`telegram.Message` object.
            2) If the bot's message is a reply to a message in the same chat and forum topic,
               sender of the original message.

    Attributes:
        remove_keyboard (:obj:`True`): Requests clients to remove the custom keyboard.
        selective (:obj:`bool`): Optional. Remove the keyboard for specific users only.
            Targets:

            1) Users that are @mentioned in the text of the :class:`telegram.Message` object.
            2) If the bot's message is a reply to a message in the same chat and forum topic,
                sender of the original message.

    """

    __slots__ = ("remove_keyboard", "selective")

    def __init__(self, selective: bool | None = None, *, api_kwargs: JSONDict | None = None):
        super().__init__(api_kwargs=api_kwargs)
        # Required
        self.remove_keyboard: bool = True
        # Optionals
        self.selective: bool | None = selective

        self._freeze()
