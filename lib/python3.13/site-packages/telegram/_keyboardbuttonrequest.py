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
"""This module contains two objects to request chats/users."""

from typing import TYPE_CHECKING

from telegram._chatadministratorrights import ChatAdministratorRights
from telegram._telegramobject import TelegramObject
from telegram._utils.argumentparsing import de_json_optional
from telegram._utils.types import JSONDict

if TYPE_CHECKING:
    from telegram import Bot


class KeyboardButtonRequestUsers(TelegramObject):
    """This object defines the criteria used to request a suitable user. The identifier of the
    selected user will be shared with the bot when the corresponding button is pressed. `More
    about requesting users » <https://core.telegram.org/bots/features#chat-and-user-selection>`_.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :attr:`request_id` is equal.

    .. versionadded:: 20.8
        This class was previously named ``KeyboardButtonRequestUser``.

    Args:
        request_id (:obj:`int`): Signed 32-bit identifier of the request, which will be received
            back in the :class:`telegram.UsersShared` object. Must be unique within the message.
        user_is_bot (:obj:`bool`, optional): Pass :obj:`True` to request a bot, pass :obj:`False`
            to request a regular user. If not specified, no additional restrictions are applied.
        user_is_premium (:obj:`bool`, optional): Pass :obj:`True` to request a premium user, pass
            :obj:`False` to request a non-premium user. If not specified, no additional
            restrictions are applied.
        max_quantity (:obj:`int`, optional): The maximum number of users to be selected;
            :tg-const:`telegram.constants.KeyboardButtonRequestUsersLimit.MIN_QUANTITY` -
            :tg-const:`telegram.constants.KeyboardButtonRequestUsersLimit.MAX_QUANTITY`.
            Defaults to :tg-const:`telegram.constants.KeyboardButtonRequestUsersLimit.MIN_QUANTITY`
            .

            .. versionadded:: 20.8
        request_name (:obj:`bool`, optional): Pass :obj:`True` to request the users' first and last
            name.

            .. versionadded:: 21.1
        request_username (:obj:`bool`, optional): Pass :obj:`True` to request the users' username.

            .. versionadded:: 21.1
        request_photo (:obj:`bool`, optional): Pass :obj:`True` to request the users' photo.

            .. versionadded:: 21.1

    Attributes:
        request_id (:obj:`int`): Identifier of the request.
        user_is_bot (:obj:`bool`): Optional. Pass :obj:`True` to request a bot, pass :obj:`False`
            to request a regular user. If not specified, no additional restrictions are applied.
        user_is_premium (:obj:`bool`): Optional. Pass :obj:`True` to request a premium user, pass
            :obj:`False` to request a non-premium user. If not specified, no additional
            restrictions are applied.
        max_quantity (:obj:`int`): Optional. The maximum number of users to be selected;
            :tg-const:`telegram.constants.KeyboardButtonRequestUsersLimit.MIN_QUANTITY` -
            :tg-const:`telegram.constants.KeyboardButtonRequestUsersLimit.MAX_QUANTITY`.
            Defaults to :tg-const:`telegram.constants.KeyboardButtonRequestUsersLimit.MIN_QUANTITY`
            .

            .. versionadded:: 20.8
        request_name (:obj:`bool`): Optional. Pass :obj:`True` to request the users' first and last
            name.

            .. versionadded:: 21.1
        request_username (:obj:`bool`): Optional. Pass :obj:`True` to request the users' username.

            .. versionadded:: 21.1
        request_photo (:obj:`bool`): Optional. Pass :obj:`True` to request the users' photo.

            .. versionadded:: 21.1

    """

    __slots__ = (
        "max_quantity",
        "request_id",
        "request_name",
        "request_photo",
        "request_username",
        "user_is_bot",
        "user_is_premium",
    )

    def __init__(
        self,
        request_id: int,
        user_is_bot: bool | None = None,
        user_is_premium: bool | None = None,
        max_quantity: int | None = None,
        request_name: bool | None = None,
        request_username: bool | None = None,
        request_photo: bool | None = None,
        *,
        api_kwargs: JSONDict | None = None,
    ):
        super().__init__(api_kwargs=api_kwargs)
        # Required
        self.request_id: int = request_id

        # Optionals
        self.user_is_bot: bool | None = user_is_bot
        self.user_is_premium: bool | None = user_is_premium
        self.max_quantity: int | None = max_quantity
        self.request_name: bool | None = request_name
        self.request_username: bool | None = request_username
        self.request_photo: bool | None = request_photo

        self._id_attrs = (self.request_id,)

        self._freeze()


