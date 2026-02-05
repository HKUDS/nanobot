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
"""Helper utilities around Telegram Objects first_name, last_name and username.
.. versionadded:: 22.4

Warning:
    Contents of this module are intended to be used internally by the library and *not* by the
    user. Changes to this module are not considered breaking changes and may not be documented in
    the changelog.
"""

from typing import TYPE_CHECKING, Protocol, TypeVar, overload

TeleUserLike = TypeVar("TeleUserLike", bound="UserLike")
TeleUserLikeOptional = TypeVar("TeleUserLikeOptional", bound="UserLikeOptional")

if TYPE_CHECKING:
    from typing import type_check_only

    @type_check_only
    class UserLike(Protocol):
        first_name: str
        last_name: str | None
        username: str | None

    @type_check_only
    class UserLikeOptional(Protocol):
        first_name: str | None
        last_name: str | None
        username: str | None


@overload
def get_name(userlike: TeleUserLike) -> str: ...
@overload
def get_name(userlike: TeleUserLikeOptional) -> str | None: ...


def get_name(userlike: TeleUserLike | TeleUserLikeOptional) -> str | None:
    """Returns ``username`` prefixed with "@". If  ``username`` is not available, calls
    :func:`get_full_name` below`.
    """
    if userlike.username:
        return f"@{userlike.username}"
    return get_full_name(userlike=userlike)


@overload
def get_full_name(userlike: TeleUserLike) -> str: ...
@overload
def get_full_name(userlike: TeleUserLikeOptional) -> str | None: ...


def get_full_name(userlike: TeleUserLike | TeleUserLikeOptional) -> str | None:
    """
    If parameter ``first_name`` is not :obj:`None`, gives
    ``first_name`` followed by (if available) `UserLike.last_name`. Otherwise,
    :obj:`None` is returned.
    """
    if not userlike.first_name:
        return None
    if userlike.last_name:
        return f"{userlike.first_name} {userlike.last_name}"
    return userlike.first_name


# We isolate these TypeVars to accomodiate telegram objects with ``username``
# and no ``first_name`` or ``last_name`` (e.g ``ChatShared``)
TeleLinkable = TypeVar("TeleLinkable", bound="Linkable")
TeleLinkableOptional = TypeVar("TeleLinkableOptional", bound="LinkableOptional")

if TYPE_CHECKING:

    @type_check_only
    class Linkable(Protocol):
        username: str

    @type_check_only
    class LinkableOptional(Protocol):
        username: str | None


@overload
def get_link(linkable: TeleLinkable) -> str: ...
@overload
def get_link(linkable: TeleLinkableOptional) -> str | None: ...


def get_link(linkable: TeleLinkable | TeleLinkableOptional) -> str | None:
    """If ``username`` is available, returns a t.me link of the user/chat."""
    if linkable.username:
        return f"https://t.me/{linkable.username}"
    return None
