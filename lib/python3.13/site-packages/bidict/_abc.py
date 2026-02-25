# Copyright 2009-2024 Joshua Bronson. All rights reserved.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.


#                             * Code review nav *
#                        (see comments in __init__.py)
# ============================================================================
# ← Prev: __init__.py          Current: _abc.py               Next: _base.py →
# ============================================================================


"""Provide the :class:`BidirectionalMapping` abstract base class."""

from __future__ import annotations

import typing as t
from abc import abstractmethod

from ._typing import KT
from ._typing import VT


class BidirectionalMapping(t.Mapping[KT, VT]):
    """Abstract base class for bidirectional mapping types.

    Extends :class:`collections.abc.Mapping` primarily by adding the
    (abstract) :attr:`inverse` property,
    which implementers of :class:`BidirectionalMapping`
    should override to return a reference to the inverse
    :class:`BidirectionalMapping` instance.
    """

    __slots__ = ()

    @property
    @abstractmethod
    def inverse(self) -> BidirectionalMapping[VT, KT]:
        """The inverse of this bidirectional mapping instance.

        *See also* :attr:`bidict.BidictBase.inverse`, :attr:`bidict.BidictBase.inv`

        :raises NotImplementedError: Meant to be overridden in subclasses.
        """
        # The @abstractmethod decorator prevents subclasses from being instantiated unless they
        # override this method. But an overriding implementation may merely return super().inverse,
        # in which case this implementation is used. Raise NotImplementedError to indicate that
        # subclasses must actually provide their own implementation.
        raise NotImplementedError

    def __inverted__(self) -> t.Iterator[tuple[VT, KT]]:
        """Get an iterator over the items in :attr:`inverse`.

        This is functionally equivalent to iterating over the items in the
        forward mapping and inverting each one on the fly, but this provides a
        more efficient implementation: Assuming the already-inverted items
        are stored in :attr:`inverse`, just return an iterator over them directly.

        Providing this default implementation enables external functions,
        particularly :func:`~bidict.inverted`, to use this optimized
        implementation when available, instead of having to invert on the fly.

        *See also* :func:`bidict.inverted`
        """
        return iter(self.inverse.items())


class MutableBidirectionalMapping(BidirectionalMapping[KT, VT], t.MutableMapping[KT, VT]):
    """Abstract base class for mutable bidirectional mapping types."""

    __slots__ = ()


#                             * Code review nav *
# ============================================================================
# ← Prev: __init__.py          Current: _abc.py               Next: _base.py →
# ============================================================================
