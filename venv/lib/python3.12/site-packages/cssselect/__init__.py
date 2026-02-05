"""
CSS Selectors based on XPath
============================

This module supports selecting XML/HTML elements based on CSS selectors.
See the `CSSSelector` class for details.


:copyright: (c) 2007-2012 Ian Bicking and contributors.
See AUTHORS for more details.
:license: BSD, see LICENSE for more details.

"""

from cssselect.parser import (
    FunctionalPseudoElement,
    Selector,
    SelectorError,
    SelectorSyntaxError,
    parse,
)
from cssselect.xpath import ExpressionError, GenericTranslator, HTMLTranslator

__all__ = (
    "ExpressionError",
    "FunctionalPseudoElement",
    "GenericTranslator",
    "HTMLTranslator",
    "Selector",
    "SelectorError",
    "SelectorSyntaxError",
    "parse",
)

VERSION = "1.4.0"
__version__ = VERSION
