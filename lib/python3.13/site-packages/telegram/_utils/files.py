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
"""This module contains helper functions related to handling of files.

.. versionchanged:: 20.0
   Previously, the contents of this module were available through the (no longer existing)
   module ``telegram._utils.helpers``.

Warning:
    Contents of this module are intended to be used internally by the library and *not* by the
    user. Changes to this module are not considered breaking changes and may not be documented in
    the changelog.
"""

from pathlib import Path
from typing import IO, TYPE_CHECKING, TypeVar, cast, overload

from telegram._utils.types import FileInput, FilePathInput

if TYPE_CHECKING:
    from typing import Any

    from telegram import InputFile, TelegramObject

_T = TypeVar("_T", bound="bytes | InputFile | str | Path | None")


@overload
def load_file(obj: IO[bytes]) -> tuple[str | None, bytes]: ...


@overload
def load_file(obj: _T) -> tuple[None, _T]: ...


def load_file(
    obj: "FileInput | None",
) -> tuple[str | None, "bytes | InputFile | str | Path | None"]:
    """If the input is a file handle, read the data and name and return it. Otherwise, return
    the input unchanged.
    """
    if obj is None:
        return None, None

    try:
        contents = obj.read()  # type: ignore[union-attr]
    except AttributeError:
        return None, cast("bytes | InputFile | str | Path", obj)

    filename = guess_file_name(obj)

    return filename, contents


def guess_file_name(obj: FileInput) -> str | None:
    """If the input is a file handle, read name and return it. Otherwise, return
    the input unchanged.
    """
    if hasattr(obj, "name") and not isinstance(obj.name, int):
        return Path(obj.name).name

    return None


def is_local_file(obj: FilePathInput | None) -> bool:
    """
    Checks if a given string is a file on local system.

    Args:
        obj (:obj:`str`): The string to check.
    """
    if obj is None:
        return False

    path = Path(obj)
    try:
        return path.is_file()
    except Exception:
        return False


def parse_file_input(  # pylint: disable=too-many-return-statements
    file_input: "FileInput | TelegramObject",
    tg_type: type["TelegramObject"] | None = None,
    filename: str | None = None,
    attach: bool = False,
    local_mode: bool = False,
) -> "str | InputFile | Any":
    """
    Parses input for sending files:

    * For string input, if the input is an absolute path of a local file:

        * if ``local_mode`` is ``True``, adds the ``file://`` prefix. If the input is a relative
        path of a local file, computes the absolute path and adds the ``file://`` prefix.
        * if ``local_mode`` is ``False``, loads the file as binary data and builds an
          :class:`InputFile` from that

      Returns the input unchanged, otherwise.
    * :class:`pathlib.Path` objects are treated the same way as strings.
    * For IO and bytes input, returns an :class:`telegram.InputFile`.
    * If :attr:`tg_type` is specified and the input is of that type, returns the ``file_id``
      attribute.

    Args:
        file_input (:obj:`str` | :obj:`bytes` | :term:`file object` | :class:`~telegram.InputFile`\
            | Telegram media object): The input to parse.
        tg_type (:obj:`type`, optional): The Telegram media type the input can be. E.g.
            :class:`telegram.Animation`.
        filename (:obj:`str`, optional): The filename. Only relevant in case an
            :class:`telegram.InputFile` is returned.
        attach (:obj:`bool`, optional): Pass :obj:`True` if the parameter this file belongs to in
            the request to Telegram should point to the multipart data via an ``attach://`` URI.
            Defaults to `False`. Only relevant if an :class:`telegram.InputFile` is returned.
        local_mode (:obj:`bool`, optional): Pass :obj:`True` if the bot is running an api server
            in ``--local`` mode.

    Returns:
        :obj:`str` | :class:`telegram.InputFile` | :obj:`object`: The parsed input or the untouched
        :attr:`file_input`, in case it's no valid file input.
    """
    # Importing on file-level yields cyclic Import Errors
    from telegram import InputFile  # pylint: disable=import-outside-toplevel  # noqa: PLC0415

    if isinstance(file_input, str) and file_input.startswith("file://"):
        if not local_mode:
            raise ValueError("Specified file input is a file URI, but local mode is not enabled.")
        return file_input
    if isinstance(file_input, str | Path):
        if is_local_file(file_input):
            path = Path(file_input)
            if local_mode:
                return path.absolute().as_uri()
            with path.open(mode="rb") as file_handle:
                return InputFile(file_handle, filename=filename, attach=attach)

        return file_input
    if isinstance(file_input, bytes):
        return InputFile(file_input, filename=filename, attach=attach)
    if hasattr(file_input, "read"):
        return InputFile(cast("IO", file_input), filename=filename, attach=attach)
    if tg_type and isinstance(file_input, tg_type):
        return file_input.file_id  # type: ignore[attr-defined]
    return file_input
