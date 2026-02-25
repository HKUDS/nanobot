# Copyright 2009-2024 Joshua Bronson. All rights reserved.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.


#                             * Code review nav *
#                        (see comments in __init__.py)
# ============================================================================
# ← Prev: _base.py            Current: _frozen.py           Next: _bidict.py →
# ============================================================================

"""Provide :class:`frozenbidict`, an immutable, hashable bidirectional mapping type."""

from __future__ import annotations

import typing as t

from ._base import BidictBase
from ._typing import KT
from ._typing import VT


class frozenbidict(BidictBase[KT, VT]):
    """Immutable, hashable bidict type."""

    _hash: int

    if t.TYPE_CHECKING:

        @property
        def inverse(self) -> frozenbidict[VT, KT]: ...

        @property
        def inv(self) -> frozenbidict[VT, KT]: ...

    def __hash__(self) -> int:
        """The hash of this bidict as determined by its items."""
        if getattr(self, '_hash', None) is None:
            # The following is like hash(frozenset(self.items()))
            # but more memory efficient. See also: https://bugs.python.org/issue46684
            self._hash = t.ItemsView(self)._hash()
        return self._hash


#                             * Code review nav *
# ============================================================================
# ← Prev: _base.py            Current: _frozen.py           Next: _bidict.py →
# ============================================================================
