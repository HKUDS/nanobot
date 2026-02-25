#!/usr/bin/env python
# pylint: disable=redefined-builtin
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
# along with this program.  If not, see [http://www.gnu.org/licenses/]
"""This module contains classes related to gifs sent by bots."""

from collections.abc import Sequence
from typing import TYPE_CHECKING

from telegram._chat import Chat
from telegram._files.sticker import Sticker
from telegram._messageentity import MessageEntity
from telegram._telegramobject import TelegramObject
from telegram._utils.argumentparsing import de_json_optional, de_list_optional, parse_sequence_arg
from telegram._utils.entities import parse_message_entities, parse_message_entity
from telegram._utils.types import JSONDict

if TYPE_CHECKING:
    from telegram import Bot


class GiftBackground(TelegramObject):
    """This object describes the background of a gift.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal if their :attr:`center_color`, :attr:`edge_color` and :attr:`text_color` are
    equal.

    .. versionadded:: 22.6

    Args:
        center_color (:obj:`int`): Center color of the background in RGB format.
        edge_color (:obj:`int`): Edge color of the background in RGB format.
        text_color (:obj:`int`): Text color of the background in RGB format.

    Attributes:
        center_color (:obj:`int`): Center color of the background in RGB format.
        edge_color (:obj:`int`): Edge color of the background in RGB format.
        text_color (:obj:`int`): Text color of the background in RGB format.

    """

    __slots__ = (
        "center_color",
        "edge_color",
        "text_color",
    )

    def __init__(
        self,
        center_color: int,
        edge_color: int,
        text_color: int,
        *,
        api_kwargs: JSONDict | None = None,
    ):
        super().__init__(api_kwargs=api_kwargs)
        self.center_color: int = center_color
        self.edge_color: int = edge_color
        self.text_color: int = text_color

        self._id_attrs = (
            self.center_color,
            self.edge_color,
            self.text_color,
        )

        self._freeze()


