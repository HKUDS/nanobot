# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from __future__ import annotations

from typing_extensions import Required, TypedDict

__all__ = ["VideoRemixParams"]


class VideoRemixParams(TypedDict, total=False):
    prompt: Required[str]
    """Updated text prompt that directs the remix generation."""
