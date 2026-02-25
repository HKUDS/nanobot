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
"""This module contains an object that represents a change in the Telegram message auto
deletion.
"""

import datetime as dtm

from telegram._telegramobject import TelegramObject
from telegram._utils.argumentparsing import to_timedelta
from telegram._utils.datetime import get_timedelta_value
from telegram._utils.types import JSONDict, TimePeriod


class MessageAutoDeleteTimerChanged(TelegramObject):
    """This object represents a service message about a change in auto-delete timer settings.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :attr:`message_auto_delete_time` is equal.

    .. versionadded:: 13.4

    Args:
        message_auto_delete_time (:obj:`int` | :class:`datetime.timedelta`): New auto-delete time
            for messages in the chat.

            .. versionchanged:: v22.2
                |time-period-input|

    Attributes:
        message_auto_delete_time (:obj:`int` | :class:`datetime.timedelta`): New auto-delete time
            for messages in the chat.

            .. deprecated:: v22.2
                |time-period-int-deprecated|

    """

    __slots__ = ("_message_auto_delete_time",)

    def __init__(
        self,
        message_auto_delete_time: TimePeriod,
        *,
        api_kwargs: JSONDict | None = None,
    ):
        super().__init__(api_kwargs=api_kwargs)
        self._message_auto_delete_time: dtm.timedelta = to_timedelta(message_auto_delete_time)

        self._id_attrs = (self.message_auto_delete_time,)

        self._freeze()

    @property
    def message_auto_delete_time(self) -> int | dtm.timedelta:
        return get_timedelta_value(  # type: ignore[return-value]
            self._message_auto_delete_time, attribute="message_auto_delete_time"
        )
