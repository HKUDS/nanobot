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
"""This module contains auxiliary functionality for building strings for __repr__ method.

Warning:
    Contents of this module are intended to be used internally by the library and *not* by the
    user. Changes to this module are not considered breaking changes and may not be documented in
    the changelog.
"""

from typing import Any


def build_repr_with_selected_attrs(obj: object, **kwargs: Any) -> str:
    """Create ``__repr__`` string in the style ``Classname[arg1=1, arg2=2]``.

    The square brackets emphasize the fact that an object cannot be instantiated
    from this string.

    Attributes that are to be used in the representation, are passed as kwargs.
    """
    return (
        f"{obj.__class__.__name__}"
        # square brackets emphasize that an object cannot be instantiated with these params
        f"[{', '.join(_stringify(name, value) for name, value in kwargs.items())}]"
    )


def _stringify(key: str, val: Any) -> str:
    return f"{key}={val.__qualname__ if callable(val) else val}"
