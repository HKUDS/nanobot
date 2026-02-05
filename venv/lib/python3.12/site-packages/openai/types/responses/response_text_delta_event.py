# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from typing import List, Optional
from typing_extensions import Literal

from ..._models import BaseModel

__all__ = ["ResponseTextDeltaEvent", "Logprob", "LogprobTopLogprob"]


class LogprobTopLogprob(BaseModel):
    token: Optional[str] = None
    """A possible text token."""

    logprob: Optional[float] = None
    """The log probability of this token."""


class Logprob(BaseModel):
    """
    A logprob is the logarithmic probability that the model assigns to producing
    a particular token at a given position in the sequence. Less-negative (higher)
    logprob values indicate greater model confidence in that token choice.
    """

    token: str
    """A possible text token."""

    logprob: float
    """The log probability of this token."""

    top_logprobs: Optional[List[LogprobTopLogprob]] = None
    """The log probability of the top 20 most likely tokens."""


class ResponseTextDeltaEvent(BaseModel):
    """Emitted when there is an additional text delta."""

    content_index: int
    """The index of the content part that the text delta was added to."""

    delta: str
    """The text delta that was added."""

    item_id: str
    """The ID of the output item that the text delta was added to."""

    logprobs: List[Logprob]
    """The log probabilities of the tokens in the delta."""

    output_index: int
    """The index of the output item that the text delta was added to."""

    sequence_number: int
    """The sequence number for this event."""

    type: Literal["response.output_text.delta"]
    """The type of the event. Always `response.output_text.delta`."""