class Gift(TelegramObject):
    """This object represents a gift that can be sent by the bot.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal if their :attr:`id` is equal.

    .. versionadded:: 21.8

    Args:
        id (:obj:`str`): Unique identifier of the gift.
        sticker (:class:`~telegram.Sticker`): The sticker that represents the gift.
        star_count (:obj:`int`): The number of Telegram Stars that must be paid to send the
            sticker.
        total_count (:obj:`int`, optional): The total number of the gifts of this type that can be
            sent by all users; for limited gifts only.
        remaining_count (:obj:`int`, optional): The number of remaining gifts of this type that can
            be sent by all users; for limited gifts only.
        upgrade_star_count (:obj:`int`, optional): The number of Telegram Stars that must be paid
            to upgrade the gift to a unique one.

            .. versionadded:: 21.10
        publisher_chat (:class:`telegram.Chat`, optional): Information about the chat that
            published the gift.

            .. versionadded:: 22.4
        personal_total_count (:obj:`int`, optional): The total number of gifts of this type that
            can be sent by the bot; for limited gifts only.

            .. versionadded:: 22.6
        personal_remaining_count (:obj:`int`, optional): The number of remaining gifts of this type
            that can be sent by the bot; for limited gifts only.

            .. versionadded:: 22.6
        background (:class:`GiftBackground`, optional): Background of the gift.

            .. versionadded:: 22.6
        is_premium (:obj:`bool`, optional): :obj:`True`, if the gift can only be purchased by
            Telegram Premium subscribers.

            .. versionadded:: 22.6
        has_colors (:obj:`bool`, optional): :obj:`True`, if the gift can be used (after being
            upgraded) to customize a user's appearance.

            .. versionadded:: 22.6
        unique_gift_variant_count (:obj:`int`, optional): The total number of different unique
            gifts that can be obtained by upgrading the gift.

            .. versionadded:: 22.6

    Attributes:
        id (:obj:`str`): Unique identifier of the gift.
        sticker (:class:`~telegram.Sticker`): The sticker that represents the gift.
        star_count (:obj:`int`): The number of Telegram Stars that must be paid to send the
            sticker.
        total_count (:obj:`int`): Optional. The total number of the gifts of this type that can be
            sent by all users; for limited gifts only.
        remaining_count (:obj:`int`): Optional. The number of remaining gifts of this type that can
            be sent by all users; for limited gifts only.
        upgrade_star_count (:obj:`int`): Optional. The number of Telegram Stars that must be paid
            to upgrade the gift to a unique one.

            .. versionadded:: 21.10
        publisher_chat (:class:`telegram.Chat`): Optional. Information about the chat that
            published the gift.

            .. versionadded:: 22.4
        personal_total_count (:obj:`int`): Optional. The total number of gifts of this type that
            can be sent by the bot; for limited gifts only.

            .. versionadded:: 22.6
        personal_remaining_count (:obj:`int`): Optional. The number of remaining gifts of this type
            that can be sent by the bot; for limited gifts only.

            .. versionadded:: 22.6
        background (:class:`GiftBackground`): Optional. Background of the gift.

            .. versionadded:: 22.6
        is_premium (:obj:`bool`): Optional. :obj:`True`, if the gift can only be purchased by
            Telegram Premium subscribers.

            .. versionadded:: 22.6
        has_colors (:obj:`bool`): Optional. :obj:`True`, if the gift can be used (after being
            upgraded) to customize a user's appearance.

            .. versionadded:: 22.6
        unique_gift_variant_count (:obj:`int`): Optional. The total number of different unique
            gifts that can be obtained by upgrading the gift.

            .. versionadded:: 22.6

    """

    __slots__ = (
        "background",
        "has_colors",
        "id",
        "is_premium",
        "personal_remaining_count",
        "personal_total_count",
        "publisher_chat",
        "remaining_count",
        "star_count",
        "sticker",
        "total_count",
        "unique_gift_variant_count",
        "upgrade_star_count",
    )

    def __init__(
        self,
        id: str,
        sticker: Sticker,
        star_count: int,
        total_count: int | None = None,
        remaining_count: int | None = None,
        upgrade_star_count: int | None = None,
        publisher_chat: Chat | None = None,
        personal_total_count: int | None = None,
        personal_remaining_count: int | None = None,
        background: GiftBackground | None = None,
        is_premium: bool | None = None,
        has_colors: bool | None = None,
        unique_gift_variant_count: int | None = None,
        *,
        api_kwargs: JSONDict | None = None,
    ):
        super().__init__(api_kwargs=api_kwargs)
        self.id: str = id
        self.sticker: Sticker = sticker
        self.star_count: int = star_count
        self.total_count: int | None = total_count
        self.remaining_count: int | None = remaining_count
        self.upgrade_star_count: int | None = upgrade_star_count
        self.publisher_chat: Chat | None = publisher_chat
        self.personal_total_count: int | None = personal_total_count
        self.personal_remaining_count: int | None = personal_remaining_count
        self.background: GiftBackground | None = background
        self.is_premium: bool | None = is_premium
        self.has_colors: bool | None = has_colors
        self.unique_gift_variant_count: int | None = unique_gift_variant_count

        self._id_attrs = (self.id,)

        self._freeze()

    @classmethod
    def de_json(cls, data: JSONDict, bot: "Bot | None" = None) -> "Gift":
        """See :meth:`telegram.TelegramObject.de_json`."""
        data = cls._parse_data(data)

        data["sticker"] = de_json_optional(data.get("sticker"), Sticker, bot)
        data["publisher_chat"] = de_json_optional(data.get("publisher_chat"), Chat, bot)
        data["background"] = de_json_optional(data.get("background"), GiftBackground, bot)
        return super().de_json(data=data, bot=bot)


class Gifts(TelegramObject):
    """This object represent a list of gifts.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal if their :attr:`gifts` are equal.

    .. versionadded:: 21.8

    Args:
        gifts (Sequence[:class:`Gift`]): The sequence of gifts.

    Attributes:
        gifts (tuple[:class:`Gift`]): The sequence of gifts.

    """

    __slots__ = ("gifts",)

    def __init__(
        self,
        gifts: Sequence[Gift],
        *,
        api_kwargs: JSONDict | None = None,
    ):
        super().__init__(api_kwargs=api_kwargs)
        self.gifts: tuple[Gift, ...] = parse_sequence_arg(gifts)

        self._id_attrs = (self.gifts,)

        self._freeze()

    @classmethod
    def de_json(cls, data: JSONDict, bot: "Bot | None" = None) -> "Gifts":
        """See :meth:`telegram.TelegramObject.de_json`."""
        data = cls._parse_data(data)

        data["gifts"] = de_list_optional(data.get("gifts"), Gift, bot)
        return super().de_json(data=data, bot=bot)


