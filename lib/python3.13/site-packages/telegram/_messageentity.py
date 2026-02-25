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
"""This module contains an object that represents a Telegram MessageEntity."""

import copy
import itertools
from collections.abc import Sequence
from typing import TYPE_CHECKING, Final

from telegram import constants
from telegram._telegramobject import TelegramObject
from telegram._user import User
from telegram._utils import enum
from telegram._utils.argumentparsing import de_json_optional
from telegram._utils.strings import TextEncoding
from telegram._utils.types import JSONDict

if TYPE_CHECKING:
    from telegram import Bot

_SEM = Sequence["MessageEntity"]


class MessageEntity(TelegramObject):
    """
    This object represents one special entity in a text message. For example, hashtags,
    usernames, URLs, etc.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :attr:`type`, :attr:`offset` and :attr:`length` are equal.

    Args:
        type (:obj:`str`): Type of the entity. Can be :attr:`MENTION` (``@username``),
            :attr:`HASHTAG` (``#hashtag`` or ``#hashtag@chatusername``), :attr:`CASHTAG` (``$USD``
            or ``USD@chatusername``), :attr:`BOT_COMMAND` (``/start@jobs_bot``), :attr:`URL`
            (``https://telegram.org``), :attr:`EMAIL` (``do-not-reply@telegram.org``),
            :attr:`PHONE_NUMBER` (``+1-212-555-0123``),
            :attr:`BOLD` (**bold text**), :attr:`ITALIC` (*italic text*), :attr:`UNDERLINE`
            (underlined text), :attr:`STRIKETHROUGH`, :attr:`SPOILER` (spoiler message),
            :attr:`BLOCKQUOTE` (block quotation), :attr:`CODE` (monowidth string), :attr:`PRE`
            (monowidth block), :attr:`TEXT_LINK` (for clickable text URLs), :attr:`TEXT_MENTION`
            (for users without usernames), :attr:`CUSTOM_EMOJI` (for inline custom emoji stickers).

            .. versionadded:: 20.0
                Added inline custom emoji

            .. versionadded:: 20.8
                Added block quotation
        offset (:obj:`int`): Offset in UTF-16 code units to the start of the entity.
        length (:obj:`int`): Length of the entity in UTF-16 code units.
        url (:obj:`str`, optional): For :attr:`TEXT_LINK` only, url that will be opened after
            user taps on the text.
        user (:class:`telegram.User`, optional): For :attr:`TEXT_MENTION` only, the mentioned
             user.
        language (:obj:`str`, optional): For :attr:`PRE` only, the programming language of
            the entity text.
        custom_emoji_id (:obj:`str`, optional): For :attr:`CUSTOM_EMOJI` only, unique identifier
            of the custom emoji. Use :meth:`telegram.Bot.get_custom_emoji_stickers` to get full
            information about the sticker.

            .. versionadded:: 20.0
    Attributes:
        type (:obj:`str`): Type of the entity.  Can be :attr:`MENTION` (``@username``),
            :attr:`HASHTAG` (``#hashtag`` or ``#hashtag@chatusername``), :attr:`CASHTAG` (``$USD``
            or ``USD@chatusername``), :attr:`BOT_COMMAND` (``/start@jobs_bot``), :attr:`URL`
            (``https://telegram.org``), :attr:`EMAIL` (``do-not-reply@telegram.org``),
            :attr:`PHONE_NUMBER` (``+1-212-555-0123``),
            :attr:`BOLD` (**bold text**), :attr:`ITALIC` (*italic text*), :attr:`UNDERLINE`
            (underlined text), :attr:`STRIKETHROUGH`, :attr:`SPOILER` (spoiler message),
            :attr:`BLOCKQUOTE` (block quotation), :attr:`CODE` (monowidth string), :attr:`PRE`
            (monowidth block), :attr:`TEXT_LINK` (for clickable text URLs), :attr:`TEXT_MENTION`
            (for users without usernames), :attr:`CUSTOM_EMOJI` (for inline custom emoji stickers).

            .. versionadded:: 20.0
                Added inline custom emoji

            .. versionadded:: 20.8
                Added block quotation
        offset (:obj:`int`): Offset in UTF-16 code units to the start of the entity.
        length (:obj:`int`): Length of the entity in UTF-16 code units.
        url (:obj:`str`): Optional. For :attr:`TEXT_LINK` only, url that will be opened after
            user taps on the text.
        user (:class:`telegram.User`): Optional. For :attr:`TEXT_MENTION` only, the mentioned
             user.
        language (:obj:`str`): Optional. For :attr:`PRE` only, the programming language of
            the entity text.
        custom_emoji_id (:obj:`str`): Optional. For :attr:`CUSTOM_EMOJI` only, unique identifier
            of the custom emoji. Use :meth:`telegram.Bot.get_custom_emoji_stickers` to get full
            information about the sticker.

            .. versionadded:: 20.0

    """

    __slots__ = ("custom_emoji_id", "language", "length", "offset", "type", "url", "user")

    def __init__(
        self,
        type: str,  # pylint: disable=redefined-builtin
        offset: int,
        length: int,
        url: str | None = None,
        user: User | None = None,
        language: str | None = None,
        custom_emoji_id: str | None = None,
        *,
        api_kwargs: JSONDict | None = None,
    ):
        super().__init__(api_kwargs=api_kwargs)
        # Required
        self.type: str = enum.get_member(constants.MessageEntityType, type, type)
        self.offset: int = offset
        self.length: int = length
        # Optionals
        self.url: str | None = url
        self.user: User | None = user
        self.language: str | None = language
        self.custom_emoji_id: str | None = custom_emoji_id

        self._id_attrs = (self.type, self.offset, self.length)

        self._freeze()

    @classmethod
    def de_json(cls, data: JSONDict, bot: "Bot | None" = None) -> "MessageEntity":
        """See :meth:`telegram.TelegramObject.de_json`."""
        data = cls._parse_data(data)

        data["user"] = de_json_optional(data.get("user"), User, bot)

        return super().de_json(data=data, bot=bot)

    @staticmethod
    def adjust_message_entities_to_utf_16(text: str, entities: _SEM) -> _SEM:
        """Utility functionality for converting the offset and length of entities from
        Unicode (:obj:`str`) to UTF-16 (``utf-16-le`` encoded :obj:`bytes`).

        Tip:
            Only the offsets and lengths calulated in UTF-16 is acceptable by the Telegram Bot API.
            If they are calculated using the Unicode string (:obj:`str` object), errors may occur
            when the text contains characters that are not in the Basic Multilingual Plane (BMP).
            For more information, see `Unicode <https://en.wikipedia.org/wiki/Unicode>`_ and
            `Plane (Unicode) <https://en.wikipedia.org/wiki/Plane_(Unicode)>`_.

        .. versionadded:: 21.4

        Examples:
            Below is a snippet of code that demonstrates how to use this function to convert
            entities from Unicode to UTF-16 space. The ``unicode_entities`` are calculated in
            Unicode and the `utf_16_entities` are calculated in UTF-16.

            .. code-block:: python

                text = "𠌕 bold 𝄢 italic underlined: 𝛙𝌢𑁍"
                unicode_entities = [
                    MessageEntity(offset=2, length=4, type=MessageEntity.BOLD),
                    MessageEntity(offset=9, length=6, type=MessageEntity.ITALIC),
                    MessageEntity(offset=28, length=3, type=MessageEntity.UNDERLINE),
                ]
                utf_16_entities = MessageEntity.adjust_message_entities_to_utf_16(
                    text, unicode_entities
                )
                await bot.send_message(
                    chat_id=123,
                    text=text,
                    entities=utf_16_entities,
                )
                # utf_16_entities[0]: offset=3, length=4
                # utf_16_entities[1]: offset=11, length=6
                # utf_16_entities[2]: offset=30, length=6

        Args:
            text (:obj:`str`): The text that the entities belong to
            entities (Sequence[:class:`telegram.MessageEntity`]): Sequence of entities
                with offset and length calculated in Unicode

        Returns:
            Sequence[:class:`telegram.MessageEntity`]: Sequence of entities
            with offset and length calculated in UTF-16 encoding
        """
        # get sorted positions
        positions = sorted(itertools.chain(*((x.offset, x.offset + x.length) for x in entities)))
        accumulated_length = 0
        # calculate the length of each slice text[:position] in utf-16 accordingly,
        # store the position translations
        position_translation: dict[int, int] = {}
        for i, position in enumerate(positions):
            last_position = positions[i - 1] if i > 0 else 0
            text_slice = text[last_position:position]
            accumulated_length += len(text_slice.encode(TextEncoding.UTF_16_LE)) // 2
            position_translation[position] = accumulated_length
        # get the final output entities
        out = []
        for entity in entities:
            translated_positions = position_translation[entity.offset]
            translated_length = (
                position_translation[entity.offset + entity.length] - translated_positions
            )
            new_entity = copy.copy(entity)
            with new_entity._unfrozen():
                new_entity.offset = translated_positions
                new_entity.length = translated_length
            out.append(new_entity)
        return out

    @staticmethod
    def shift_entities(by: str | int, entities: _SEM) -> _SEM:
        """Utility functionality for shifting the offset of entities by a given amount.

        Examples:
            Shifting by an integer amount:

            .. code-block:: python

                text = "Hello, world!"
                entities = [
                    MessageEntity(offset=0, length=5, type=MessageEntity.BOLD),
                    MessageEntity(offset=7, length=5, type=MessageEntity.ITALIC),
                ]
                shifted_entities = MessageEntity.shift_entities(1, entities)
                await bot.send_message(
                    chat_id=123,
                    text="!" + text,
                    entities=shifted_entities,
                )

            Shifting using a string:

            .. code-block:: python

                text = "Hello, world!"
                prefix = "𝄢"
                entities = [
                    MessageEntity(offset=0, length=5, type=MessageEntity.BOLD),
                    MessageEntity(offset=7, length=5, type=MessageEntity.ITALIC),
                ]
                shifted_entities = MessageEntity.shift_entities(prefix, entities)
                await bot.send_message(
                    chat_id=123,
                    text=prefix + text,
                    entities=shifted_entities,
                )

        Tip:
            The :paramref:`entities` are *not* modified in place. The function returns a sequence
            of new objects.

        .. versionadded:: 21.5

        Args:
            by (:obj:`str` | :obj:`int`): Either the amount to shift the offset by or
                a string whose length will be used as the amount to shift the offset by. In this
                case, UTF-16 encoding will be used to calculate the length.
            entities (Sequence[:class:`telegram.MessageEntity`]): Sequence of entities

        Returns:
            Sequence[:class:`telegram.MessageEntity`]: Sequence of entities with the offset shifted
        """
        effective_shift = by if isinstance(by, int) else len(by.encode("utf-16-le")) // 2

        out = []
        for entity in entities:
            new_entity = copy.copy(entity)
            with new_entity._unfrozen():
                new_entity.offset += effective_shift
            out.append(new_entity)
        return out

    @classmethod
    def concatenate(
        cls,
        *args: tuple[str, _SEM] | tuple[str, _SEM, bool],
    ) -> tuple[str, _SEM]:
        """Utility functionality for concatenating two text along with their formatting entities.

        Tip:
            This function is useful for prefixing an already formatted text with a new text and its
            formatting entities. In particular, it automatically correctly handles UTF-16 encoding.

        Examples:
            This example shows a callback function that can be used to add a prefix and suffix to
            the message in a :class:`~telegram.ext.CallbackQueryHandler`:

            .. code-block:: python

                async def prefix_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
                    prefix = "𠌕 bold 𝄢 italic underlined: 𝛙𝌢𑁍 | "
                    prefix_entities = [
                        MessageEntity(offset=2, length=4, type=MessageEntity.BOLD),
                        MessageEntity(offset=9, length=6, type=MessageEntity.ITALIC),
                        MessageEntity(offset=28, length=3, type=MessageEntity.UNDERLINE),
                    ]
                    suffix = " | 𠌕 bold 𝄢 italic underlined: 𝛙𝌢𑁍"
                    suffix_entities = [
                        MessageEntity(offset=5, length=4, type=MessageEntity.BOLD),
                        MessageEntity(offset=12, length=6, type=MessageEntity.ITALIC),
                        MessageEntity(offset=31, length=3, type=MessageEntity.UNDERLINE),
                    ]

                    message = update.effective_message
                    first = (prefix, prefix_entities, True)
                    second = (message.text, message.entities)
                    third = (suffix, suffix_entities, True)

                    new_text, new_entities = MessageEntity.concatenate(first, second, third)
                    await update.callback_query.edit_message_text(
                        text=new_text,
                        entities=new_entities,
                    )

        Hint:
            The entities are *not* modified in place. The function returns a
            new sequence of objects.

        .. versionadded:: 21.5

        Args:
            *args (tuple[:obj:`str`, Sequence[:class:`telegram.MessageEntity`]] | \
                tuple[:obj:`str`, Sequence[:class:`telegram.MessageEntity`], :obj:`bool`]):
                Arbitrary number of tuples containing the text and its entities to concatenate.
                If the last element of the tuple is a :obj:`bool`, it is used to determine whether
                to adjust the entities to UTF-16 via
                :meth:`adjust_message_entities_to_utf_16`. UTF-16 adjustment is disabled by
                default.

        Returns:
            tuple[:obj:`str`, Sequence[:class:`telegram.MessageEntity`]]: The concatenated text
            and its entities
        """
        output_text = ""
        output_entities: list[MessageEntity] = []
        for arg in args:
            text, entities = arg[0], arg[1]

            if len(arg) > 2 and arg[2] is True:
                entities = cls.adjust_message_entities_to_utf_16(text, entities)

            output_entities.extend(cls.shift_entities(output_text, entities))
            output_text += text

        return output_text, output_entities

    ALL_TYPES: Final[list[str]] = list(constants.MessageEntityType)
    """list[:obj:`str`]: A list of all available message entity types."""
    BLOCKQUOTE: Final[str] = constants.MessageEntityType.BLOCKQUOTE
    """:const:`telegram.constants.MessageEntityType.BLOCKQUOTE`

    .. versionadded:: 20.8
    """
    BOLD: Final[str] = constants.MessageEntityType.BOLD
    """:const:`telegram.constants.MessageEntityType.BOLD`"""
    BOT_COMMAND: Final[str] = constants.MessageEntityType.BOT_COMMAND
    """:const:`telegram.constants.MessageEntityType.BOT_COMMAND`"""
    CASHTAG: Final[str] = constants.MessageEntityType.CASHTAG
    """:const:`telegram.constants.MessageEntityType.CASHTAG`"""
    CODE: Final[str] = constants.MessageEntityType.CODE
    """:const:`telegram.constants.MessageEntityType.CODE`"""
    CUSTOM_EMOJI: Final[str] = constants.MessageEntityType.CUSTOM_EMOJI
    """:const:`telegram.constants.MessageEntityType.CUSTOM_EMOJI`

    .. versionadded:: 20.0
    """
    EMAIL: Final[str] = constants.MessageEntityType.EMAIL
    """:const:`telegram.constants.MessageEntityType.EMAIL`"""
    EXPANDABLE_BLOCKQUOTE: Final[str] = constants.MessageEntityType.EXPANDABLE_BLOCKQUOTE
    """:const:`telegram.constants.MessageEntityType.EXPANDABLE_BLOCKQUOTE`

    .. versionadded:: 21.3
    """
    HASHTAG: Final[str] = constants.MessageEntityType.HASHTAG
    """:const:`telegram.constants.MessageEntityType.HASHTAG`"""
    ITALIC: Final[str] = constants.MessageEntityType.ITALIC
    """:const:`telegram.constants.MessageEntityType.ITALIC`"""
    MENTION: Final[str] = constants.MessageEntityType.MENTION
    """:const:`telegram.constants.MessageEntityType.MENTION`"""
    PHONE_NUMBER: Final[str] = constants.MessageEntityType.PHONE_NUMBER
    """:const:`telegram.constants.MessageEntityType.PHONE_NUMBER`"""
    PRE: Final[str] = constants.MessageEntityType.PRE
    """:const:`telegram.constants.MessageEntityType.PRE`"""
    SPOILER: Final[str] = constants.MessageEntityType.SPOILER
    """:const:`telegram.constants.MessageEntityType.SPOILER`

    .. versionadded:: 13.10
    """
    STRIKETHROUGH: Final[str] = constants.MessageEntityType.STRIKETHROUGH
    """:const:`telegram.constants.MessageEntityType.STRIKETHROUGH`"""
    TEXT_LINK: Final[str] = constants.MessageEntityType.TEXT_LINK
    """:const:`telegram.constants.MessageEntityType.TEXT_LINK`"""
    TEXT_MENTION: Final[str] = constants.MessageEntityType.TEXT_MENTION
    """:const:`telegram.constants.MessageEntityType.TEXT_MENTION`"""
    UNDERLINE: Final[str] = constants.MessageEntityType.UNDERLINE
    """:const:`telegram.constants.MessageEntityType.UNDERLINE`"""
    URL: Final[str] = constants.MessageEntityType.URL
    """:const:`telegram.constants.MessageEntityType.URL`"""
