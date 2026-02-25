# Copyright 2009-2024 Joshua Bronson. All rights reserved.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.


#                             * Code review nav *
#                        (see comments in __init__.py)
# ============================================================================
# ← Prev: _bidict.py      Current: _orderedbase.py   Next: _orderedbidict.py →
# ============================================================================


"""Provide :class:`OrderedBidictBase`."""

from __future__ import annotations

import typing as t
from weakref import ref as weakref

from ._base import BidictBase
from ._base import Unwrites
from ._bidict import bidict
from ._iter import iteritems
from ._typing import KT
from ._typing import MISSING
from ._typing import OKT
from ._typing import OVT
from ._typing import VT
from ._typing import MapOrItems


AT = t.TypeVar('AT')  # attr type


class WeakAttr(t.Generic[AT]):
    """Descriptor to automatically manage (de)referencing the given slot as a weakref.

    See https://docs.python.org/3/howto/descriptor.html#managed-attributes
    for an intro to using descriptors like this for managed attributes.
    """

    def __init__(self, *, slot: str) -> None:
        self.slot = slot

    def __set__(self, instance: t.Any, value: AT) -> None:
        setattr(instance, self.slot, weakref(value))

    def __get__(self, instance: t.Any, __owner: t.Any = None) -> AT:
        return t.cast(AT, getattr(instance, self.slot)())


class Node:
    """A node in a circular doubly-linked list
    used to encode the order of items in an ordered bidict.

    A weak reference to the previous node is stored
    to avoid creating strong reference cycles.
    Referencing/dereferencing the weakref is handled automatically by :class:`WeakAttr`.
    """

    prv: WeakAttr[Node] = WeakAttr(slot='_prv_weak')
    __slots__ = ('__weakref__', '_prv_weak', 'nxt')

    nxt: Node | WeakAttr[Node]  # Allow subclasses to use a WeakAttr for nxt too (see SentinelNode)

    def __init__(self, prv: Node, nxt: Node) -> None:
        self.prv = prv
        self.nxt = nxt

    def unlink(self) -> None:
        """Remove self from in between prv and nxt.
        Self's references to prv and nxt are retained so it can be relinked (see below).
        """
        self.prv.nxt = self.nxt
        self.nxt.prv = self.prv

    def relink(self) -> None:
        """Restore self between prv and nxt after unlinking (see above)."""
        self.prv.nxt = self.nxt.prv = self


class SentinelNode(Node):
    """Special node in a circular doubly-linked list
    that links the first node with the last node.
    When its next and previous references point back to itself
    it represents an empty list.
    """

    nxt: WeakAttr[Node] = WeakAttr(slot='_nxt_weak')
    __slots__ = ('_nxt_weak',)

    def __init__(self) -> None:
        super().__init__(self, self)

    def iternodes(self, *, reverse: bool = False) -> t.Iterator[Node]:
        """Iterator yielding nodes in the requested order."""
        attr = 'prv' if reverse else 'nxt'
        node = getattr(self, attr)
        while node is not self:
            yield node
            node = getattr(node, attr)

    def new_last_node(self) -> Node:
        """Create and return a new terminal node."""
        old_last = self.prv
        new_last = Node(old_last, self)
        old_last.nxt = self.prv = new_last
        return new_last


