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
# along with this program. If not, see [http://www.gnu.org/licenses/].
"""This module contains objects that represent owned gifts."""

import datetime as dtm
from collections.abc import Sequence
from typing import TYPE_CHECKING, Final

from telegram import constants
from telegram._gifts import Gift
from telegram._messageentity import MessageEntity
from telegram._telegramobject import TelegramObject
from telegram._uniquegift import UniqueGift
from telegram._user import User
from telegram._utils import enum
from telegram._utils.argumentparsing import de_json_optional, de_list_optional, parse_sequence_arg
from telegram._utils.datetime import extract_tzinfo_from_defaults, from_timestamp
from telegram._utils.entities import parse_message_entities, parse_message_entity
from telegram._utils.types import JSONDict

if TYPE_CHECKING:
    from telegram import Bot


class OwnedGift(TelegramObject):
    """This object describes a gift received and owned by a user or a chat. Currently, it
    can be one of:

    * :class:`telegram.OwnedGiftRegular`
    * :class:`telegram.OwnedGiftUnique`

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :attr:`type` is equal.

    .. versionadded:: 22.1

    Args:
        type (:obj:`str`): Type of the owned gift.

    Attributes:
        type (:obj:`str`): Type of the owned gift.
    """

    __slots__ = ("type",)

    REGULAR: Final[str] = constants.OwnedGiftType.REGULAR
    """:const:`telegram.constants.OwnedGiftType.REGULAR`"""
    UNIQUE: Final[str] = constants.OwnedGiftType.UNIQUE
    """:const:`telegram.constants.OwnedGiftType.UNIQUE`"""

    def __init__(
        self,
        type: str,  # pylint: disable=redefined-builtin
        *,
        api_kwargs: JSONDict | None = None,
    ) -> None:
        super().__init__(api_kwargs=api_kwargs)
        self.type: str = enum.get_member(constants.OwnedGiftType, type, type)

        self._id_attrs = (self.type,)
        self._freeze()

    @classmethod
    def de_json(cls, data: JSONDict, bot: "Bot | None" = None) -> "OwnedGift":
        """Converts JSON data to the appropriate :class:`OwnedGift` object, i.e. takes
        care of selecting the correct subclass.

        Args:
            data (dict[:obj:`str`, ...]): The JSON data.
            bot (:class:`telegram.Bot`, optional): The bot associated with this object.

        Returns:
            The Telegram object.

        """
        data = cls._parse_data(data)

        _class_mapping: dict[str, type[OwnedGift]] = {
            cls.REGULAR: OwnedGiftRegular,
            cls.UNIQUE: OwnedGiftUnique,
        }

        if cls is OwnedGift and data.get("type") in _class_mapping:
            return _class_mapping[data.pop("type")].de_json(data=data, bot=bot)

        return super().de_json(data=data, bot=bot)


class OwnedGifts(TelegramObject):
    """Contains the list of gifts received and owned by a user or a chat.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :attr:`total_count` and :attr:`gifts` are equal.

    .. versionadded:: 22.1

    Args:
        total_count (:obj:`int`): The total number of gifts owned by the user or the chat.
        gifts (Sequence[:class:`telegram.OwnedGift`]): The list of gifts.
        next_offset (:obj:`str`, optional): Offset for the next request. If empty,
            then there are no more results.

    Attributes:
        total_count (:obj:`int`): The total number of gifts owned by the user or the chat.
        gifts (Sequence[:class:`telegram.OwnedGift`]): The list of gifts.
        next_offset (:obj:`str`): Optional. Offset for the next request. If empty,
            then there are no more results.
    """

    __slots__ = (
        "gifts",
        "next_offset",
        "total_count",
    )

    def __init__(
        self,
        total_count: int,
        gifts: Sequence[OwnedGift],
        next_offset: str | None = None,
        *,
        api_kwargs: JSONDict | None = None,
    ):
        super().__init__(api_kwargs=api_kwargs)
        self.total_count: int = total_count
        self.gifts: tuple[OwnedGift, ...] = parse_sequence_arg(gifts)
        self.next_offset: str | None = next_offset

        self._id_attrs = (self.total_count, self.gifts)

        self._freeze()

    @classmethod
    def de_json(cls, data: JSONDict, bot: "Bot | None" = None) -> "OwnedGifts":
        """See :meth:`telegram.TelegramObject.de_json`."""
        data = cls._parse_data(data)

        data["gifts"] = de_list_optional(data.get("gifts"), OwnedGift, bot)
        return super().de_json(data=data, bot=bot)


