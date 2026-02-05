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
"""This module contains helper functions related to warnings issued by the library.

.. versionadded:: 20.0

Warning:
    Contents of this module are intended to be used internally by the library and *not* by the
    user. Changes to this module are not considered breaking changes and may not be documented in
    the changelog.
"""

import warnings

from telegram.warnings import PTBUserWarning


def warn(
    message: str | PTBUserWarning,
    category: type[Warning] = PTBUserWarning,
    stacklevel: int = 0,
) -> None:
    """
    Helper function used as a shortcut for warning with default values.

    .. versionadded:: 20.0

    Args:
        message (:obj:`str` | :obj:`PTBUserWarning`): Specify the warnings message to pass to
            ``warnings.warn()``.

            .. versionchanged:: 21.2
                Now also accepts a :obj:`PTBUserWarning` instance.

        category (:obj:`type[Warning]`, optional): Specify the Warning class to pass to
            ``warnings.warn()``. Defaults to :class:`telegram.warnings.PTBUserWarning`.
        stacklevel (:obj:`int`, optional): Specify the stacklevel to pass to ``warnings.warn()``.
            Pass the same value as you'd pass directly to ``warnings.warn()``. Defaults to ``0``.
    """
    warnings.warn(message, category=category, stacklevel=stacklevel + 1)
