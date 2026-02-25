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
"""This module contains auxiliary functionality for parsing MessageEntity objects.

Warning:
    Contents of this module are intended to be used internally by the library and *not* by the
    user. Changes to this module are not considered breaking changes and may not be documented in
    the changelog.
"""

from collections.abc import Sequence

from telegram._messageentity import MessageEntity
from telegram._utils.strings import TextEncoding


def parse_message_entity(text: str, entity: MessageEntity) -> str:
    """Returns the text from a given :class:`telegram.MessageEntity`.

    Args:
        text (:obj:`str`): The text to extract the entity from.
        entity (:class:`telegram.MessageEntity`): The entity to extract the text from.

    Returns:
        :obj:`str`: The text of the given entity.
    """
    entity_text = text.encode(TextEncoding.UTF_16_LE)
    entity_text = entity_text[entity.offset * 2 : (entity.offset + entity.length) * 2]

    return entity_text.decode(TextEncoding.UTF_16_LE)


def parse_message_entities(
    text: str, entities: Sequence[MessageEntity], types: Sequence[str] | None = None
) -> dict[MessageEntity, str]:
    """
    Returns a :obj:`dict` that maps :class:`telegram.MessageEntity` to :obj:`str`.
    It contains entities filtered by their ``type`` attribute as
    the key, and the text that each entity belongs to as the value of the :obj:`dict`.

    Args:
        text (:obj:`str`): The text to extract the entity from.
        entities (list[:class:`telegram.MessageEntity`]): The entities to extract the text from.
        types (list[:obj:`str`], optional): List of ``MessageEntity`` types as strings. If the
            ``type`` attribute of an entity is contained in this list, it will be returned.
            Defaults to :attr:`telegram.MessageEntity.ALL_TYPES`.

    Returns:
        dict[:class:`telegram.MessageEntity`, :obj:`str`]: A dictionary of entities mapped to
        the text that belongs to them, calculated based on UTF-16 codepoints.
    """
    if types is None:
        types = MessageEntity.ALL_TYPES

    return {
        entity: parse_message_entity(text, entity) for entity in entities if entity.type in types
    }
