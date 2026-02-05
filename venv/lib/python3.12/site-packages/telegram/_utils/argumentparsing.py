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
"""This module contains helper functions related to parsing arguments for classes and methods.

Warning:
    Contents of this module are intended to be used internally by the library and *not* by the
    user. Changes to this module are not considered breaking changes and may not be documented in
    the changelog.
"""

import datetime as dtm
from collections.abc import Sequence
from typing import TYPE_CHECKING, Protocol, TypeVar, overload

from telegram._linkpreviewoptions import LinkPreviewOptions
from telegram._telegramobject import TelegramObject
from telegram._utils.types import JSONDict, ODVInput

if TYPE_CHECKING:
    from typing import type_check_only

    from telegram import Bot, FileCredentials

T = TypeVar("T")


def parse_sequence_arg(arg: Sequence[T] | None) -> tuple[T, ...]:
    """Parses an optional sequence into a tuple

    Args:
        arg (:obj:`Sequence`): The sequence to parse.

    Returns:
        :obj:`Tuple`: The sequence converted to a tuple or an empty tuple.
    """
    return tuple(arg) if arg else ()


@overload
def to_timedelta(arg: None) -> None: ...


@overload
def to_timedelta(
    arg: (
        int | float | dtm.timedelta  # noqa: PYI041 (be more explicit about `int` and `float` args)
    ),
) -> dtm.timedelta: ...


def to_timedelta(arg: int | float | dtm.timedelta | None) -> dtm.timedelta | None:  # noqa: PYI041
    """Parses an optional time period in seconds into a timedelta

    Args:
        arg (:obj:`int` | :class:`datetime.timedelta`, optional): The time period to parse.

    Returns:
        :obj:`timedelta`: The time period converted to a timedelta object or :obj:`None`.
    """
    if arg is None:
        return None
    if isinstance(arg, int | float):
        return dtm.timedelta(seconds=arg)
    return arg


def parse_lpo_and_dwpp(
    disable_web_page_preview: bool | None, link_preview_options: ODVInput[LinkPreviewOptions]
) -> ODVInput[LinkPreviewOptions]:
    """Wrapper around warn_about_deprecated_arg_return_new_arg. Takes care of converting
    disable_web_page_preview to LinkPreviewOptions.
    """
    if disable_web_page_preview and link_preview_options:
        raise ValueError(
            "Parameters `disable_web_page_preview` and `link_preview_options` are mutually "
            "exclusive."
        )

    if disable_web_page_preview is not None:
        link_preview_options = LinkPreviewOptions(is_disabled=disable_web_page_preview)

    return link_preview_options


Tele_co = TypeVar("Tele_co", bound=TelegramObject, covariant=True)
TeleCrypto_co = TypeVar("TeleCrypto_co", bound="HasDecryptMethod", covariant=True)

if TYPE_CHECKING:

    @type_check_only
    class HasDecryptMethod(Protocol):
        __slots__ = ()

        @classmethod
        def de_json_decrypted(
            cls: type[TeleCrypto_co],
            data: JSONDict,
            bot: "Bot | None",
            credentials: list["FileCredentials"],
        ) -> TeleCrypto_co: ...

        @classmethod
        def de_list_decrypted(
            cls: type[TeleCrypto_co],
            data: list[JSONDict],
            bot: "Bot | None",
            credentials: list["FileCredentials"],
        ) -> tuple[TeleCrypto_co, ...]: ...


def de_json_optional(
    data: JSONDict | None, cls: type[Tele_co], bot: "Bot | None"
) -> Tele_co | None:
    """Wrapper around TO.de_json that returns None if data is None."""
    if data is None:
        return None

    return cls.de_json(data, bot)


def de_json_decrypted_optional(
    data: JSONDict | None,
    cls: type[TeleCrypto_co],
    bot: "Bot | None",
    credentials: list["FileCredentials"],
) -> TeleCrypto_co | None:
    """Wrapper around TO.de_json_decrypted that returns None if data is None."""
    if data is None:
        return None

    return cls.de_json_decrypted(data, bot, credentials)


def de_list_optional(
    data: list[JSONDict] | None, cls: type[Tele_co], bot: "Bot | None"
) -> tuple[Tele_co, ...]:
    """Wrapper around TO.de_list that returns an empty list if data is None."""
    if data is None:
        return ()

    return cls.de_list(data, bot)


def de_list_decrypted_optional(
    data: list[JSONDict] | None,
    cls: type[TeleCrypto_co],
    bot: "Bot | None",
    credentials: list["FileCredentials"],
) -> tuple[TeleCrypto_co, ...]:
    """Wrapper around TO.de_list_decrypted that returns an empty list if data is None."""
    if data is None:
        return ()

    return cls.de_list_decrypted(data, bot, credentials)
