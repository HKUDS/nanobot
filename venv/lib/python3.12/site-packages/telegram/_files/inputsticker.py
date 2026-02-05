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
"""This module contains an object that represents a Telegram InputSticker."""

from collections.abc import Sequence
from typing import TYPE_CHECKING

from telegram._files.sticker import MaskPosition
from telegram._telegramobject import TelegramObject
from telegram._utils.argumentparsing import parse_sequence_arg
from telegram._utils.files import parse_file_input
from telegram._utils.types import FileInput, JSONDict

if TYPE_CHECKING:
    from telegram._files.inputfile import InputFile


class InputSticker(TelegramObject):
    """
    This object describes a sticker to be added to a sticker set.

    .. versionadded:: 20.2

    .. versionchanged:: 21.1
        As of Bot API 7.2, the new argument :paramref:`format` is a required argument, and thus the
        order of the arguments has changed.

    Args:
        sticker (:obj:`str` | :term:`file object` | :class:`~telegram.InputFile` | :obj:`bytes` \
            | :class:`pathlib.Path`): The
            added sticker. |uploadinputnopath| Animated and video stickers can't be uploaded via
            HTTP URL.
        emoji_list (Sequence[:obj:`str`]): Sequence of
            :tg-const:`telegram.constants.StickerLimit.MIN_STICKER_EMOJI` -
            :tg-const:`telegram.constants.StickerLimit.MAX_STICKER_EMOJI` emoji associated with the
            sticker.
        mask_position (:class:`telegram.MaskPosition`, optional): Position where the mask should be
            placed on faces. For ":tg-const:`telegram.constants.StickerType.MASK`" stickers only.
        keywords (Sequence[:obj:`str`], optional): Sequence of
            0-:tg-const:`telegram.constants.StickerLimit.MAX_SEARCH_KEYWORDS` search keywords
            for the sticker with the total length of up to
            :tg-const:`telegram.constants.StickerLimit.MAX_KEYWORD_LENGTH` characters. For
            ":tg-const:`telegram.constants.StickerType.REGULAR`" and
            ":tg-const:`telegram.constants.StickerType.CUSTOM_EMOJI`" stickers only.
        format (:obj:`str`): Format of the added sticker, must be one of
            :tg-const:`telegram.constants.StickerFormat.STATIC` for a
            ``.WEBP`` or ``.PNG`` image, :tg-const:`telegram.constants.StickerFormat.ANIMATED`
            for a ``.TGS`` animation, :tg-const:`telegram.constants.StickerFormat.VIDEO` for a
            ``.WEBM`` video.

            .. versionadded:: 21.1

    Attributes:
        sticker (:obj:`str` | :class:`telegram.InputFile`): The added sticker.
        emoji_list (tuple[:obj:`str`]): Tuple of
            :tg-const:`telegram.constants.StickerLimit.MIN_STICKER_EMOJI` -
            :tg-const:`telegram.constants.StickerLimit.MAX_STICKER_EMOJI` emoji associated with the
            sticker.
        mask_position (:class:`telegram.MaskPosition`): Optional. Position where the mask should be
            placed on faces. For ":tg-const:`telegram.constants.StickerType.MASK`" stickers only.
        keywords (tuple[:obj:`str`]): Optional. Tuple of
            0-:tg-const:`telegram.constants.StickerLimit.MAX_SEARCH_KEYWORDS` search keywords
            for the sticker with the total length of up to
            :tg-const:`telegram.constants.StickerLimit.MAX_KEYWORD_LENGTH` characters. For
            ":tg-const:`telegram.constants.StickerType.REGULAR`" and
            ":tg-const:`telegram.constants.StickerType.CUSTOM_EMOJI`" stickers only.
            ":tg-const:`telegram.constants.StickerType.CUSTOM_EMOJI`" stickers only.
        format (:obj:`str`): Format of the added sticker, must be one of
            :tg-const:`telegram.constants.StickerFormat.STATIC` for a
            ``.WEBP`` or ``.PNG`` image, :tg-const:`telegram.constants.StickerFormat.ANIMATED`
            for a ``.TGS`` animation, :tg-const:`telegram.constants.StickerFormat.VIDEO` for a
            ``.WEBM`` video.

            .. versionadded:: 21.1
    """

    __slots__ = ("emoji_list", "format", "keywords", "mask_position", "sticker")

    def __init__(
        self,
        sticker: FileInput,
        emoji_list: Sequence[str],
        format: str,  # pylint: disable=redefined-builtin
        mask_position: MaskPosition | None = None,
        keywords: Sequence[str] | None = None,
        *,
        api_kwargs: JSONDict | None = None,
    ):
        super().__init__(api_kwargs=api_kwargs)

        # We use local_mode=True because we don't have access to the actual setting and want
        # things to work in local mode.
        self.sticker: str | InputFile = parse_file_input(
            sticker,
            local_mode=True,
            attach=True,
        )
        self.emoji_list: tuple[str, ...] = parse_sequence_arg(emoji_list)
        self.format: str = format
        self.mask_position: MaskPosition | None = mask_position
        self.keywords: tuple[str, ...] = parse_sequence_arg(keywords)

        self._freeze()