class OwnedGiftRegular(OwnedGift):
    """Describes a regular gift owned by a user or a chat.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :attr:`gift` and :attr:`send_date` are equal.

    .. versionadded:: 22.1

    Args:
        gift (:class:`telegram.Gift`): Information about the regular gift.
        owned_gift_id (:obj:`str`, optional): Unique identifier of the gift for the bot; for
            gifts received on behalf of business accounts only.
        sender_user (:class:`telegram.User`, optional): Sender of the gift if it is a known user.
        send_date (:obj:`datetime.datetime`): Date the gift was sent as :class:`datetime.datetime`.
            |datetime_localization|.
        text (:obj:`str`, optional): Text of the message that was added to the gift.
        entities (Sequence[:class:`telegram.MessageEntity`], optional): Special entities that
            appear in the text.
        is_private (:obj:`bool`, optional): :obj:`True`, if the sender and gift text are shown
            only to the gift receiver; otherwise, everyone will be able to see them.
        is_saved (:obj:`bool`, optional): :obj:`True`, if the gift is displayed on the account's
            profile page; for gifts received on behalf of business accounts only.
        can_be_upgraded (:obj:`bool`, optional): :obj:`True`, if the gift can be upgraded to a
            unique gift; for gifts received on behalf of business accounts only.
        was_refunded (:obj:`bool`, optional): :obj:`True`, if the gift was refunded and isn't
            available anymore.
        convert_star_count (:obj:`int`, optional): Number of Telegram Stars that can be
            claimed by the receiver instead of the gift; omitted if the gift cannot be converted
            to Telegram Stars; for gifts received on behalf of business accounts only.
        prepaid_upgrade_star_count (:obj:`int`, optional): Number of Telegram Stars that were
            paid for the ability to upgrade the gift.
        is_upgrade_separate (:obj:`bool`, optional): :obj:`True`, if the gift's upgrade was
            purchased after the gift was sent; for gifts received on behalf of business accounts

            .. versionadded:: 22.6
        unique_gift_number (:obj:`int`, optional): Unique number reserved for this gift when
            upgraded. See the number field in :class:`~telegram.UniqueGift`

            ... versionadded:: 22.6

    Attributes:
        type (:obj:`str`): Type of the gift, always :attr:`~telegram.OwnedGift.REGULAR`.
        gift (:class:`telegram.Gift`): Information about the regular gift.
        owned_gift_id (:obj:`str`): Optional. Unique identifier of the gift for the bot; for
            gifts received on behalf of business accounts only.
        sender_user (:class:`telegram.User`): Optional. Sender of the gift if it is a known user.
        send_date (:obj:`datetime.datetime`): Date the gift was sent as :class:`datetime.datetime`.
            |datetime_localization|.
        text (:obj:`str`): Optional. Text of the message that was added to the gift.
        entities (Sequence[:class:`telegram.MessageEntity`]): Optional. Special entities that
            appear in the text.
        is_private (:obj:`bool`): Optional. :obj:`True`, if the sender and gift text are shown
            only to the gift receiver; otherwise, everyone will be able to see them.
        is_saved (:obj:`bool`): Optional. :obj:`True`, if the gift is displayed on the account's
            profile page; for gifts received on behalf of business accounts only.
        can_be_upgraded (:obj:`bool`): Optional. :obj:`True`, if the gift can be upgraded to a
            unique gift; for gifts received on behalf of business accounts only.
        was_refunded (:obj:`bool`): Optional. :obj:`True`, if the gift was refunded and isn't
            available anymore.
        convert_star_count (:obj:`int`): Optional. Number of Telegram Stars that can be
            claimed by the receiver instead of the gift; omitted if the gift cannot be converted
            to Telegram Stars; for gifts received on behalf of business accounts only.
        prepaid_upgrade_star_count (:obj:`int`): Optional. Number of Telegram Stars that were
            paid for the ability to upgrade the gift.
        is_upgrade_separate (:obj:`bool`): Optional. :obj:`True`, if the gift's upgrade was
            purchased after the gift was sent; for gifts received on behalf of business accounts

            .. versionadded:: 22.6
        unique_gift_number (:obj:`int`): Optional. Unique number reserved for this gift when
            upgraded. See the number field in :class:`~telegram.UniqueGift`

            ... versionadded:: 22.6

    """

    __slots__ = (
        "can_be_upgraded",
        "convert_star_count",
        "entities",
        "gift",
        "is_private",
        "is_saved",
        "is_upgrade_separate",
        "owned_gift_id",
        "prepaid_upgrade_star_count",
        "send_date",
        "sender_user",
        "text",
        "unique_gift_number",
        "was_refunded",
    )

    def __init__(
        self,
        gift: Gift,
        send_date: dtm.datetime,
        owned_gift_id: str | None = None,
        sender_user: User | None = None,
        text: str | None = None,
        entities: Sequence[MessageEntity] | None = None,
        is_private: bool | None = None,
        is_saved: bool | None = None,
        can_be_upgraded: bool | None = None,
        was_refunded: bool | None = None,
        convert_star_count: int | None = None,
        prepaid_upgrade_star_count: int | None = None,
        is_upgrade_separate: bool | None = None,
        unique_gift_number: int | None = None,
        *,
        api_kwargs: JSONDict | None = None,
    ) -> None:
        super().__init__(type=OwnedGift.REGULAR, api_kwargs=api_kwargs)

        with self._unfrozen():
            self.gift: Gift = gift
            self.send_date: dtm.datetime = send_date
            self.owned_gift_id: str | None = owned_gift_id
            self.sender_user: User | None = sender_user
            self.text: str | None = text
            self.entities: tuple[MessageEntity, ...] = parse_sequence_arg(entities)
            self.is_private: bool | None = is_private
            self.is_saved: bool | None = is_saved
            self.can_be_upgraded: bool | None = can_be_upgraded
            self.was_refunded: bool | None = was_refunded
            self.convert_star_count: int | None = convert_star_count
            self.prepaid_upgrade_star_count: int | None = prepaid_upgrade_star_count
            self.is_upgrade_separate: bool | None = is_upgrade_separate
            self.unique_gift_number: int | None = unique_gift_number

            self._id_attrs = (self.type, self.gift, self.send_date)

    @classmethod
    def de_json(cls, data: JSONDict, bot: "Bot | None" = None) -> "OwnedGiftRegular":
        """See :meth:`telegram.OwnedGift.de_json`."""
        data = cls._parse_data(data)

        loc_tzinfo = extract_tzinfo_from_defaults(bot)
        data["send_date"] = from_timestamp(data.get("send_date"), tzinfo=loc_tzinfo)
        data["sender_user"] = de_json_optional(data.get("sender_user"), User, bot)
        data["gift"] = de_json_optional(data.get("gift"), Gift, bot)
        data["entities"] = de_list_optional(data.get("entities"), MessageEntity, bot)

        return super().de_json(data=data, bot=bot)  # type: ignore[return-value]

    def parse_entity(self, entity: MessageEntity) -> str:
        """Returns the text in :attr:`text`
        from a given :class:`telegram.MessageEntity` of :attr:`entities`.

        Note:
            This method is present because Telegram calculates the offset and length in
            UTF-16 codepoint pairs, which some versions of Python don't handle automatically.
            (That is, you can't just slice ``OwnedGiftRegular.text`` with the offset and length.)

        Args:
            entity (:class:`telegram.MessageEntity`): The entity to extract the text from. It must
                be an entity that belongs to :attr:`entities`.

        Returns:
            :obj:`str`: The text of the given entity.

        Raises:
            RuntimeError: If the owned gift has no text.

        """
        if not self.text:
            raise RuntimeError("This OwnedGiftRegular has no 'text'.")

        return parse_message_entity(self.text, entity)

    def parse_entities(self, types: list[str] | None = None) -> dict[MessageEntity, str]:
        """
        Returns a :obj:`dict` that maps :class:`telegram.MessageEntity` to :obj:`str`.
        It contains entities from this owned gift's text filtered by their ``type`` attribute as
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
            RuntimeError: If the owned gift has no text.

        """
        if not self.text:
            raise RuntimeError("This OwnedGiftRegular has no 'text'.")

        return parse_message_entities(self.text, self.entities, types)


