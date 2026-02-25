# Copyright 2009-2024 Joshua Bronson. All rights reserved.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.


#                             * Code review nav *
#                        (see comments in __init__.py)
# ============================================================================
# ← Prev: _abc.py              Current: _base.py            Next: _frozen.py →
# ============================================================================


"""Provide :class:`BidictBase`."""

from __future__ import annotations

import typing as t
import weakref
from itertools import starmap
from operator import eq
from types import MappingProxyType

from ._abc import BidirectionalMapping
from ._dup import DROP_NEW
from ._dup import DROP_OLD
from ._dup import ON_DUP_DEFAULT
from ._dup import RAISE
from ._dup import OnDup
from ._exc import DuplicationError
from ._exc import KeyAndValueDuplicationError
from ._exc import KeyDuplicationError
from ._exc import ValueDuplicationError
from ._iter import inverted
from ._iter import iteritems
from ._typing import KT
from ._typing import MISSING
from ._typing import OKT
from ._typing import OVT
from ._typing import VT
from ._typing import Maplike
from ._typing import MapOrItems


OldKV = t.Tuple[OKT[KT], OVT[VT]]
DedupResult = t.Optional[OldKV[KT, VT]]
Unwrites = t.List[t.Tuple[t.Any, ...]]
BT = t.TypeVar('BT', bound='BidictBase[t.Any, t.Any]')


class BidictKeysView(t.KeysView[KT], t.ValuesView[KT]):
    """Since the keys of a bidict are the values of its inverse (and vice versa),
    the :class:`~collections.abc.ValuesView` result of calling *bi.values()*
    is also a :class:`~collections.abc.KeysView` of *bi.inverse*.
    """


