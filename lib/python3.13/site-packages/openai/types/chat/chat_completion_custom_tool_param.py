# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from __future__ import annotations

from typing import Union
from typing_extensions import Literal, Required, TypeAlias, TypedDict

__all__ = [
    "ChatCompletionCustomToolParam",
    "Custom",
    "CustomFormat",
    "CustomFormatText",
    "CustomFormatGrammar",
    "CustomFormatGrammarGrammar",
]


class CustomFormatText(TypedDict, total=False):
    """Unconstrained free-form text."""

    type: Required[Literal["text"]]
    """Unconstrained text format. Always `text`."""


class CustomFormatGrammarGrammar(TypedDict, total=False):
    """Your chosen grammar."""

    definition: Required[str]
    """The grammar definition."""

    syntax: Required[Literal["lark", "regex"]]
    """The syntax of the grammar definition. One of `lark` or `regex`."""


class CustomFormatGrammar(TypedDict, total=False):
    """A grammar defined by the user."""

    grammar: Required[CustomFormatGrammarGrammar]
    """Your chosen grammar."""

    type: Required[Literal["grammar"]]
    """Grammar format. Always `grammar`."""


CustomFormat: TypeAlias = Union[CustomFormatText, CustomFormatGrammar]


class Custom(TypedDict, total=False):
    """Properties of the custom tool."""

    name: Required[str]
    """The name of the custom tool, used to identify it in tool calls."""

    description: str
    """Optional description of the custom tool, used to provide more context."""

    format: CustomFormat
    """The input format for the custom tool. Default is unconstrained text."""


class ChatCompletionCustomToolParam(TypedDict, total=False):
    """A custom tool that processes input using a specified format."""

    custom: Required[Custom]
    """Properties of the custom tool."""

    type: Required[Literal["custom"]]
    """The type of the custom tool. Always `custom`."""
