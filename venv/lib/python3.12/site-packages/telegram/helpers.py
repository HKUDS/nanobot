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
"""This module contains convenience helper functions.

.. versionchanged:: 20.0
   Previously, the contents of this module were available through the (no longer existing)
   module ``telegram.utils.helpers``.
"""

__all__ = (
    "create_deep_linked_url",
    "effective_message_type",
    "escape_markdown",
    "mention_html",
    "mention_markdown",
)

import re
from html import escape
from typing import TYPE_CHECKING

from telegram._utils.types import MarkdownVersion
from telegram.constants import MessageLimit, MessageType

if TYPE_CHECKING:
    from telegram import Message, Update


def escape_markdown(
    text: str, version: MarkdownVersion = 1, entity_type: str | None = None
) -> str:
    """Helper function to escape telegram markup symbols.

    .. versionchanged:: 20.3
        Custom emoji entity escaping is now supported.

    Args:
        text (:obj:`str`): The text.
        version (:obj:`int` | :obj:`str`): Use to specify the version of telegrams Markdown.
            Either ``1`` or ``2``. Defaults to ``1``.
        entity_type (:obj:`str`, optional): For the entity types
            :tg-const:`telegram.MessageEntity.PRE`, :tg-const:`telegram.MessageEntity.CODE` and
            the link part of :tg-const:`telegram.MessageEntity.TEXT_LINK` and
            :tg-const:`telegram.MessageEntity.CUSTOM_EMOJI`, only certain characters need to be
            escaped in :tg-const:`telegram.constants.ParseMode.MARKDOWN_V2`. See the `official API
            documentation <https://core.telegram.org/bots/api#formatting-options>`_ for details.
            Only valid in combination with ``version=2``, will be ignored else.
    """
    if int(version) == 1:
        escape_chars = r"_*`["
    elif int(version) == 2:
        if entity_type in ["pre", "code"]:
            escape_chars = r"\`"
        elif entity_type in ["text_link", "custom_emoji"]:
            escape_chars = r"\)"
        else:
            escape_chars = r"\_*[]()~`>#+-=|{}.!"
    else:
        raise ValueError("Markdown version must be either 1 or 2!")

    return re.sub(f"([{re.escape(escape_chars)}])", r"\\\1", text)


def mention_html(user_id: int | str, name: str) -> str:
    """
    Helper function to create a user mention as HTML tag.

    Args:
        user_id (:obj:`int`): The user's id which you want to mention.
        name (:obj:`str`): The name the mention is showing.

    Returns:
        :obj:`str`: The inline mention for the user as HTML.
    """
    return f'<a href="tg://user?id={user_id}">{escape(name)}</a>'


def mention_markdown(user_id: int | str, name: str, version: MarkdownVersion = 1) -> str:
    """
    Helper function to create a user mention in Markdown syntax.

    Args:
        user_id (:obj:`int`): The user's id which you want to mention.
        name (:obj:`str`): The name the mention is showing.
        version (:obj:`int` | :obj:`str`): Use to specify the version of Telegram's Markdown.
            Either ``1`` or ``2``. Defaults to ``1``.

    Returns:
        :obj:`str`: The inline mention for the user as Markdown.
    """
    tg_link = f"tg://user?id={user_id}"
    if version == 1:
        return f"[{name}]({tg_link})"
    return f"[{escape_markdown(name, version=version)}]({tg_link})"


def effective_message_type(entity: "Message | Update") -> str | None:
    """
    Extracts the type of message as a string identifier from a :class:`telegram.Message` or a
    :class:`telegram.Update`.

    Args:
        entity (:class:`telegram.Update` | :class:`telegram.Message`): The ``update`` or
            ``message`` to extract from.

    Returns:
        :obj:`str` | :obj:`None`: One of :class:`telegram.constants.MessageType` if the entity
        contains a message that matches one of those types. :obj:`None` otherwise.

    """
    # Importing on file-level yields cyclic Import Errors
    from telegram import (  # pylint: disable=import-outside-toplevel  # noqa: PLC0415
        Message,
        Update,
    )

    if isinstance(entity, Message):
        message = entity
    elif isinstance(entity, Update):
        if not entity.effective_message:
            return None
        message = entity.effective_message
    else:
        raise TypeError(f"The entity is neither Message nor Update (got: {type(entity)})")

    for message_type in MessageType:
        if message[message_type]:
            return message_type

    return None


def create_deep_linked_url(
    bot_username: str, payload: str | None = None, group: bool = False
) -> str:
    """
    Creates a deep-linked URL for this :paramref:`~create_deep_linked_url.bot_username` with the
    specified :paramref:`~create_deep_linked_url.payload`. See
    https://core.telegram.org/bots/features#deep-linking to learn more.

    The :paramref:`~create_deep_linked_url.payload` may consist of the following characters:
    ``A-Z, a-z, 0-9, _, -``

    Note:
        Works well in conjunction with
        ``CommandHandler("start", callback, filters=filters.Regex('payload'))``

    Examples:
        * ``create_deep_linked_url(bot.get_me().username, "some-params")``
        * :any:`Deep Linking <examples.deeplinking>`

    Args:
        bot_username (:obj:`str`): The username to link to.
        payload (:obj:`str`, optional): Parameters to encode in the created URL.
        group (:obj:`bool`, optional): If :obj:`True` the user is prompted to select a group to
            add the bot to. If :obj:`False`, opens a one-on-one conversation with the bot.
            Defaults to :obj:`False`.

    Returns:
        :obj:`str`: An URL to start the bot with specific parameters.

    Raises:
        :exc:`ValueError`: If the length of the :paramref:`payload` exceeds \
        :tg-const:`telegram.constants.MessageLimit.DEEP_LINK_LENGTH` characters,
            contains invalid characters, or if the :paramref:`bot_username` is less than 4
            characters.
    """
    if bot_username is None or len(bot_username) <= 3:
        raise ValueError("You must provide a valid bot_username.")

    base_url = f"https://t.me/{bot_username}"
    if not payload:
        return base_url

    if len(payload) > MessageLimit.DEEP_LINK_LENGTH:
        raise ValueError(
            f"The deep-linking payload must not exceed {MessageLimit.DEEP_LINK_LENGTH} characters."
        )

    if not re.match(r"^[A-Za-z0-9_-]+$", payload):
        raise ValueError(
            "Only the following characters are allowed for deep-linked "
            "URLs: A-Z, a-z, 0-9, _ and -"
        )

    key = "startgroup" if group else "start"

    return f"{base_url}?{key}={payload}"
