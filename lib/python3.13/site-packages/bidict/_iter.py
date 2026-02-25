# Copyright 2009-2024 Joshua Bronson. All rights reserved.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.


"""Functions for iterating over items in a mapping."""

from __future__ import annotations

import typing as t
from operator import itemgetter

from ._typing import KT
from ._typing import VT
from ._typing import ItemsIter
from ._typing import Maplike
from ._typing import MapOrItems


def iteritems(arg: MapOrItems[KT, VT] = (), /, **kw: VT) -> ItemsIter[KT, VT]:
    """Yield the items from *arg* and *kw* in the order given."""
    if isinstance(arg, t.Mapping):
        yield from arg.items()
    elif isinstance(arg, Maplike):
        yield from ((k, arg[k]) for k in arg.keys())
    else:
        yield from arg
    yield from t.cast(ItemsIter[KT, VT], kw.items())


swap: t.Final = itemgetter(1, 0)


def inverted(arg: MapOrItems[KT, VT]) -> ItemsIter[VT, KT]:
    """Yield the inverse items of the provided object.

    If *arg* has a :func:`callable` ``__inverted__`` attribute,
    return the result of calling it.

    Otherwise, return an iterator over the items in `arg`,
    inverting each item on the fly.

    *See also* :attr:`bidict.BidirectionalMapping.__inverted__`
    """
    invattr = getattr(arg, '__inverted__', None)
    if callable(invattr):
        inv: ItemsIter[VT, KT] = invattr()
        return inv
    return map(swap, iteritems(arg))