class GiftInfo(TelegramObject):
    """Describes a service message about a regular gift that was sent or received.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal if their :attr:`gift` is equal.

    .. versionadded:: 22.1

    Args:
        gift (:class:`Gift`): Information about the gift.
        owned_gift_id (:obj:`str`, optional): Unique identifier of the received gift for the bot;
            only present for gifts received on behalf of business accounts.
        convert_star_count (:obj:`int`, optional) Number of Telegram Stars that can be claimed by
            the receiver by converting the gift; omitted if conversion to Telegram Stars
            is impossible.
        prepaid_upgrade_star_count (:obj:`int`, optional): Number of Telegram Stars that were
            prepaid for the ability to upgrade the gift.
        can_be_upgraded (:obj:`bool`, optional): :obj:`True`, if the gift can be upgraded
            to a unique gift.
        text (:obj:`str`, optional): Text of the message that was added to the gift.
        entities (Sequence[:class:`telegram.MessageEntity`], optional): Special entities that
            appear in the text.
        is_private (:obj:`bool`, optional): :obj:`True`, if the sender and gift text are
            shown only to the gift receiver; otherwise, everyone will be able to see them.
        is_upgrade_separate (:obj:`bool`, optional): :obj:`True`, if the gift's upgrade was
            purchased after the gift was sent.

            .. versionadded:: 22.6
        unique_gift_number (:obj:`int`, optional): Unique number reserved for this gift when
            upgraded. See the number field in :class:`~telegram.UniqueGift`.

            .. versionadded:: 22.6

    Attributes:
        gift (:class:`Gift`): Information about the gift.
        owned_gift_id (:obj:`str`): Optional. Unique identifier of the received gift for the bot;
            only present for gifts received on behalf of business accounts.
        convert_star_count (:obj:`int`): Optional. Number of Telegram Stars that can be claimed by
            the receiver by converting the gift; omitted if conversion to Telegram Stars
            is impossible.
        prepaid_upgrade_star_count (:obj:`int`): Optional. Number of Telegram Stars that were
            prepaid for the ability to upgrade the gift.
        can_be_upgraded (:obj:`bool`): Optional. :obj:`True`, if the gift can be upgraded
            to a unique gift.
        text (:obj:`str`): Optional. Text of the message that was added to the gift.
        entities (Sequence[:class:`telegram.MessageEntity`]): Optional. Special entities that
            appear in the text.
        is_private (:obj:`bool`): Optional. :obj:`True`, if the sender and gift text are
            shown only to the gift receiver; otherwise, everyone will be able to see them.
        is_upgrade_separate (:obj:`bool`): Optional. :obj:`True`, if the gift's upgrade was
            purchased after the gift was sent.

            .. versionadded:: 22.6
        unique_gift_number (:obj:`int`): Optional. Unique number reserved for this gift when
            upgraded. See the number field in :class:`~telegram.UniqueGift`.

            .. versionadded:: 22.6

    """

    __slots__ = (
        "can_be_upgraded",
        "convert_star_count",
        "entities",
        "gift",
        "is_private",
        "is_upgrade_separate",
        "owned_gift_id",
        "prepaid_upgrade_star_count",
        "text",
        "unique_gift_number",
    )

    def __init__(
        self,
        gift: Gift,
        owned_gift_id: str | None = None,
        convert_star_count: int | None = None,
        prepaid_upgrade_star_count: int | None = None,
        can_be_upgraded: bool | None = None,
        text: str | None = None,
        entities: Sequence[MessageEntity] | None = None,
        is_private: bool | None = None,
        unique_gift_number: int | None = None,
        is_upgrade_separate: bool | None = None,
        *,
        api_kwargs: JSONDict | None = None,
    ):
        super().__init__(api_kwargs=api_kwargs)
        # Required
        self.gift: Gift = gift
        # Optional
        self.owned_gift_id: str | None = owned_gift_id
        self.convert_star_count: int | None = convert_star_count
        self.prepaid_upgrade_star_count: int | None = prepaid_upgrade_star_count
        self.can_be_upgraded: bool | None = can_be_upgraded
        self.text: str | None = text
        self.entities: tuple[MessageEntity, ...] = parse_sequence_arg(entities)
        self.is_private: bool | None = is_private
        self.unique_gift_number: int | None = unique_gift_number
        self.is_upgrade_separate: bool | None = is_upgrade_separate

        self._id_attrs = (self.gift,)

        self._freeze()

    @classmethod
    def de_json(cls, data: JSONDict, bot: "Bot | None" = None) -> "GiftInfo":
        """See :meth:`telegram.TelegramObject.de_json`."""
        data = cls._parse_data(data)

        data["gift"] = de_json_optional(data.get("gift"), Gift, bot)
        data["entities"] = de_list_optional(data.get("entities"), MessageEntity, bot)

        return super().de_json(data=data, bot=bot)

    def parse_entity(self, entity: MessageEntity) -> str:
        """Returns the text in :attr:`text`
        from a given :class:`telegram.MessageEntity` of :attr:`entities`.

        Note:
            This method is present because Telegram calculates the offset and length in
            UTF-16 codepoint pairs, which some versions of Python don't handle automatically.
            (That is, you can't just slice ``Message.text`` with the offset and length.)

        Args:
            entity (:class:`telegram.MessageEntity`): The entity to extract the text from. It must
                be an entity that belongs to :attr:`entities`.

        Returns:
            :obj:`str`: The text of the given entity.

        Raises:
            RuntimeError: If the gift info has no text.

        """
        if not self.text:
            raise RuntimeError("This GiftInfo has no 'text'.")

        return parse_message_entity(self.text, entity)

    def parse_entities(self, types: list[str] | None = None) -> dict[MessageEntity, str]:
        """
        Returns a :obj:`dict` that maps :class:`telegram.MessageEntity` to :obj:`str`.
        It contains entities from this gift info's text filtered by their ``type`` attribute as
        the key, and the text that each entity belongs to as the value of the :obj:`dict`.

        Note:
            This method should always be used instead of the :attr:`entities`
            attribute, since it calculates the correct substring from the message text based on
            UTF-16 codepoints. See :attr:`parse_entity` for more info.

        Args:
            types (list[:obj:`str`], optional): List of ``MessageEntity`` types as strings. If the
                    ``type`` attribute of an entity is contained in this list, it will be returned.
                    Defaults to :attr:`telegram.MessageEntity.ALL_TYPES`.

        Returns:
            dict[:class:`telegram.MessageEntity`, :obj:`str`]: A dictionary of entities mapped to
            the text that belongs to them, calculated based on UTF-16 codepoints.

        Raises:
            RuntimeError: If the gift info has no text.

        """
        if not self.text:
            raise RuntimeError("This GiftInfo has no 'text'.")

        return parse_message_entities(self.text, self.entities, types)


