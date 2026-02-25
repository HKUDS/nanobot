# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from typing import Optional

from ..._models import BaseModel

__all__ = ["RealtimeResponseUsageOutputTokenDetails"]


class RealtimeResponseUsageOutputTokenDetails(BaseModel):
    """Details about the output tokens used in the Response."""

    audio_tokens: Optional[int] = None
    """The number of audio tokens used in the Response."""

    text_tokens: Optional[int] = None
    """The number of text tokens used in the Response."""
