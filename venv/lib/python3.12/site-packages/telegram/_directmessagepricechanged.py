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
"""This module contains an object that represents a Direct Message Price."""

from telegram._telegramobject import TelegramObject
from telegram._utils.types import JSONDict


class DirectMessagePriceChanged(TelegramObject):
    """
    Describes a service message about a change in the price of direct messages sent to a channel
    chat.

    .. versionadded:: 22.3

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :attr:`are_direct_messages_enabled`, and
    :attr:`direct_message_star_count` are equal.

    Args:
        are_direct_messages_enabled (:obj:`bool`):
            :obj:`True`, if direct messages are enabled for the channel chat; :obj:`False`
            otherwise.
        direct_message_star_count (:obj:`int`, optional):
            The new number of Telegram Stars that must be paid by users for each direct message
            sent to the channel. Does not apply to users who have been exempted by administrators.
            Defaults to ``0``.

    Attributes:
        are_direct_messages_enabled (:obj:`bool`):
            :obj:`True`, if direct messages are enabled for the channel chat; :obj:`False`
            otherwise.
        direct_message_star_count (:obj:`int`):
            Optional. The new number of Telegram Stars that must be paid by users for each direct
            message sent to the channel. Does not apply to users who have been exempted by
            administrators. Defaults to ``0``.
    """

    __slots__ = ("are_direct_messages_enabled", "direct_message_star_count")

    def __init__(
        self,
        are_direct_messages_enabled: bool,
        direct_message_star_count: int | None = None,
        *,
        api_kwargs: JSONDict | None = None,
    ):
        super().__init__(api_kwargs=api_kwargs)
        self.are_direct_messages_enabled: bool = are_direct_messages_enabled
        self.direct_message_star_count: int | None = direct_message_star_count

        self._id_attrs = (self.are_direct_messages_enabled, self.direct_message_star_count)

        self._freeze()
