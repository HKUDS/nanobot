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
"""This module contains a mutable mapping that keeps track of the keys that where accessed.

.. versionadded:: 20.0

Warning:
    Contents of this module are intended to be used internally by the library and *not* by the
    user. Changes to this module are not considered breaking changes and may not be documented in
    the changelog.
"""

from collections import UserDict
from collections.abc import Mapping
from typing import Final, Generic, TypeVar

from telegram._utils.defaultvalue import DEFAULT_NONE, DefaultValue

_VT = TypeVar("_VT")
_KT = TypeVar("_KT")
_T = TypeVar("_T")


class TrackingDict(UserDict, Generic[_KT, _VT]):
    """Mutable mapping that keeps track of which keys where accessed with write access.
    Read-access is not tracked.

    Note:
        * ``setdefault()`` and ``pop`` are considered writing only depending on whether the
            key is present
        * deleting values is considered writing
    """

    DELETED: Final = object()
    """Special marker indicating that an entry was deleted."""

    __slots__ = ("_write_access_keys",)

    def __init__(self) -> None:
        super().__init__()
        self._write_access_keys: set[_KT] = set()

    def __setitem__(self, key: _KT, value: _VT) -> None:
        self.__track_write(key)
        super().__setitem__(key, value)

    def __delitem__(self, key: _KT) -> None:
        self.__track_write(key)
        super().__delitem__(key)

    def __track_write(self, key: _KT | set[_KT]) -> None:
        if isinstance(key, set):
            self._write_access_keys |= key
        else:
            self._write_access_keys.add(key)

    def pop_accessed_keys(self) -> set[_KT]:
        """Returns all keys that were write-accessed since the last time this method was called."""
        out = self._write_access_keys
        self._write_access_keys = set()
        return out

    def pop_accessed_write_items(self) -> list[tuple[_KT, _VT]]:
        """
        Returns all keys & corresponding values as set of tuples that were write-accessed since
        the last time this method was called. If a key was deleted, the value will be
        :attr:`DELETED`.
        """
        keys = self.pop_accessed_keys()
        return [(key, self.get(key, self.DELETED)) for key in keys]

    def mark_as_accessed(self, key: _KT) -> None:
        """Use this method have the key returned again in the next call to
        :meth:`pop_accessed_write_items` or :meth:`pop_accessed_keys`
        """
        self._write_access_keys.add(key)

    # Override methods to track access

    def update_no_track(self, mapping: Mapping[_KT, _VT]) -> None:
        """Like ``update``, but doesn't count towards write access."""
        for key, value in mapping.items():
            self.data[key] = value

    # Mypy seems a bit inconsistent about what it wants as types for `default` and return value
    # so we just ignore a bit
    def pop(  # type: ignore[override]
        self,
        key: _KT,
        default: _VT = DEFAULT_NONE,  # type: ignore[assignment]
    ) -> _VT:
        if key in self:
            self.__track_write(key)
        if isinstance(default, DefaultValue):
            return super().pop(key)
        return super().pop(key, default=default)

    def clear(self) -> None:
        self.__track_write(set(super().keys()))
        super().clear()

    # Mypy seems a bit inconsistent about what it wants as types for `default` and return value
    # so we just ignore a bit
    def setdefault(self: "TrackingDict[_KT, _T]", key: _KT, default: _T | None = None) -> _T:
        if key in self:
            return self[key]

        self.__track_write(key)
        self[key] = default  # type: ignore[assignment]
        return default  # type: ignore[return-value]