class BidictBase(BidirectionalMapping[KT, VT]):
    """Base class implementing :class:`BidirectionalMapping`."""

    #: The default :class:`~bidict.OnDup`
    #: that governs behavior when a provided item
    #: duplicates the key or value of other item(s).
    #:
    #: *See also*
    #: :ref:`basic-usage:Values Must Be Unique` (https://bidict.rtfd.io/basic-usage.html#values-must-be-unique),
    #: :doc:`extending` (https://bidict.rtfd.io/extending.html)
    on_dup = ON_DUP_DEFAULT

    _fwdm: t.MutableMapping[KT, VT]  #: the backing forward mapping (*key* → *val*)
    _invm: t.MutableMapping[VT, KT]  #: the backing inverse mapping (*val* → *key*)

    # Use Any rather than KT/VT in the following to avoid "ClassVar cannot contain type variables" errors:
    _fwdm_cls: t.ClassVar[type[t.MutableMapping[t.Any, t.Any]]] = dict  #: class of the backing forward mapping
    _invm_cls: t.ClassVar[type[t.MutableMapping[t.Any, t.Any]]] = dict  #: class of the backing inverse mapping

    #: The class of the inverse bidict instance.
    _inv_cls: t.ClassVar[type[BidictBase[t.Any, t.Any]]]

    def __init_subclass__(cls) -> None:
        super().__init_subclass__()
        cls._init_class()

    @classmethod
    def _init_class(cls) -> None:
        cls._ensure_inv_cls()
        cls._set_reversed()

    __reversed__: t.ClassVar[t.Any]

    @classmethod
    def _set_reversed(cls) -> None:
        """Set __reversed__ for subclasses that do not set it explicitly
        according to whether backing mappings are reversible.
        """
        if cls is not BidictBase:
            resolved = cls.__reversed__
            overridden = resolved is not BidictBase.__reversed__
            if overridden:  # E.g. OrderedBidictBase, OrderedBidict
                return
        backing_reversible = all(issubclass(i, t.Reversible) for i in (cls._fwdm_cls, cls._invm_cls))
        cls.__reversed__ = _fwdm_reversed if backing_reversible else None

    @classmethod
    def _ensure_inv_cls(cls) -> None:
        """Ensure :attr:`_inv_cls` is set, computing it dynamically if necessary.

        All subclasses provided in :mod:`bidict` are their own inverse classes,
        i.e., their backing forward and inverse mappings are both the same type,
        but users may define subclasses where this is not the case.
        This method ensures that the inverse class is computed correctly regardless.

        See: :ref:`extending:Dynamic Inverse Class Generation`
        (https://bidict.rtfd.io/extending.html#dynamic-inverse-class-generation)
        """
        # This _ensure_inv_cls() method is (indirectly) corecursive with _make_inv_cls() below
        # in the case that we need to dynamically generate the inverse class:
        #   1. _ensure_inv_cls() calls cls._make_inv_cls()
        #   2. cls._make_inv_cls() calls type(..., (cls, ...), ...) to dynamically generate inv_cls
        #   3. Our __init_subclass__ hook (see above) is automatically called on inv_cls
        #   4. inv_cls.__init_subclass__() calls inv_cls._ensure_inv_cls()
        #   5. inv_cls._ensure_inv_cls() resolves to this implementation
        #      (inv_cls deliberately does not override this), so we're back where we started.
        # But since the _make_inv_cls() call will have set inv_cls.__dict__._inv_cls,
        # just check if it's already set before calling _make_inv_cls() to prevent infinite recursion.
        if getattr(cls, '__dict__', {}).get('_inv_cls'):  # Don't assume cls.__dict__ (e.g. mypyc native class)
            return
        cls._inv_cls = cls._make_inv_cls()

    @classmethod
    def _make_inv_cls(cls: type[BT]) -> type[BT]:
        diff = cls._inv_cls_dict_diff()
        cls_is_own_inv = all(getattr(cls, k, MISSING) == v for (k, v) in diff.items())
        if cls_is_own_inv:
            return cls
        # Suppress auto-calculation of _inv_cls's _inv_cls since we know it already.
        # Works with the guard in BidictBase._ensure_inv_cls() to prevent infinite recursion.
        diff['_inv_cls'] = cls
        inv_cls = type(f'{cls.__name__}Inv', (cls, GeneratedBidictInverse), diff)
        inv_cls.__module__ = cls.__module__
        return t.cast(t.Type[BT], inv_cls)

    @classmethod
    def _inv_cls_dict_diff(cls) -> dict[str, t.Any]:
        return {
            '_fwdm_cls': cls._invm_cls,
            '_invm_cls': cls._fwdm_cls,
        }

    def __init__(self, arg: MapOrItems[KT, VT] = (), /, **kw: VT) -> None:
        """Make a new bidirectional mapping.
        The signature behaves like that of :class:`dict`.
        ktems passed via positional arg are processed first,
        followed by any items passed via keyword argument.
        Any duplication encountered along the way
        is handled as per :attr:`on_dup`.
        """
        self._fwdm = self._fwdm_cls()
        self._invm = self._invm_cls()
        self._update(arg, kw, rollback=False)

    # If Python ever adds support for higher-kinded types, `inverse` could use them, e.g.
    #     def inverse(self: BT[KT, VT]) -> BT[VT, KT]:
    # Ref: https://github.com/python/typing/issues/548#issuecomment-621571821
    @property
    def inverse(self) -> BidictBase[VT, KT]:
        """The inverse of this bidirectional mapping instance."""
        # When `bi.inverse` is called for the first time, this method
        # computes the inverse instance, stores it for subsequent use, and then
        # returns it. It also stores a reference on `bi.inverse` back to `bi`,
        # but uses a weakref to avoid creating a reference cycle. Strong references
        # to inverse instances are stored in ._inv, and weak references are stored
        # in ._invweak.

        # First check if a strong reference is already stored.
        inv: BidictBase[VT, KT] | None = getattr(self, '_inv', None)
        if inv is not None:
            return inv
        # Next check if a weak reference is already stored.
        invweak = getattr(self, '_invweak', None)
        if invweak is not None:
            inv = invweak()  # Try to resolve a strong reference and return it.
            if inv is not None:
                return inv
        # No luck. Compute the inverse reference and store it for subsequent use.
        inv = self._make_inverse()
        self._inv: BidictBase[VT, KT] | None = inv
        self._invweak: weakref.ReferenceType[BidictBase[VT, KT]] | None = None
        # Also store a weak reference back to `instance` on its inverse instance, so that
        # the second `.inverse` access in `bi.inverse.inverse` hits the cached weakref.
        inv._inv = None
        inv._invweak = weakref.ref(self)
        # In e.g. `bidict().inverse.inverse`, this design ensures that a strong reference
        # back to the original instance is retained before its refcount drops to zero,
        # avoiding an unintended potential deallocation.
        return inv

    def _make_inverse(self) -> BidictBase[VT, KT]:
        inv: BidictBase[VT, KT] = self._inv_cls()
        inv._fwdm = self._invm
        inv._invm = self._fwdm
        return inv

    @property
    def inv(self) -> BidictBase[VT, KT]:
        """Alias for :attr:`inverse`."""
        return self.inverse

    def __repr__(self) -> str:
        """See :func:`repr`."""
        clsname = self.__class__.__name__
        items = dict(self.items()) if self else ''
        return f'{clsname}({items})'

    def values(self) -> BidictKeysView[VT]:
        """A set-like object providing a view on the contained values.

        Since the values of a bidict are equivalent to the keys of its inverse,
        this method returns a set-like object for this bidict's values
        rather than just a collections.abc.ValuesView.
        This object supports set operations like union and difference,
        and constant- rather than linear-time containment checks,
        and is no more expensive to provide than the less capable
        collections.abc.ValuesView would be.

        See :meth:`keys` for more information.
        """
        return t.cast(BidictKeysView[VT], self.inverse.keys())

    def keys(self) -> t.KeysView[KT]:
        """A set-like object providing a view on the contained keys.

        When *b._fwdm* is a :class:`dict`, *b.keys()* returns a
        *dict_keys* object that behaves exactly the same as
        *collections.abc.KeysView(b)*, except for

          - offering better performance

          - being reversible on Python 3.8+

          - having a .mapping attribute in Python 3.10+
            that exposes a mappingproxy to *b._fwdm*.
        """
        fwdm, fwdm_cls = self._fwdm, self._fwdm_cls
        return fwdm.keys() if fwdm_cls is dict else BidictKeysView(self)

    def items(self) -> t.ItemsView[KT, VT]:
        """A set-like object providing a view on the contained items.

        When *b._fwdm* is a :class:`dict`, *b.items()* returns a
        *dict_items* object that behaves exactly the same as
        *collections.abc.ItemsView(b)*, except for:

          - offering better performance

          - being reversible on Python 3.8+

          - having a .mapping attribute in Python 3.10+
            that exposes a mappingproxy to *b._fwdm*.
        """
        return self._fwdm.items() if self._fwdm_cls is dict else super().items()

    # The inherited collections.abc.Mapping.__contains__() method is implemented by doing a `try`
    # `except KeyError` around `self[key]`. The following implementation is much faster,
    # especially in the missing case.
    def __contains__(self, key: t.Any) -> bool:
        """True if the mapping contains the specified key, else False."""
        return key in self._fwdm

    # The inherited collections.abc.Mapping.__eq__() method is implemented in terms of an inefficient
    # `dict(self.items()) == dict(other.items())` comparison, so override it with a
    # more efficient implementation.
    def __eq__(self, other: object) -> bool:
        """*x.__eq__(other)　⟺　x == other*

        Equivalent to *dict(x.items()) == dict(other.items())*
        but more efficient.

        Note that :meth:`bidict's __eq__() <bidict.BidictBase.__eq__>` implementation
        is inherited by subclasses,
        in particular by the ordered bidict subclasses,
        so even with ordered bidicts,
        :ref:`== comparison is order-insensitive <eq-order-insensitive>`
        (https://bidict.rtfd.io/other-bidict-types.html#eq-is-order-insensitive).

        *See also* :meth:`equals_order_sensitive`
        """
        if isinstance(other, t.Mapping):
            return self._fwdm.items() == other.items()
        # Ref: https://docs.python.org/3/library/constants.html#NotImplemented
        return NotImplemented

    def equals_order_sensitive(self, other: object) -> bool:
        """Order-sensitive equality check.

        *See also* :ref:`eq-order-insensitive`
        (https://bidict.rtfd.io/other-bidict-types.html#eq-is-order-insensitive)
        """
        if not isinstance(other, t.Mapping) or len(self) != len(other):
            return False
        return all(starmap(eq, zip(self.items(), other.items())))

    def _dedup(self, key: KT, val: VT, on_dup: OnDup) -> DedupResult[KT, VT]:
        """Check *key* and *val* for any duplication in self.

        Handle any duplication as per the passed in *on_dup*.

        If (key, val) is already present, return None
        since writing (key, val) would be a no-op.

        If duplication is found and the corresponding :class:`~bidict.OnDupAction` is
        :attr:`~bidict.DROP_NEW`, return None.

        If duplication is found and the corresponding :class:`~bidict.OnDupAction` is
        :attr:`~bidict.RAISE`, raise the appropriate exception.

        If duplication is found and the corresponding :class:`~bidict.OnDupAction` is
        :attr:`~bidict.DROP_OLD`, or if no duplication is found,
        return *(oldkey, oldval)*.
        """
        fwdm, invm = self._fwdm, self._invm
        oldval: OVT[VT] = fwdm.get(key, MISSING)
        oldkey: OKT[KT] = invm.get(val, MISSING)
        isdupkey, isdupval = oldval is not MISSING, oldkey is not MISSING
        if isdupkey and isdupval:
            if key == oldkey:
                assert val == oldval
                # (key, val) duplicates an existing item -> no-op.
                return None
            # key and val each duplicate a different existing item.
            if on_dup.val is RAISE:
                raise KeyAndValueDuplicationError(key, val)
            if on_dup.val is DROP_NEW:
                return None
            assert on_dup.val is DROP_OLD
            # Fall through to the return statement on the last line.
        elif isdupkey:
            if on_dup.key is RAISE:
                raise KeyDuplicationError(key)
            if on_dup.key is DROP_NEW:
                return None
            assert on_dup.key is DROP_OLD
            # Fall through to the return statement on the last line.
        elif isdupval:
            if on_dup.val is RAISE:
                raise ValueDuplicationError(val)
            if on_dup.val is DROP_NEW:
                return None
            assert on_dup.val is DROP_OLD
            # Fall through to the return statement on the last line.
        # else neither isdupkey nor isdupval.
        return oldkey, oldval

    def _write(self, newkey: KT, newval: VT, oldkey: OKT[KT], oldval: OVT[VT], unwrites: Unwrites | None) -> None:
        """Insert (newkey, newval), extending *unwrites* with associated inverse operations if provided.

        *oldkey* and *oldval* are as returned by :meth:`_dedup`.

        If *unwrites* is not None, it is extended with the inverse operations necessary to undo the write.
        This design allows :meth:`_update` to roll back a partially applied update that fails part-way through
        when necessary.

        This design also allows subclasses that require additional operations to easily extend this implementation.
        For example, :class:`bidict.OrderedBidictBase` calls this inherited implementation, and then extends *unwrites*
        with additional operations needed to keep its internal linked list nodes consistent with its items' order
        as changes are made.
        """
        fwdm, invm = self._fwdm, self._invm
        fwdm_set, invm_set = fwdm.__setitem__, invm.__setitem__
        fwdm_del, invm_del = fwdm.__delitem__, invm.__delitem__
        # Always perform the following writes regardless of duplication.
        fwdm_set(newkey, newval)
        invm_set(newval, newkey)
        if oldval is MISSING and oldkey is MISSING:  # no key or value duplication
            # {0: 1, 2: 3} | {4: 5} => {0: 1, 2: 3, 4: 5}
            if unwrites is not None:
                unwrites.extend((
                    (fwdm_del, newkey),
                    (invm_del, newval),
                ))
        elif oldval is not MISSING and oldkey is not MISSING:  # key and value duplication across two different items
            # {0: 1, 2: 3} | {0: 3} => {0: 3}
            fwdm_del(oldkey)
            invm_del(oldval)
            if unwrites is not None:
                unwrites.extend((
                    (fwdm_set, newkey, oldval),
                    (invm_set, oldval, newkey),
                    (fwdm_set, oldkey, newval),
                    (invm_set, newval, oldkey),
                ))
        elif oldval is not MISSING:  # just key duplication
            # {0: 1, 2: 3} | {2: 4} => {0: 1, 2: 4}
            invm_del(oldval)
            if unwrites is not None:
                unwrites.extend((
                    (fwdm_set, newkey, oldval),
                    (invm_set, oldval, newkey),
                    (invm_del, newval),
                ))
        else:
            assert oldkey is not MISSING  # just value duplication
            # {0: 1, 2: 3} | {4: 3} => {0: 1, 4: 3}
            fwdm_del(oldkey)
            if unwrites is not None:
                unwrites.extend((
                    (fwdm_set, oldkey, newval),
                    (invm_set, newval, oldkey),
                    (fwdm_del, newkey),
                ))

    def _update(
        self,
        arg: MapOrItems[KT, VT],
        kw: t.Mapping[str, VT] = MappingProxyType({}),
        *,
        rollback: bool | None = None,
        on_dup: OnDup | None = None,
    ) -> None:
        """Update with the items from *arg* and *kw*, maybe failing and rolling back as per *on_dup* and *rollback*."""
        # Note: We must process input in a single pass, since arg may be a generator.
        if not isinstance(arg, (t.Iterable, Maplike)):
            raise TypeError(f"'{arg.__class__.__name__}' object is not iterable")
        if not arg and not kw:
            return
        if on_dup is None:
            on_dup = self.on_dup
        if rollback is None:
            rollback = RAISE in on_dup

        # Fast path when we're empty and updating only from another bidict (i.e. no dup vals in new items).
        if not self and not kw and isinstance(arg, BidictBase):
            self._init_from(arg)
            return

        # Fast path when we're adding more items than we contain already and rollback is enabled:
        # Update a copy of self with rollback disabled. Fail if that fails, otherwise become the copy.
        if rollback and isinstance(arg, t.Sized) and len(arg) + len(kw) > len(self):
            tmp = self.copy()
            tmp._update(arg, kw, rollback=False, on_dup=on_dup)
            self._init_from(tmp)
            return

        # In all other cases, benchmarking has indicated that the update is best implemented as follows:
        # For each new item, perform a dup check (raising if necessary), and apply the associated writes we need to
        # perform on our backing _fwdm and _invm mappings. If rollback is enabled, also compute the associated unwrites
        # as we go. If the update results in a DuplicationError and rollback is enabled, apply the accumulated unwrites
        # before raising, to ensure that we fail clean.
        write = self._write
        unwrites: Unwrites | None = [] if rollback else None
        for key, val in iteritems(arg, **kw):
            try:
                dedup_result = self._dedup(key, val, on_dup)
            except DuplicationError:
                if unwrites is not None:
                    for fn, *args in reversed(unwrites):
                        fn(*args)
                raise
            if dedup_result is not None:
                write(key, val, *dedup_result, unwrites=unwrites)

    def __copy__(self: BT) -> BT:
        """Used for the copy protocol. See the :mod:`copy` module."""
        return self.copy()

    def copy(self: BT) -> BT:
        """Make a (shallow) copy of this bidict."""
        # Could just `return self.__class__(self)` here, but the below is faster. The former
        # would copy this bidict's items into a new instance one at a time (checking for duplication
        # for each item), whereas the below copies from the backing mappings all at once, and foregoes
        # item-by-item duplication checking since the backing mappings have been checked already.
        return self._from_other(self.__class__, self)

    @staticmethod
    def _from_other(bt: type[BT], other: MapOrItems[KT, VT], inv: bool = False) -> BT:
        """Fast, private constructor based on :meth:`_init_from`.

        If *inv* is true, return the inverse of the instance instead of the instance itself.
        (Useful for pickling with dynamically-generated inverse classes -- see :meth:`__reduce__`.)
        """
        inst = bt()
        inst._init_from(other)
        return t.cast(BT, inst.inverse) if inv else inst

    def _init_from(self, other: MapOrItems[KT, VT]) -> None:
        """Fast init from *other*, bypassing item-by-item duplication checking."""
        self._fwdm.clear()
        self._invm.clear()
        self._fwdm.update(other)
        # If other is a bidict, use its existing backing inverse mapping, otherwise
        # other could be a generator that's now exhausted, so invert self._fwdm on the fly.
        inv = other.inverse if isinstance(other, BidictBase) else inverted(self._fwdm)
        self._invm.update(inv)

    # other's type is Mapping rather than Maplike since bidict() | SupportsKeysAndGetItem({})
    # raises a TypeError, just like dict() | SupportsKeysAndGetItem({}) does.
    def __or__(self: BT, other: t.Mapping[KT, VT]) -> BT:
        """Return self|other."""
        if not isinstance(other, t.Mapping):
            return NotImplemented
        new = self.copy()
        new._update(other, rollback=False)
        return new

    def __ror__(self: BT, other: t.Mapping[KT, VT]) -> BT:
        """Return other|self."""
        if not isinstance(other, t.Mapping):
            return NotImplemented
        new = self.__class__(other)
        new._update(self, rollback=False)
        return new

    def __len__(self) -> int:
        """The number of contained items."""
        return len(self._fwdm)

    def __iter__(self) -> t.Iterator[KT]:
        """Iterator over the contained keys."""
        return iter(self._fwdm)

    def __getitem__(self, key: KT) -> VT:
        """*x.__getitem__(key) ⟺ x[key]*"""
        return self._fwdm[key]

    def __reduce__(self) -> tuple[t.Any, ...]:
        """Return state information for pickling."""
        cls = self.__class__
        inst: t.Mapping[t.Any, t.Any] = self
        # If this bidict's class is dynamically generated, pickle the inverse instead, whose (presumably not
        # dynamically generated) class the caller is more likely to have a reference to somewhere in sys.modules
        # that pickle can discover.
        if should_invert := isinstance(self, GeneratedBidictInverse):
            cls = self._inv_cls
            inst = self.inverse
        return self._from_other, (cls, dict(inst), should_invert)


# See BidictBase._set_reversed() above.
def _fwdm_reversed(self: BidictBase[KT, t.Any]) -> t.Iterator[KT]:
    """Iterator over the contained keys in reverse order."""
    assert isinstance(self._fwdm, t.Reversible)
    return reversed(self._fwdm)


BidictBase._init_class()


class GeneratedBidictInverse:
    """Base class for dynamically-generated inverse bidict classes."""


#                             * Code review nav *
# ============================================================================
# ← Prev: _abc.py              Current: _base.py            Next: _frozen.py →
# ============================================================================
