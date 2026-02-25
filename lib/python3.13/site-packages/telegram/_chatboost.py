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
"""This module contains the classes that represent Telegram ChatBoosts."""

import datetime as dtm
from collections.abc import Sequence
from typing import TYPE_CHECKING, Final

from telegram import constants
from telegram._chat import Chat
from telegram._telegramobject import TelegramObject
from telegram._user import User
from telegram._utils import enum
from telegram._utils.argumentparsing import de_json_optional, de_list_optional, parse_sequence_arg
from telegram._utils.datetime import extract_tzinfo_from_defaults, from_timestamp
from telegram._utils.types import JSONDict

if TYPE_CHECKING:
    from telegram import Bot


class ChatBoostAdded(TelegramObject):
    """
    This object represents a service message about a user boosting a chat.

    Objects of this class are comparable in terms of equality.
    Two objects of this class are considered equal, if their
    :attr:`boost_count` are equal.

    .. versionadded:: 21.0

    Args:
        boost_count (:obj:`int`): Number of boosts added by the user.

    Attributes:
        boost_count (:obj:`int`): Number of boosts added by the user.

    """

    __slots__ = ("boost_count",)

    def __init__(
        self,
        boost_count: int,
        *,
        api_kwargs: JSONDict | None = None,
    ) -> None:
        super().__init__(api_kwargs=api_kwargs)
        self.boost_count: int = boost_count
        self._id_attrs = (self.boost_count,)

        self._freeze()


class ChatBoostSource(TelegramObject):
    """
    Base class for Telegram ChatBoostSource objects. It can be one of:

    * :class:`telegram.ChatBoostSourcePremium`
    * :class:`telegram.ChatBoostSourceGiftCode`
    * :class:`telegram.ChatBoostSourceGiveaway`

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :attr:`source` is equal.

    .. versionadded:: 20.8

    Args:
        source (:obj:`str`): The source of the chat boost. Can be one of:
            :attr:`~telegram.ChatBoostSource.PREMIUM`, :attr:`~telegram.ChatBoostSource.GIFT_CODE`,
            or :attr:`~telegram.ChatBoostSource.GIVEAWAY`.

    Attributes:
        source (:obj:`str`): The source of the chat boost. Can be one of:
            :attr:`~telegram.ChatBoostSource.PREMIUM`, :attr:`~telegram.ChatBoostSource.GIFT_CODE`,
            or :attr:`~telegram.ChatBoostSource.GIVEAWAY`.
    """

    __slots__ = ("source",)

    PREMIUM: Final[str] = constants.ChatBoostSources.PREMIUM
    """:const:`telegram.constants.ChatBoostSources.PREMIUM`"""
    GIFT_CODE: Final[str] = constants.ChatBoostSources.GIFT_CODE
    """:const:`telegram.constants.ChatBoostSources.GIFT_CODE`"""
    GIVEAWAY: Final[str] = constants.ChatBoostSources.GIVEAWAY
    """:const:`telegram.constants.ChatBoostSources.GIVEAWAY`"""

    def __init__(self, source: str, *, api_kwargs: JSONDict | None = None):
        super().__init__(api_kwargs=api_kwargs)

        # Required by all subclasses:
        self.source: str = enum.get_member(constants.ChatBoostSources, source, source)

        self._id_attrs = (self.source,)
        self._freeze()

    @classmethod
    def de_json(cls, data: JSONDict, bot: "Bot | None" = None) -> "ChatBoostSource":
        """See :meth:`telegram.TelegramObject.de_json`."""
        data = cls._parse_data(data)

        _class_mapping: dict[str, type[ChatBoostSource]] = {
            cls.PREMIUM: ChatBoostSourcePremium,
            cls.GIFT_CODE: ChatBoostSourceGiftCode,
            cls.GIVEAWAY: ChatBoostSourceGiveaway,
        }

        if cls is ChatBoostSource and data.get("source") in _class_mapping:
            return _class_mapping[data.pop("source")].de_json(data=data, bot=bot)

        if "user" in data:
            data["user"] = de_json_optional(data.get("user"), User, bot)

        return super().de_json(data=data, bot=bot)


class ChatBoostSourcePremium(ChatBoostSource):
    """
    The boost was obtained by subscribing to Telegram Premium or by gifting a Telegram Premium
    subscription to another user.

    .. versionadded:: 20.8

    Args:
        user (:class:`telegram.User`): User that boosted the chat.

    Attributes:
        source (:obj:`str`): The source of the chat boost. Always
            :attr:`~telegram.ChatBoostSource.PREMIUM`.
        user (:class:`telegram.User`): User that boosted the chat.
    """

    __slots__ = ("user",)

    def __init__(self, user: User, *, api_kwargs: JSONDict | None = None):
        super().__init__(source=self.PREMIUM, api_kwargs=api_kwargs)

        with self._unfrozen():
            self.user: User = user


