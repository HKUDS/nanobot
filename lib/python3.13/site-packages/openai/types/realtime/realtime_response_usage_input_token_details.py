# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from typing import Optional

from ..._models import BaseModel

__all__ = ["RealtimeResponseUsageInputTokenDetails", "CachedTokensDetails"]


class CachedTokensDetails(BaseModel):
    """Details about the cached tokens used as input for the Response."""

    audio_tokens: Optional[int] = None
    """The number of cached audio tokens used as input for the Response."""

    image_tokens: Optional[int] = None
    """The number of cached image tokens used as input for the Response."""

    text_tokens: Optional[int] = None
    """The number of cached text tokens used as input for the Response."""


class RealtimeResponseUsageInputTokenDetails(BaseModel):
    """Details about the input tokens used in the Response.

    Cached tokens are tokens from previous turns in the conversation that are included as context for the current response. Cached tokens here are counted as a subset of input tokens, meaning input tokens will include cached and uncached tokens.
    """

    audio_tokens: Optional[int] = None
    """The number of audio tokens used as input for the Response."""

    cached_tokens: Optional[int] = None
    """The number of cached tokens used as input for the Response."""

    cached_tokens_details: Optional[CachedTokensDetails] = None
    """Details about the cached tokens used as input for the Response."""

    image_tokens: Optional[int] = None
    """The number of image tokens used as input for the Response."""

    text_tokens: Optional[int] = None
    """The number of text tokens used as input for the Response."""