class OwnedGiftUnique(OwnedGift):
    """
    Describes a unique gift received and owned by a user or a chat.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :attr:`gift` and :attr:`send_date` are equal.

    .. versionadded:: 22.1

    Args:
        gift (:class:`telegram.UniqueGift`): Information about the unique gift.
        owned_gift_id (:obj:`str`, optional): Unique identifier of the received gift for the
            bot; for gifts received on behalf of business accounts only.
        sender_user (:class:`telegram.User`, optional): Sender of the gift if it is a known user.
        send_date (:obj:`datetime.datetime`): Date the gift was sent as :class:`datetime.datetime`.
            |datetime_localization|
        is_saved (:obj:`bool`, optional): :obj:`True`, if the gift is displayed on the account's
            profile page; for gifts received on behalf of business accounts only.
        can_be_transferred (:obj:`bool`, optional): :obj:`True`, if the gift can be transferred to
            another owner; for gifts received on behalf of business accounts only.
        transfer_star_count (:obj:`int`, optional): Number of Telegram Stars that must be paid
            to transfer the gift; omitted if the bot cannot transfer the gift.
        next_transfer_date (:obj:`datetime.datetime`, optional): Date when the gift can be
            transferred. If it's in the past, then the gift can be transferred now.
            |datetime_localization|
            .. versionadded:: 22.3

    Attributes:
        type (:obj:`str`): Type of the owned gift, always :tg-const:`~telegram.OwnedGift.UNIQUE`.
        gift (:class:`telegram.UniqueGift`): Information about the unique gift.
        owned_gift_id (:obj:`str`): Optional. Unique identifier of the received gift for the
            bot; for gifts received on behalf of business accounts only.
        sender_user (:class:`telegram.User`): Optional. Sender of the gift if it is a known user.
        send_date (:obj:`datetime.datetime`): Date the gift was sent as :class:`datetime.datetime`.
            |datetime_localization|
        is_saved (:obj:`bool`): Optional. :obj:`True`, if the gift is displayed on the account's
            profile page; for gifts received on behalf of business accounts only.
        can_be_transferred (:obj:`bool`): Optional. :obj:`True`, if the gift can be transferred to
            another owner; for gifts received on behalf of business accounts only.
        transfer_star_count (:obj:`int`): Optional. Number of Telegram Stars that must be paid
            to transfer the gift; omitted if the bot cannot transfer the gift.
        next_transfer_date (:obj:`datetime.datetime`): Optional. Date when the gift can be
            transferred. If it's in the past, then the gift can be transferred now.
            |datetime_localization|
            .. versionadded:: 22.3
    """

    __slots__ = (
        "can_be_transferred",
        "gift",
        "is_saved",
        "next_transfer_date",
        "owned_gift_id",
        "send_date",
        "sender_user",
        "transfer_star_count",
    )

    def __init__(
        self,
        gift: UniqueGift,
        send_date: dtm.datetime,
        owned_gift_id: str | None = None,
        sender_user: User | None = None,
        is_saved: bool | None = None,
        can_be_transferred: bool | None = None,
        transfer_star_count: int | None = None,
        next_transfer_date: dtm.datetime | None = None,
        *,
        api_kwargs: JSONDict | None = None,
    ) -> None:
        super().__init__(type=OwnedGift.UNIQUE, api_kwargs=api_kwargs)

        with self._unfrozen():
            self.gift: UniqueGift = gift
            self.send_date: dtm.datetime = send_date
            self.owned_gift_id: str | None = owned_gift_id
            self.sender_user: User | None = sender_user
            self.is_saved: bool | None = is_saved
            self.can_be_transferred: bool | None = can_be_transferred
            self.transfer_star_count: int | None = transfer_star_count
            self.next_transfer_date: dtm.datetime | None = next_transfer_date

            self._id_attrs = (self.type, self.gift, self.send_date)

    @classmethod
    def de_json(cls, data: JSONDict, bot: "Bot | None" = None) -> "OwnedGiftUnique":
        """See :meth:`telegram.OwnedGift.de_json`."""
        data = cls._parse_data(data)

        loc_tzinfo = extract_tzinfo_from_defaults(bot)
        data["send_date"] = from_timestamp(data.get("send_date"), tzinfo=loc_tzinfo)
        data["sender_user"] = de_json_optional(data.get("sender_user"), User, bot)
        data["gift"] = de_json_optional(data.get("gift"), UniqueGift, bot)
        data["next_transfer_date"] = from_timestamp(
            data.get("next_transfer_date"), tzinfo=loc_tzinfo
        )

        return super().de_json(data=data, bot=bot)  # type: ignore[return-value]
