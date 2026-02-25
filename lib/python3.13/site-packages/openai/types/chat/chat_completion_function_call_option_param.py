# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from __future__ import annotations

from typing_extensions import Required, TypedDict

__all__ = ["ChatCompletionFunctionCallOptionParam"]


class ChatCompletionFunctionCallOptionParam(TypedDict, total=False):
    """
    Specifying a particular function via `{"name": "my_function"}` forces the model to call that function.
    """

    name: Required[str]
    """The name of the function to call."""
