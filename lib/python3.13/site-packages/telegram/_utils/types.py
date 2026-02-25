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
"""This module contains custom typing aliases for internal use within the library.

Warning:
    Contents of this module are intended to be used internally by the library and *not* by the
    user. Changes to this module are not considered breaking changes and may not be documented in
    the changelog.
"""

import datetime as dtm
from collections.abc import Callable, Collection
from pathlib import Path
from typing import IO, TYPE_CHECKING, Any, Literal, TypeAlias, TypeVar, Union

from telegram._utils.defaultvalue import DefaultValue

if TYPE_CHECKING:
    from telegram import (
        ForceReply,
        InlineKeyboardMarkup,
        InputFile,
        ReplyKeyboardMarkup,
        ReplyKeyboardRemove,
    )

# We guarantee that InputFile will be defined at runtime, so we can use a string here and ignore
# ruff.
# See https://github.com/python-telegram-bot/python-telegram-bot/pull/4827#issuecomment-2973060875
# on why we're doing this workaround.
# TODO: Use `type` syntax when we drop support for Python 3.11.
FileLike: TypeAlias = IO[bytes] | "InputFile"  # noqa: TC010
"""Either a bytes-stream (e.g. open file handler) or a :class:`telegram.InputFile`."""

FilePathInput: TypeAlias = str | Path
"""A filepath either as string or as :obj:`pathlib.Path` object."""

FileInput: TypeAlias = FilePathInput | FileLike | bytes | str
"""Valid input for passing files to Telegram. Either a file id as string, a file like object,
a local file path as string, :class:`pathlib.Path` or the file contents as :obj:`bytes`."""

JSONDict: TypeAlias = dict[str, Any]
"""Dictionary containing response from Telegram or data to send to the API."""

DVValueType = TypeVar("DVValueType")  # pylint: disable=invalid-name
DVType: TypeAlias = DVValueType | DefaultValue[DVValueType]
"""Generic type for a variable which can be either `type` or `DefaultValue[type]`."""
ODVInput: TypeAlias = DefaultValue[DVValueType] | DVValueType | DefaultValue[None] | None
"""Generic type for bot method parameters which can have defaults. ``ODVInput[type]`` is the same
as ``Union[DefaultValue[type], type, DefaultValue[None], None]``."""
DVInput: TypeAlias = DefaultValue[DVValueType] | DVValueType | DefaultValue[None]
"""Generic type for bot method parameters which can have defaults. ``DVInput[type]`` is the same
as ``Union[DefaultValue[type], type, DefaultValue[None]]``."""

RT = TypeVar("RT")
SCT: TypeAlias = RT | Collection[RT]  # pylint: disable=invalid-name
"""Single instance or collection of instances."""

# See comment above on why we're stuck using a Union here.
ReplyMarkup: TypeAlias = Union[
    "InlineKeyboardMarkup", "ReplyKeyboardMarkup", "ReplyKeyboardRemove", "ForceReply"
]
"""Type alias for reply markup objects.

.. versionadded:: 20.0
"""

FieldTuple: TypeAlias = tuple[str, bytes | IO[bytes], str]
"""Alias for return type of `InputFile.field_tuple`."""
UploadFileDict: TypeAlias = dict[str, FieldTuple]
"""Dictionary containing file data to be uploaded to the API."""

HTTPVersion: TypeAlias = Literal["1.1", "2.0", "2"]
"""Allowed HTTP versions.

.. versionadded:: 20.4"""

CorrectOptionID: TypeAlias = Literal[0, 1, 2, 3, 4, 5, 6, 7, 8, 9]  # pylint: disable=invalid-name

MarkdownVersion: TypeAlias = Literal[1, 2]

SocketOpt: TypeAlias = (
    tuple[int, int, int] | tuple[int, int, bytes | bytearray] | tuple[int, int, None, int]
)

BaseUrl: TypeAlias = str | Callable[[str], str]

TimePeriod: TypeAlias = int | dtm.timedelta
