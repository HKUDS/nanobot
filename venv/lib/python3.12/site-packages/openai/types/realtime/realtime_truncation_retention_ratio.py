# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from typing import Optional
from typing_extensions import Literal

from ..._models import BaseModel

__all__ = ["RealtimeTruncationRetentionRatio", "TokenLimits"]


class TokenLimits(BaseModel):
    """Optional custom token limits for this truncation strategy.

    If not provided, the model's default token limits will be used.
    """

    post_instructions: Optional[int] = None
    """
    Maximum tokens allowed in the conversation after instructions (which including
    tool definitions). For example, setting this to 5,000 would mean that truncation
    would occur when the conversation exceeds 5,000 tokens after instructions. This
    cannot be higher than the model's context window size minus the maximum output
    tokens.
    """


class RealtimeTruncationRetentionRatio(BaseModel):
    """
    Retain a fraction of the conversation tokens when the conversation exceeds the input token limit. This allows you to amortize truncations across multiple turns, which can help improve cached token usage.
    """

    retention_ratio: float
    """
    Fraction of post-instruction conversation tokens to retain (`0.0` - `1.0`) when
    the conversation exceeds the input token limit. Setting this to `0.8` means that
    messages will be dropped until 80% of the maximum allowed tokens are used. This
    helps reduce the frequency of truncations and improve cache rates.
    """

    type: Literal["retention_ratio"]
    """Use retention ratio truncation."""

    token_limits: Optional[TokenLimits] = None
    """Optional custom token limits for this truncation strategy.

    If not provided, the model's default token limits will be used.
    """
