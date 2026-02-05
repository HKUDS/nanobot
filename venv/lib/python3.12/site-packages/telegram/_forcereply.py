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
"""This module contains an object that represents a Telegram ForceReply."""

from typing import Final

from telegram import constants
from telegram._telegramobject import TelegramObject
from telegram._utils.types import JSONDict


class ForceReply(TelegramObject):
    """
    Upon receiving a message with this object, Telegram clients will display a reply interface to
    the user (act as if the user has selected the bot's message and tapped 'Reply'). This can be
    extremely useful if you want to create user-friendly step-by-step interfaces without having
    to sacrifice `privacy mode <https://core.telegram.org/bots/features#privacy-mode>`_. Not
    supported in channels and for messages sent on behalf of a Telegram Business account.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :attr:`selective` is equal.

    .. versionchanged:: 20.0
        The (undocumented) argument ``force_reply`` was removed and instead :attr:`force_reply`
        is now always set to :obj:`True` as expected by the Bot API.

    Args:
        selective (:obj:`bool`, optional): Use this parameter if you want to force reply from
            specific users only. Targets:

            1) Users that are @mentioned in the :attr:`~telegram.Message.text` of the
               :class:`telegram.Message` object.
            2) If the bot's message is a reply to a message in the same chat and forum topic,
               sender of the original message.

        input_field_placeholder (:obj:`str`, optional): The placeholder to be shown in the input
            field when the reply is active;
            :tg-const:`telegram.ForceReply.MIN_INPUT_FIELD_PLACEHOLDER`-
            :tg-const:`telegram.ForceReply.MAX_INPUT_FIELD_PLACEHOLDER`
            characters.

            .. versionadded:: 13.7

    Attributes:
        force_reply (:obj:`True`): Shows reply interface to the user, as if they manually selected
            the bots message and tapped 'Reply'.
        selective (:obj:`bool`): Optional. Force reply from specific users only. Targets:

            1) Users that are @mentioned in the :attr:`~telegram.Message.text` of the
               :class:`telegram.Message` object.
            2) If the bot's message is a reply to a message in the same chat and forum topic,
                sender of the original message.
        input_field_placeholder (:obj:`str`): Optional. The placeholder to be shown in the input
            field when the reply is active;
            :tg-const:`telegram.ForceReply.MIN_INPUT_FIELD_PLACEHOLDER`-
            :tg-const:`telegram.ForceReply.MAX_INPUT_FIELD_PLACEHOLDER`
            characters.

            .. versionadded:: 13.7

    """

    __slots__ = ("force_reply", "input_field_placeholder", "selective")

    def __init__(
        self,
        selective: bool | None = None,
        input_field_placeholder: str | None = None,
        *,
        api_kwargs: JSONDict | None = None,
    ):
        super().__init__(api_kwargs=api_kwargs)
        self.force_reply: bool = True
        self.selective: bool | None = selective
        self.input_field_placeholder: str | None = input_field_placeholder

        self._id_attrs = (self.selective,)

        self._freeze()

    MIN_INPUT_FIELD_PLACEHOLDER: Final[int] = constants.ReplyLimit.MIN_INPUT_FIELD_PLACEHOLDER
    """:const:`telegram.constants.ReplyLimit.MIN_INPUT_FIELD_PLACEHOLDER`

    .. versionadded:: 20.0
    """
    MAX_INPUT_FIELD_PLACEHOLDER: Final[int] = constants.ReplyLimit.MAX_INPUT_FIELD_PLACEHOLDER
    """:const:`telegram.constants.ReplyLimit.MAX_INPUT_FIELD_PLACEHOLDER`

    .. versionadded:: 20.0
    """
