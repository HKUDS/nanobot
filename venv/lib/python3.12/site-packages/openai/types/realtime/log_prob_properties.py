# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from typing import List

from ..._models import BaseModel

__all__ = ["LogProbProperties"]


class LogProbProperties(BaseModel):
    """A log probability object."""

    token: str
    """The token that was used to generate the log probability."""

    bytes: List[int]
    """The bytes that were used to generate the log probability."""

    logprob: float
    """The log probability of the token."""
