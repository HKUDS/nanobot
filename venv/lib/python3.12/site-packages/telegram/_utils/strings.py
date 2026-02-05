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
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU Lesser Public License for more details.
#
# You should have received a copy of the GNU Lesser Public License
# along with this program.  If not, see [http://www.gnu.org/licenses/].
"""This module contains a helper functions related to string manipulation.

Warning:
    Contents of this module are intended to be used internally by the library and *not* by the
    user. Changes to this module are not considered breaking changes and may not be documented in
    the changelog.
"""

from telegram._utils.enum import StringEnum

# TODO: Remove this when https://github.com/PyCQA/pylint/issues/6887 is resolved.
# pylint: disable=invalid-enum-extension


class TextEncoding(StringEnum):
    """This enum contains encoding schemes for text.

    .. versionadded:: 21.5
    """

    __slots__ = ()

    UTF_8 = "utf-8"
    UTF_16_LE = "utf-16-le"


def to_camel_case(snake_str: str) -> str:
    """Converts a snake_case string to camelCase.

    Args:
        snake_str (:obj:`str`): The string to convert.

    Returns:
        :obj:`str`: The converted string.
    """
    components = snake_str.split("_")
    return components[0] + "".join(x.title() for x in components[1:])
