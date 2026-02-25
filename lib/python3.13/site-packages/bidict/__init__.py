# Copyright 2009-2024 Joshua Bronson. All rights reserved.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.


# ============================================================================
#                    * Welcome to the bidict source code *
# ============================================================================

# Reading through the code? You'll find a "Code review nav" comment like the one
# below at the top and bottom of the key source files. Follow these cues to take
# a path through the code that's optimized for familiarizing yourself with it.
#
# If you're not reading this on https://github.com/jab/bidict already, go there
# to ensure you have the latest version of the code. While there, you can also
# star the project, watch it for updates, fork the code, and submit an issue or
# pull request with any proposed changes. More information can be found linked
# from README.rst, which is also shown on https://github.com/jab/bidict.

#                             * Code review nav *
# ============================================================================
#                             Current: __init__.py             Next: _abc.py →
# ============================================================================


"""The bidirectional mapping library for Python.

----

bidict by example:

.. code-block:: python

   >>> from bidict import bidict
   >>> element_by_symbol = bidict({'H': 'hydrogen'})
   >>> element_by_symbol['H']
   'hydrogen'
   >>> element_by_symbol.inverse['hydrogen']
   'H'


Please see https://github.com/jab/bidict for the most up-to-date code and
https://bidict.readthedocs.io for the most up-to-date documentation
if you are reading this elsewhere.

----

.. :copyright: (c) 2009-2024 Joshua Bronson.
.. :license: MPLv2. See LICENSE for details.
"""

# Use private aliases to not re-export these publicly (for Sphinx automodule with imported-members).
from __future__ import annotations as _annotations

from contextlib import suppress as _suppress

from ._abc import BidirectionalMapping as BidirectionalMapping
from ._abc import MutableBidirectionalMapping as MutableBidirectionalMapping
from ._base import BidictBase as BidictBase
from ._base import BidictKeysView as BidictKeysView
from ._base import GeneratedBidictInverse as GeneratedBidictInverse
from ._bidict import MutableBidict as MutableBidict
from ._bidict import bidict as bidict
from ._dup import DROP_NEW as DROP_NEW
from ._dup import DROP_OLD as DROP_OLD
from ._dup import ON_DUP_DEFAULT as ON_DUP_DEFAULT
from ._dup import ON_DUP_DROP_OLD as ON_DUP_DROP_OLD
from ._dup import ON_DUP_RAISE as ON_DUP_RAISE
from ._dup import RAISE as RAISE
from ._dup import OnDup as OnDup
from ._dup import OnDupAction as OnDupAction
from ._exc import BidictException as BidictException
from ._exc import DuplicationError as DuplicationError
from ._exc import KeyAndValueDuplicationError as KeyAndValueDuplicationError
from ._exc import KeyDuplicationError as KeyDuplicationError
from ._exc import ValueDuplicationError as ValueDuplicationError
from ._frozen import frozenbidict as frozenbidict
from ._iter import inverted as inverted
from ._orderedbase import OrderedBidictBase as OrderedBidictBase
from ._orderedbidict import OrderedBidict as OrderedBidict
from .metadata import __author__ as __author__
from .metadata import __copyright__ as __copyright__
from .metadata import __description__ as __description__
from .metadata import __license__ as __license__
from .metadata import __url__ as __url__
from .metadata import __version__ as __version__


# Set __module__ of re-exported classes to the 'bidict' top-level module, so that e.g.
# 'bidict.bidict' shows up as 'bidict.bidict` rather than 'bidict._bidict.bidict'.
for _obj in tuple(locals().values()):  # pragma: no cover
    if not getattr(_obj, '__module__', '').startswith('bidict.'):
        continue
    with _suppress(AttributeError):
        _obj.__module__ = 'bidict'


#                             * Code review nav *
# ============================================================================
#                             Current: __init__.py             Next: _abc.py →
# ============================================================================
