# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from __future__ import annotations

from typing_extensions import Literal, Required, TypedDict

__all__ = ["ChatCompletionContentPartTextParam"]


class ChatCompletionContentPartTextParam(TypedDict, total=False):
    """
    Learn about [text inputs](https://platform.openai.com/docs/guides/text-generation).
    """

    text: Required[str]
    """The text content."""

    type: Required[Literal["text"]]
    """The type of the content part."""