class ChatBoostSourceGiftCode(ChatBoostSource):
    """
    The boost was obtained by the creation of Telegram Premium gift codes to boost a chat. Each
    such code boosts the chat 4 times for the duration of the corresponding Telegram Premium
    subscription.

    .. versionadded:: 20.8

    Args:
        user (:class:`telegram.User`): User for which the gift code was created.

    Attributes:
        source (:obj:`str`): The source of the chat boost. Always
            :attr:`~telegram.ChatBoostSource.GIFT_CODE`.
        user (:class:`telegram.User`): User for which the gift code was created.
    """

    __slots__ = ("user",)

    def __init__(self, user: User, *, api_kwargs: JSONDict | None = None):
        super().__init__(source=self.GIFT_CODE, api_kwargs=api_kwargs)

        with self._unfrozen():
            self.user: User = user


class ChatBoostSourceGiveaway(ChatBoostSource):
    """
    The boost was obtained by the creation of a Telegram Premium giveaway or a Telegram Star.
    This boosts the chat 4 times for the duration of the corresponding Telegram Premium
    subscription for Telegram Premium giveaways and :attr:`prize_star_count` / 500 times for
    one year for Telegram Star giveaways.

    .. versionadded:: 20.8

    Args:
        giveaway_message_id (:obj:`int`): Identifier of a message in the chat with the giveaway;
            the message could have been deleted already. May be 0 if the message isn't sent yet.
        user (:class:`telegram.User`, optional): User that won the prize in the giveaway if any;
            for Telegram Premium giveaways only.
        prize_star_count (:obj:`int`, optional): The number of Telegram Stars to be split between
            giveaway winners; for Telegram Star giveaways only.

            .. versionadded:: 21.6
        is_unclaimed (:obj:`bool`, optional): :obj:`True`, if the giveaway was completed, but
            there was no user to win the prize.

    Attributes:
        source (:obj:`str`): Source of the boost. Always
            :attr:`~telegram.ChatBoostSource.GIVEAWAY`.
        giveaway_message_id (:obj:`int`): Identifier of a message in the chat with the giveaway;
            the message could have been deleted already. May be 0 if the message isn't sent yet.
        user (:class:`telegram.User`): Optional. User that won the prize in the giveaway if any.
        prize_star_count (:obj:`int`): Optional. The number of Telegram Stars to be split between
            giveaway winners; for Telegram Star giveaways only.

            .. versionadded:: 21.6
        is_unclaimed (:obj:`bool`): Optional. :obj:`True`, if the giveaway was completed, but
            there was no user to win the prize.
    """

    __slots__ = ("giveaway_message_id", "is_unclaimed", "prize_star_count", "user")

    def __init__(
        self,
        giveaway_message_id: int,
        user: User | None = None,
        is_unclaimed: bool | None = None,
        prize_star_count: int | None = None,
        *,
        api_kwargs: JSONDict | None = None,
    ):
        super().__init__(source=self.GIVEAWAY, api_kwargs=api_kwargs)

        with self._unfrozen():
            self.giveaway_message_id: int = giveaway_message_id
            self.user: User | None = user
            self.prize_star_count: int | None = prize_star_count
            self.is_unclaimed: bool | None = is_unclaimed


class ChatBoost(TelegramObject):
    """
    This object contains information about a chat boost.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :attr:`boost_id`, :attr:`add_date`, :attr:`expiration_date`,
    and :attr:`source` are equal.

    .. versionadded:: 20.8

    Args:
        boost_id (:obj:`str`): Unique identifier of the boost.
        add_date (:obj:`datetime.datetime`): Point in time when the chat was boosted.
        expiration_date (:obj:`datetime.datetime`): Point in time when the boost
            will automatically expire, unless the booster's Telegram Premium subscription is
            prolonged.
        source (:class:`telegram.ChatBoostSource`): Source of the added boost.

    Attributes:
        boost_id (:obj:`str`): Unique identifier of the boost.
        add_date (:obj:`datetime.datetime`): Point in time when the chat was boosted.
            |datetime_localization|
        expiration_date (:obj:`datetime.datetime`): Point in time when the boost
            will automatically expire, unless the booster's Telegram Premium subscription is
            prolonged. |datetime_localization|
        source (:class:`telegram.ChatBoostSource`): Source of the added boost.
    """

    __slots__ = ("add_date", "boost_id", "expiration_date", "source")

    def __init__(
        self,
        boost_id: str,
        add_date: dtm.datetime,
        expiration_date: dtm.datetime,
        source: ChatBoostSource,
        *,
        api_kwargs: JSONDict | None = None,
    ):
        super().__init__(api_kwargs=api_kwargs)

        self.boost_id: str = boost_id
        self.add_date: dtm.datetime = add_date
        self.expiration_date: dtm.datetime = expiration_date
        self.source: ChatBoostSource = source

        self._id_attrs = (self.boost_id, self.add_date, self.expiration_date, self.source)
        self._freeze()

    @classmethod
    def de_json(cls, data: JSONDict, bot: "Bot | None" = None) -> "ChatBoost":
        """See :meth:`telegram.TelegramObject.de_json`."""
        data = cls._parse_data(data)

        data["source"] = de_json_optional(data.get("source"), ChatBoostSource, bot)
        loc_tzinfo = extract_tzinfo_from_defaults(bot)
        data["add_date"] = from_timestamp(data.get("add_date"), tzinfo=loc_tzinfo)
        data["expiration_date"] = from_timestamp(data.get("expiration_date"), tzinfo=loc_tzinfo)

        return super().de_json(data=data, bot=bot)


