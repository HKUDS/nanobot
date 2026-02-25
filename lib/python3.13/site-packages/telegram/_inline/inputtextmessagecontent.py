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
"""This module contains the classes that represent Telegram InputTextMessageContent."""

from collections.abc import Sequence
from typing import TYPE_CHECKING

from telegram._inline.inputmessagecontent import InputMessageContent
from telegram._messageentity import MessageEntity
from telegram._utils.argumentparsing import parse_lpo_and_dwpp, parse_sequence_arg
from telegram._utils.defaultvalue import DEFAULT_NONE
from telegram._utils.types import JSONDict, ODVInput

if TYPE_CHECKING:
    from telegram._linkpreviewoptions import LinkPreviewOptions


class InputTextMessageContent(InputMessageContent):
    """
    Represents the content of a text message to be sent as the result of an inline query.

    Objects of this class are comparable in terms of equality. Two objects of this class are
    considered equal, if their :attr:`message_text` is equal.

    Examples:
        :any:`Inline Bot <examples.inlinebot>`

    Args:
        message_text (:obj:`str`): Text of the message to be sent,
            :tg-const:`telegram.constants.MessageLimit.MIN_TEXT_LENGTH`-
            :tg-const:`telegram.constants.MessageLimit.MAX_TEXT_LENGTH` characters after entities
            parsing.
        parse_mode (:obj:`str`, optional): |parse_mode|
        entities (Sequence[:class:`telegram.MessageEntity`], optional): |caption_entities|

            .. versionchanged:: 20.0
                |sequenceclassargs|

        link_preview_options (:obj:`LinkPreviewOptions`, optional): Link preview generation
            options for the message. Mutually exclusive with
            :paramref:`disable_web_page_preview`.

            .. versionadded:: 20.8

    Keyword Args:
        disable_web_page_preview (:obj:`bool`, optional): Disables link previews for links in the
            sent message. Convenience parameter for setting :paramref:`link_preview_options`.
            Mutually exclusive with :paramref:`link_preview_options`.

            .. versionchanged:: 20.8
                Bot API 7.0 introduced :paramref:`link_preview_options` replacing this
                argument. PTB will automatically convert this argument to that one, but
                for advanced options, please use :paramref:`link_preview_options` directly.

            .. versionchanged:: 21.0
                |keyword_only_arg|

    Attributes:
        message_text (:obj:`str`): Text of the message to be sent,
            :tg-const:`telegram.constants.MessageLimit.MIN_TEXT_LENGTH`-
            :tg-const:`telegram.constants.MessageLimit.MAX_TEXT_LENGTH` characters after entities
            parsing.
        parse_mode (:obj:`str`): Optional. |parse_mode|
        entities (tuple[:class:`telegram.MessageEntity`]): Optional. |captionentitiesattr|

            .. versionchanged:: 20.0

                * |tupleclassattrs|
                * |alwaystuple|
        link_preview_options (:obj:`LinkPreviewOptions`): Optional. Link preview generation
            options for the message.

            .. versionadded:: 20.8

    """

    __slots__ = ("entities", "link_preview_options", "message_text", "parse_mode")

    def __init__(
        self,
        message_text: str,
        parse_mode: ODVInput[str] = DEFAULT_NONE,
        entities: Sequence[MessageEntity] | None = None,
        link_preview_options: ODVInput["LinkPreviewOptions"] = DEFAULT_NONE,
        *,
        disable_web_page_preview: bool | None = None,
        api_kwargs: JSONDict | None = None,
    ):
        super().__init__(api_kwargs=api_kwargs)

        with self._unfrozen():
            # Required
            self.message_text: str = message_text
            # Optionals
            self.parse_mode: ODVInput[str] = parse_mode
            self.entities: tuple[MessageEntity, ...] = parse_sequence_arg(entities)
            self.link_preview_options: ODVInput[LinkPreviewOptions] = parse_lpo_and_dwpp(
                disable_web_page_preview, link_preview_options
            )

            self._id_attrs = (self.message_text,)
