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
"""This module contains an object that represents a Telegram LoginUrl."""

from telegram._telegramobject import TelegramObject
from telegram._utils.types import JSONDict


class LoginUrl(TelegramObject):
    """This object represents a parameter of the inline keyboard button used to automatically
    authorize a user. Serves as a great replacement for the Telegram Login Widget when the user is
    coming from Telegram. All the user needs to do is tap/click a button and confirm that they want
    to log in. Telegram apps support these buttons as of version 5.7.

    Sample bot: `@discussbot <https://t.me/discussbot>`_

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :attr:`url` is equal.

    Note:
        You must always check the hash of the received data to verify the authentication
        and the integrity of the data as described in
        `Checking authorization <https://core.telegram.org/widgets/login#checking-authorization>`_

    Args:
        url (:obj:`str`): An HTTPS URL to be opened with user authorization data added to the query
            string when the button is pressed. If the user refuses to provide authorization data,
            the original URL without information about the user will be opened. The data added is
            the same as described in
            `Receiving authorization data
            <https://core.telegram.org/widgets/login#receiving-authorization-data>`_.
        forward_text (:obj:`str`, optional): New text of the button in forwarded messages.
        bot_username (:obj:`str`, optional): Username of a bot, which will be used for user
            authorization. See
            `Setting up a bot <https://core.telegram.org/widgets/login#setting-up-a-bot>`_
            for more details. If not specified, the current
            bot's username will be assumed. The url's domain must be the same as the domain linked
            with the bot. See
            `Linking your domain to the bot
            <https://core.telegram.org/widgets/login#linking-your-domain-to-the-bot>`_
            for more details.
        request_write_access (:obj:`bool`, optional): Pass :obj:`True` to request the permission
            for your bot to send messages to the user.

    Attributes:
        url (:obj:`str`): An HTTPS URL to be opened with user authorization data added to the query
            string when the button is pressed. If the user refuses to provide authorization data,
            the original URL without information about the user will be opened. The data added is
            the same as described in
            `Receiving authorization data
            <https://core.telegram.org/widgets/login#receiving-authorization-data>`_.
        forward_text (:obj:`str`): Optional. New text of the button in forwarded messages.
        bot_username (:obj:`str`): Optional. Username of a bot, which will be used for user
            authorization. See
            `Setting up a bot <https://core.telegram.org/widgets/login#setting-up-a-bot>`_
            for more details. If not specified, the current
            bot's username will be assumed. The url's domain must be the same as the domain linked
            with the bot. See
            `Linking your domain to the bot
            <https://core.telegram.org/widgets/login#linking-your-domain-to-the-bot>`_
            for more details.
        request_write_access (:obj:`bool`): Optional. Pass :obj:`True` to request the permission
            for your bot to send messages to the user.

    """

    __slots__ = ("bot_username", "forward_text", "request_write_access", "url")

    def __init__(
        self,
        url: str,
        forward_text: str | None = None,
        bot_username: str | None = None,
        request_write_access: bool | None = None,
        *,
        api_kwargs: JSONDict | None = None,
    ):
        super().__init__(api_kwargs=api_kwargs)
        # Required
        self.url: str = url
        # Optional
        self.forward_text: str | None = forward_text
        self.bot_username: str | None = bot_username
        self.request_write_access: bool | None = request_write_access

        self._id_attrs = (self.url,)

        self._freeze()