class KeyboardButtonRequestChat(TelegramObject):
    """This object defines the criteria used to request a suitable chat. The identifier of the
    selected user will be shared with the bot when the corresponding button is pressed. `More
    about requesting users » <https://core.telegram.org/bots/features#chat-and-user-selection>`_.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :attr:`request_id` is equal.

    .. versionadded:: 20.1

    Args:
        request_id (:obj:`int`): Signed 32-bit identifier of the request, which will be received
            back in the :class:`telegram.ChatShared` object. Must be unique within the message.
        chat_is_channel (:obj:`bool`): Pass :obj:`True` to request a channel chat, pass
            :obj:`False` to request a group or a supergroup chat.
        chat_is_forum (:obj:`bool`, optional): Pass :obj:`True` to request a forum supergroup, pass
            :obj:`False` to request a non-forum chat. If not specified, no additional
            restrictions are applied.
        chat_has_username (:obj:`bool`, optional): Pass :obj:`True` to request a supergroup or a
            channel with a username, pass :obj:`False` to request a chat without a username. If
            not specified, no additional restrictions are applied.
        chat_is_created (:obj:`bool`, optional): Pass :obj:`True` to request a chat owned by the
            user. Otherwise, no additional restrictions are applied.
        user_administrator_rights (:class:`ChatAdministratorRights`, optional): Specifies the
            required administrator rights of the user in the chat. If not specified, no additional
            restrictions are applied.
        bot_administrator_rights (:class:`ChatAdministratorRights`, optional): Specifies the
            required administrator rights of the bot in the chat. The rights must be a subset of
            :paramref:`user_administrator_rights`. If not specified, no additional restrictions are
            applied.
        bot_is_member (:obj:`bool`, optional): Pass :obj:`True` to request a chat with the bot
            as a member. Otherwise, no additional restrictions are applied.
        request_title (:obj:`bool`, optional): Pass :obj:`True` to request the chat's title.

            .. versionadded:: 21.1
        request_username (:obj:`bool`, optional): Pass :obj:`True` to request the chat's username.

            .. versionadded:: 21.1
        request_photo (:obj:`bool`, optional): Pass :obj:`True` to request the chat's photo.

            .. versionadded:: 21.1
    Attributes:
        request_id (:obj:`int`): Identifier of the request.
        chat_is_channel (:obj:`bool`): Pass :obj:`True` to request a channel chat, pass
            :obj:`False` to request a group or a supergroup chat.
        chat_is_forum (:obj:`bool`): Optional. Pass :obj:`True` to request a forum supergroup, pass
            :obj:`False` to request a non-forum chat. If not specified, no additional
            restrictions are applied.
        chat_has_username (:obj:`bool`): Optional. Pass :obj:`True` to request a supergroup or a
            channel with a username, pass :obj:`False` to request a chat without a username. If
            not specified, no additional restrictions are applied.
        chat_is_created (:obj:`bool`) Optional. Pass :obj:`True` to request a chat owned by the
            user. Otherwise, no additional restrictions are applied.
        user_administrator_rights (:class:`ChatAdministratorRights`) Optional. Specifies the
            required administrator rights of the user in the chat. If not specified, no additional
            restrictions are applied.
        bot_administrator_rights (:class:`ChatAdministratorRights`) Optional. Specifies the
            required administrator rights of the bot in the chat. The rights must be a subset of
            :attr:`user_administrator_rights`. If not specified, no additional restrictions are
            applied.
        bot_is_member (:obj:`bool`) Optional. Pass :obj:`True` to request a chat with the bot
            as a member. Otherwise, no additional restrictions are applied.
        request_title (:obj:`bool`): Optional. Pass :obj:`True` to request the chat's title.

            .. versionadded:: 21.1
        request_username (:obj:`bool`): Optional. Pass :obj:`True` to request the chat's username.

            .. versionadded:: 21.1
        request_photo (:obj:`bool`): Optional. Pass :obj:`True` to request the chat's photo.

            .. versionadded:: 21.1
    """

    __slots__ = (
        "bot_administrator_rights",
        "bot_is_member",
        "chat_has_username",
        "chat_is_channel",
        "chat_is_created",
        "chat_is_forum",
        "request_id",
        "request_photo",
        "request_title",
        "request_username",
        "user_administrator_rights",
    )

    def __init__(
        self,
        request_id: int,
        chat_is_channel: bool,
        chat_is_forum: bool | None = None,
        chat_has_username: bool | None = None,
        chat_is_created: bool | None = None,
        user_administrator_rights: ChatAdministratorRights | None = None,
        bot_administrator_rights: ChatAdministratorRights | None = None,
        bot_is_member: bool | None = None,
        request_title: bool | None = None,
        request_username: bool | None = None,
        request_photo: bool | None = None,
        *,
        api_kwargs: JSONDict | None = None,
    ):
        super().__init__(api_kwargs=api_kwargs)
        # required
        self.request_id: int = request_id
        self.chat_is_channel: bool = chat_is_channel

        # optional
        self.chat_is_forum: bool | None = chat_is_forum
        self.chat_has_username: bool | None = chat_has_username
        self.chat_is_created: bool | None = chat_is_created
        self.user_administrator_rights: ChatAdministratorRights | None = user_administrator_rights
        self.bot_administrator_rights: ChatAdministratorRights | None = bot_administrator_rights
        self.bot_is_member: bool | None = bot_is_member
        self.request_title: bool | None = request_title
        self.request_username: bool | None = request_username
        self.request_photo: bool | None = request_photo

        self._id_attrs = (self.request_id,)

        self._freeze()

    @classmethod
    def de_json(cls, data: JSONDict, bot: "Bot | None" = None) -> "KeyboardButtonRequestChat":
        """See :meth:`telegram.TelegramObject.de_json`."""
        data = cls._parse_data(data)

        data["user_administrator_rights"] = de_json_optional(
            data.get("user_administrator_rights"), ChatAdministratorRights, bot
        )
        data["bot_administrator_rights"] = de_json_optional(
            data.get("bot_administrator_rights"), ChatAdministratorRights, bot
        )

        return super().de_json(data=data, bot=bot)