class OrderedBidictBase(BidictBase[KT, VT]):
    """Base class implementing an ordered :class:`BidirectionalMapping`."""

    _node_by_korv: bidict[t.Any, Node]
    _bykey: bool

    def __init__(self, arg: MapOrItems[KT, VT] = (), /, **kw: VT) -> None:
        """Make a new ordered bidirectional mapping.
        The signature behaves like that of :class:`dict`.
        Items passed in are added in the order they are passed,
        respecting the :attr:`~bidict.BidictBase.on_dup`
        class attribute in the process.

        The order in which items are inserted is remembered,
        similar to :class:`collections.OrderedDict`.
        """
        self._sntl = SentinelNode()
        self._node_by_korv = bidict()
        self._bykey = True
        super().__init__(arg, **kw)

    if t.TYPE_CHECKING:

        @property
        def inverse(self) -> OrderedBidictBase[VT, KT]: ...

        @property
        def inv(self) -> OrderedBidictBase[VT, KT]: ...

    def _make_inverse(self) -> OrderedBidictBase[VT, KT]:
        inv = t.cast(OrderedBidictBase[VT, KT], super()._make_inverse())
        inv._sntl = self._sntl
        inv._node_by_korv = self._node_by_korv
        inv._bykey = not self._bykey
        return inv

    def _assoc_node(self, node: Node, key: KT, val: VT) -> None:
        korv = key if self._bykey else val
        self._node_by_korv.forceput(korv, node)

    def _dissoc_node(self, node: Node) -> None:
        del self._node_by_korv.inverse[node]
        node.unlink()

    def _init_from(self, other: MapOrItems[KT, VT]) -> None:
        """See :meth:`BidictBase._init_from`."""
        super()._init_from(other)
        bykey = self._bykey
        korv_by_node = self._node_by_korv.inverse
        korv_by_node.clear()
        korv_by_node_set = korv_by_node.__setitem__
        self._sntl.nxt = self._sntl.prv = self._sntl
        new_node = self._sntl.new_last_node
        for k, v in iteritems(other):
            korv_by_node_set(new_node(), k if bykey else v)

    def _write(self, newkey: KT, newval: VT, oldkey: OKT[KT], oldval: OVT[VT], unwrites: Unwrites | None) -> None:
        """See :meth:`bidict.BidictBase._spec_write`."""
        super()._write(newkey, newval, oldkey, oldval, unwrites)
        assoc, dissoc = self._assoc_node, self._dissoc_node
        node_by_korv, bykey = self._node_by_korv, self._bykey
        if oldval is MISSING and oldkey is MISSING:  # no key or value duplication
            # {0: 1, 2: 3} | {4: 5} => {0: 1, 2: 3, 4: 5}
            newnode = self._sntl.new_last_node()
            assoc(newnode, newkey, newval)
            if unwrites is not None:
                unwrites.append((dissoc, newnode))
        elif oldval is not MISSING and oldkey is not MISSING:  # key and value duplication across two different items
            # {0: 1, 2: 3} | {0: 3} => {0: 3}
            #    n1, n2             =>   n1   (collapse n1 and n2 into n1)
            # oldkey: 2, oldval: 1, oldnode: n2, newkey: 0, newval: 3, newnode: n1
            if bykey:
                oldnode = node_by_korv[oldkey]
                newnode = node_by_korv[newkey]
            else:
                oldnode = node_by_korv[newval]
                newnode = node_by_korv[oldval]
            dissoc(oldnode)
            assoc(newnode, newkey, newval)
            if unwrites is not None:
                unwrites.extend((
                    (assoc, newnode, newkey, oldval),
                    (assoc, oldnode, oldkey, newval),
                    (oldnode.relink,),
                ))
        elif oldval is not MISSING:  # just key duplication
            # {0: 1, 2: 3} | {2: 4} => {0: 1, 2: 4}
            # oldkey: MISSING, oldval: 3, newkey: 2, newval: 4
            node = node_by_korv[newkey if bykey else oldval]
            assoc(node, newkey, newval)
            if unwrites is not None:
                unwrites.append((assoc, node, newkey, oldval))
        else:
            assert oldkey is not MISSING  # just value duplication
            # {0: 1, 2: 3} | {4: 3} => {0: 1, 4: 3}
            # oldkey: 2, oldval: MISSING, newkey: 4, newval: 3
            node = node_by_korv[oldkey if bykey else newval]
            assoc(node, newkey, newval)
            if unwrites is not None:
                unwrites.append((assoc, node, oldkey, newval))

    def __iter__(self) -> t.Iterator[KT]:
        """Iterator over the contained keys in insertion order."""
        return self._iter(reverse=False)

    def __reversed__(self) -> t.Iterator[KT]:
        """Iterator over the contained keys in reverse insertion order."""
        return self._iter(reverse=True)

    def _iter(self, *, reverse: bool = False) -> t.Iterator[KT]:
        nodes = self._sntl.iternodes(reverse=reverse)
        korv_by_node = self._node_by_korv.inverse
        if self._bykey:
            for node in nodes:
                yield korv_by_node[node]
        else:
            key_by_val = self._invm
            for node in nodes:
                val = korv_by_node[node]
                yield key_by_val[val]


#                             * Code review nav *
# ============================================================================
# ← Prev: _bidict.py      Current: _orderedbase.py   Next: _orderedbidict.py →
# ============================================================================