class AcceptedGiftTypes(TelegramObject):
    """This object describes the types of gifts that can be gifted to a user or a chat.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal if their :attr:`unlimited_gifts`, :attr:`limited_gifts`,
    :attr:`unique_gifts`, :attr:`premium_subscription` and :attr:`gifts_from_channels` are equal.

    .. versionadded:: 22.1
    .. versionchanged:: 22.6
        :attr:`gifts_from_channels` is now considered for equality checks.

    Args:
        unlimited_gifts (:class:`bool`): :obj:`True`, if unlimited regular gifts are accepted.
        limited_gifts (:class:`bool`): :obj:`True`, if limited regular gifts are accepted.
        unique_gifts (:class:`bool`): :obj:`True`, if unique gifts or gifts that can be upgraded
            to unique for free are accepted.
        premium_subscription (:class:`bool`): :obj:`True`, if a Telegram Premium subscription
            is accepted.
        gifts_from_channels (:obj:`bool`): :obj:`True`, if transfers of unique gifts from channels
            are accepted

            .. versionadded:: 22.6

    Attributes:
        unlimited_gifts (:class:`bool`): :obj:`True`, if unlimited regular gifts are accepted.
        limited_gifts (:class:`bool`): :obj:`True`, if limited regular gifts are accepted.
        unique_gifts (:class:`bool`): :obj:`True`, if unique gifts or gifts that can be upgraded
            to unique for free are accepted.
        premium_subscription (:class:`bool`): :obj:`True`, if a Telegram Premium subscription
            is accepted.
        gifts_from_channels (:obj:`bool`): :obj:`True`, if transfers of unique gifts from channels
            are accepted

            .. versionadded:: 22.6

    """

    __slots__ = (
        "gifts_from_channels",
        "limited_gifts",
        "premium_subscription",
        "unique_gifts",
        "unlimited_gifts",
    )

    def __init__(
        self,
        unlimited_gifts: bool,
        limited_gifts: bool,
        unique_gifts: bool,
        premium_subscription: bool,
        gifts_from_channels: bool,
        *,
        api_kwargs: JSONDict | None = None,
    ):
        super().__init__(api_kwargs=api_kwargs)
        self.unlimited_gifts: bool = unlimited_gifts
        self.limited_gifts: bool = limited_gifts
        self.unique_gifts: bool = unique_gifts
        self.premium_subscription: bool = premium_subscription
        self.gifts_from_channels: bool = gifts_from_channels

        self._id_attrs = (
            self.unlimited_gifts,
            self.limited_gifts,
            self.unique_gifts,
            self.premium_subscription,
            self.gifts_from_channels,
        )

        self._freeze()
