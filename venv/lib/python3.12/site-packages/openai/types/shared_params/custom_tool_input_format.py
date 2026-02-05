# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from __future__ import annotations

from typing import Union
from typing_extensions import Literal, Required, TypeAlias, TypedDict

__all__ = ["CustomToolInputFormat", "Text", "Grammar"]


class Text(TypedDict, total=False):
    """Unconstrained free-form text."""

    type: Required[Literal["text"]]
    """Unconstrained text format. Always `text`."""


class Grammar(TypedDict, total=False):
    """A grammar defined by the user."""

    definition: Required[str]
    """The grammar definition."""

    syntax: Required[Literal["lark", "regex"]]
    """The syntax of the grammar definition. One of `lark` or `regex`."""

    type: Required[Literal["grammar"]]
    """Grammar format. Always `grammar`."""


CustomToolInputFormat: TypeAlias = Union[Text, Grammar]
