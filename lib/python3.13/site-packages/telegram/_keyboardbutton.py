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
"""This module contains an object that represents a Telegram KeyboardButton."""

from typing import TYPE_CHECKING

from telegram._keyboardbuttonpolltype import KeyboardButtonPollType
from telegram._keyboardbuttonrequest import KeyboardButtonRequestChat, KeyboardButtonRequestUsers
from telegram._telegramobject import TelegramObject
from telegram._utils.argumentparsing import de_json_optional
from telegram._utils.types import JSONDict
from telegram._webappinfo import WebAppInfo

if TYPE_CHECKING:
    from telegram import Bot


class KeyboardButton(TelegramObject):
    """
    This object represents one button of the reply keyboard. At most one of the optional fields
    must be used to specify type of the button. For simple text buttons, :obj:`str`
    can be used instead of this object to specify text of the button.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :attr:`text`, :attr:`request_contact`, :attr:`request_location`,
    :attr:`request_poll`, :attr:`web_app`, :attr:`request_users` and :attr:`request_chat` are
    equal.

    Note:
        * Optional fields are mutually exclusive.
        * :attr:`request_contact` and :attr:`request_location` options will only work in Telegram
          versions released after 9 April, 2016. Older clients will display unsupported message.
        * :attr:`request_poll` option will only work in Telegram versions released after 23
          January, 2020. Older clients will display unsupported message.
        * :attr:`web_app` option will only work in Telegram versions released after 16 April, 2022.
          Older clients will display unsupported message.
        * :attr:`request_users` and :attr:`request_chat` options will only work in Telegram
          versions released after 3 February, 2023. Older clients will display unsupported
          message.

    .. versionchanged:: 21.0
       Removed deprecated argument and attribute ``request_user``.
    .. versionchanged:: 20.0
       :attr:`web_app` is considered as well when comparing objects of this type in terms of
       equality.
    .. versionchanged:: 20.5
       :attr:`request_users` and :attr:`request_chat` are considered as well when
       comparing objects of this type in terms of equality.

    Args:
        text (:obj:`str`): Text of the button. If none of the optional fields are used, it will be
            sent to the bot as a message when the button is pressed.
        request_contact (:obj:`bool`, optional): If :obj:`True`, the user's phone number will be
            sent as a contact when the button is pressed. Available in private chats only.
        request_location (:obj:`bool`, optional): If :obj:`True`, the user's current location will
            be sent when the button is pressed. Available in private chats only.
        request_poll (:class:`~telegram.KeyboardButtonPollType`, optional): If specified, the user
            will be asked to create a poll and send it to the bot when the button is pressed.
            Available in private chats only.
        web_app (:class:`~telegram.WebAppInfo`, optional): If specified, the described `Web App
            <https://core.telegram.org/bots/webapps>`_ will be launched when the button is pressed.
            The Web App will be able to send a :attr:`Message.web_app_data` service message.
            Available in private chats only.

            .. versionadded:: 20.0

        request_users (:class:`KeyboardButtonRequestUsers`, optional): If specified, pressing the
            button will open a list of suitable users. Tapping on any user will send its
            identifier to the bot in a :attr:`telegram.Message.users_shared` service message.
            Available in private chats only.

            .. versionadded:: 20.8
        request_chat (:class:`KeyboardButtonRequestChat`, optional): If specified, pressing the
            button will open a list of suitable chats. Tapping on a chat will send its
            identifier to the bot in a :attr:`telegram.Message.chat_shared` service message.
            Available in private chats only.

            .. versionadded:: 20.1
    Attributes:
        text (:obj:`str`): Text of the button. If none of the optional fields are used, it will be
            sent to the bot as a message when the button is pressed.
        request_contact (:obj:`bool`): Optional. If :obj:`True`, the user's phone number will be
            sent as a contact when the button is pressed. Available in private chats only.
        request_location (:obj:`bool`): Optional. If :obj:`True`, the user's current location will
            be sent when the button is pressed. Available in private chats only.
        request_poll (:class:`~telegram.KeyboardButtonPollType`): Optional. If specified,
            the user will be asked to create a poll and send it to the bot when the button is
            pressed. Available in private chats only.
        web_app (:class:`~telegram.WebAppInfo`): Optional. If specified, the described `Web App
            <https://core.telegram.org/bots/webapps>`_ will be launched when the button is pressed.
            The Web App will be able to send a :attr:`Message.web_app_data` service message.
            Available in private chats only.

            .. versionadded:: 20.0
        request_users (:class:`KeyboardButtonRequestUsers`): Optional. If specified, pressing the
            button will open a list of suitable users. Tapping on any user will send its
            identifier to the bot in a :attr:`telegram.Message.users_shared` service message.
            Available in private chats only.

            .. versionadded:: 20.8
        request_chat (:class:`KeyboardButtonRequestChat`): Optional. If specified, pressing the
            button will open a list of suitable chats. Tapping on a chat will send its
            identifier to the bot in a :attr:`telegram.Message.chat_shared` service message.
            Available in private chats only.

            .. versionadded:: 20.1
    """

    __slots__ = (
        "request_chat",
        "request_contact",
        "request_location",
        "request_poll",
        "request_users",
        "text",
        "web_app",
    )

    def __init__(
        self,
        text: str,
        request_contact: bool | None = None,
        request_location: bool | None = None,
        request_poll: KeyboardButtonPollType | None = None,
        web_app: WebAppInfo | None = None,
        request_chat: KeyboardButtonRequestChat | None = None,
        request_users: KeyboardButtonRequestUsers | None = None,
        *,
        api_kwargs: JSONDict | None = None,
    ):
        super().__init__(api_kwargs=api_kwargs)

        # Required
        self.text: str = text
        # Optionals
        self.request_contact: bool | None = request_contact
        self.request_location: bool | None = request_location
        self.request_poll: KeyboardButtonPollType | None = request_poll
        self.web_app: WebAppInfo | None = web_app
        self.request_users: KeyboardButtonRequestUsers | None = request_users
        self.request_chat: KeyboardButtonRequestChat | None = request_chat

        self._id_attrs = (
            self.text,
            self.request_contact,
            self.request_location,
            self.request_poll,
            self.web_app,
            self.request_users,
            self.request_chat,
        )

        self._freeze()

    @classmethod
    def de_json(cls, data: JSONDict, bot: "Bot | None" = None) -> "KeyboardButton":
        """See :meth:`telegram.TelegramObject.de_json`."""
        data = cls._parse_data(data)

        data["request_poll"] = de_json_optional(
            data.get("request_poll"), KeyboardButtonPollType, bot
        )
        data["request_users"] = de_json_optional(
            data.get("request_users"), KeyboardButtonRequestUsers, bot
        )
        data["request_chat"] = de_json_optional(
            data.get("request_chat"), KeyboardButtonRequestChat, bot
        )
        data["web_app"] = de_json_optional(data.get("web_app"), WebAppInfo, bot)

        api_kwargs = {}
        # This is a deprecated field that TG still returns for backwards compatibility
        # Let's filter it out to speed up the de-json process
        if request_user := data.get("request_user"):
            api_kwargs = {"request_user": request_user}

        return super()._de_json(data=data, bot=bot, api_kwargs=api_kwargs)
