# Copyright 2009-2024 Joshua Bronson. All rights reserved.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.


"""Provide all bidict exceptions."""

from __future__ import annotations


class BidictException(Exception):
    """Base class for bidict exceptions."""


class DuplicationError(BidictException):
    """Base class for exceptions raised when uniqueness is violated
    as per the :attr:`~bidict.RAISE` :class:`~bidict.OnDupAction`.
    """


class KeyDuplicationError(DuplicationError):
    """Raised when a given key is not unique."""


class ValueDuplicationError(DuplicationError):
    """Raised when a given value is not unique."""


class KeyAndValueDuplicationError(KeyDuplicationError, ValueDuplicationError):
    """Raised when a given item's key and value are not unique.

    That is, its key duplicates that of another item,
    and its value duplicates that of a different other item.
    """
