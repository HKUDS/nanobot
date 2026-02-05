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
"""This module contains an object that represents a Telegram Web App Info."""

from telegram._telegramobject import TelegramObject
from telegram._utils.types import JSONDict


class WebAppInfo(TelegramObject):
    """
    This object contains information about a `Web App <https://core.telegram.org/bots/webapps>`_.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :attr:`url` are equal.

    Examples:
        :any:`Webapp Bot <examples.webappbot>`

    .. versionadded:: 20.0

    Args:
        url (:obj:`str`): An HTTPS URL of a Web App to be opened with additional data as specified
            in `Initializing Web Apps \
            <https://core.telegram.org/bots/webapps#initializing-mini-apps>`_.

    Attributes:
        url (:obj:`str`): An HTTPS URL of a Web App to be opened with additional data as specified
            in `Initializing Web Apps \
            <https://core.telegram.org/bots/webapps#initializing-mini-apps>`_.
    """

    __slots__ = ("url",)

    def __init__(self, url: str, *, api_kwargs: JSONDict | None = None):
        super().__init__(api_kwargs=api_kwargs)
        # Required
        self.url: str = url

        self._id_attrs = (self.url,)

        self._freeze()
