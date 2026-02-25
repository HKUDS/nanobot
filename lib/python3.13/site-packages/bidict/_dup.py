# Copyright 2009-2024 Joshua Bronson. All rights reserved.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.


"""Provide :class:`OnDup` and related functionality."""

from __future__ import annotations

import typing as t
from enum import Enum


class OnDupAction(Enum):
    """An action to take to prevent duplication from occurring."""

    #: Raise a :class:`~bidict.DuplicationError`.
    RAISE = 'RAISE'
    #: Overwrite existing items with new items.
    DROP_OLD = 'DROP_OLD'
    #: Keep existing items and drop new items.
    DROP_NEW = 'DROP_NEW'

    def __repr__(self) -> str:
        return f'{self.__class__.__name__}.{self.name}'


RAISE: t.Final[OnDupAction] = OnDupAction.RAISE
DROP_OLD: t.Final[OnDupAction] = OnDupAction.DROP_OLD
DROP_NEW: t.Final[OnDupAction] = OnDupAction.DROP_NEW


class OnDup(t.NamedTuple):
    r"""A combination of :class:`~bidict.OnDupAction`\s specifying how to handle various types of duplication.

    The :attr:`~OnDup.key` field specifies what action to take when a duplicate key is encountered.

    The :attr:`~OnDup.val` field specifies what action to take when a duplicate value is encountered.

    In the case of both key and value duplication across two different items,
    only :attr:`~OnDup.val` is used.

    *See also* :ref:`basic-usage:Values Must Be Unique`
    (https://bidict.rtfd.io/basic-usage.html#values-must-be-unique)
    """

    key: OnDupAction = DROP_OLD
    val: OnDupAction = RAISE


#: Default :class:`OnDup` used for the
#: :meth:`~bidict.bidict.__init__`,
#: :meth:`~bidict.bidict.__setitem__`, and
#: :meth:`~bidict.bidict.update` methods.
ON_DUP_DEFAULT: t.Final[OnDup] = OnDup(key=DROP_OLD, val=RAISE)
#: An :class:`OnDup` whose members are all :obj:`RAISE`.
ON_DUP_RAISE: t.Final[OnDup] = OnDup(key=RAISE, val=RAISE)
#: An :class:`OnDup` whose members are all :obj:`DROP_OLD`.
ON_DUP_DROP_OLD: t.Final[OnDup] = OnDup(key=DROP_OLD, val=DROP_OLD)