class ChatBoostUpdated(TelegramObject):
    """This object represents a boost added to a chat or changed.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :attr:`chat`, and :attr:`boost` are equal.

    .. versionadded:: 20.8

    Args:
        chat (:class:`telegram.Chat`): Chat which was boosted.
        boost (:class:`telegram.ChatBoost`): Information about the chat boost.

    Attributes:
        chat (:class:`telegram.Chat`): Chat which was boosted.
        boost (:class:`telegram.ChatBoost`): Information about the chat boost.
    """

    __slots__ = ("boost", "chat")

    def __init__(
        self,
        chat: Chat,
        boost: ChatBoost,
        *,
        api_kwargs: JSONDict | None = None,
    ):
        super().__init__(api_kwargs=api_kwargs)

        self.chat: Chat = chat
        self.boost: ChatBoost = boost

        self._id_attrs = (self.chat.id, self.boost)
        self._freeze()

    @classmethod
    def de_json(cls, data: JSONDict, bot: "Bot | None" = None) -> "ChatBoostUpdated":
        """See :meth:`telegram.TelegramObject.de_json`."""
        data = cls._parse_data(data)

        data["chat"] = de_json_optional(data.get("chat"), Chat, bot)
        data["boost"] = de_json_optional(data.get("boost"), ChatBoost, bot)

        return super().de_json(data=data, bot=bot)


class ChatBoostRemoved(TelegramObject):
    """
    This object represents a boost removed from a chat.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :attr:`chat`, :attr:`boost_id`, :attr:`remove_date`, and
    :attr:`source` are equal.

    Args:
        chat (:class:`telegram.Chat`): Chat which was boosted.
        boost_id (:obj:`str`): Unique identifier of the boost.
        remove_date (:obj:`datetime.datetime`): Point in time when the boost was removed.
        source (:class:`telegram.ChatBoostSource`): Source of the removed boost.

    Attributes:
        chat (:class:`telegram.Chat`): Chat which was boosted.
        boost_id (:obj:`str`): Unique identifier of the boost.
        remove_date (:obj:`datetime.datetime`): Point in time when the boost was removed.
            |datetime_localization|
        source (:class:`telegram.ChatBoostSource`): Source of the removed boost.
    """

    __slots__ = ("boost_id", "chat", "remove_date", "source")

    def __init__(
        self,
        chat: Chat,
        boost_id: str,
        remove_date: dtm.datetime,
        source: ChatBoostSource,
        *,
        api_kwargs: JSONDict | None = None,
    ):
        super().__init__(api_kwargs=api_kwargs)

        self.chat: Chat = chat
        self.boost_id: str = boost_id
        self.remove_date: dtm.datetime = remove_date
        self.source: ChatBoostSource = source

        self._id_attrs = (self.chat, self.boost_id, self.remove_date, self.source)
        self._freeze()

    @classmethod
    def de_json(cls, data: JSONDict, bot: "Bot | None" = None) -> "ChatBoostRemoved":
        """See :meth:`telegram.TelegramObject.de_json`."""
        data = cls._parse_data(data)

        data["chat"] = de_json_optional(data.get("chat"), Chat, bot)
        data["source"] = de_json_optional(data.get("source"), ChatBoostSource, bot)
        loc_tzinfo = extract_tzinfo_from_defaults(bot)
        data["remove_date"] = from_timestamp(data.get("remove_date"), tzinfo=loc_tzinfo)

        return super().de_json(data=data, bot=bot)


class UserChatBoosts(TelegramObject):
    """This object represents a list of boosts added to a chat by a user.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :attr:`boosts` are equal.

    .. versionadded:: 20.8

    Args:
        boosts (Sequence[:class:`telegram.ChatBoost`]): List of boosts added to the chat by the
            user.

    Attributes:
        boosts (tuple[:class:`telegram.ChatBoost`]): List of boosts added to the chat by the user.
    """

    __slots__ = ("boosts",)

    def __init__(
        self,
        boosts: Sequence[ChatBoost],
        *,
        api_kwargs: JSONDict | None = None,
    ):
        super().__init__(api_kwargs=api_kwargs)

        self.boosts: tuple[ChatBoost, ...] = parse_sequence_arg(boosts)

        self._id_attrs = (self.boosts,)
        self._freeze()

    @classmethod
    def de_json(cls, data: JSONDict, bot: "Bot | None" = None) -> "UserChatBoosts":
        """See :meth:`telegram.TelegramObject.de_json`."""
        data = cls._parse_data(data)

        data["boosts"] = de_list_optional(data.get("boosts"), ChatBoost, bot)

        return super().de_json(data=data, bot=bot)
