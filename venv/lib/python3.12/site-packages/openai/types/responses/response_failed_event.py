# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from typing_extensions import Literal

from .response import Response
from ..._models import BaseModel

__all__ = ["ResponseFailedEvent"]


class ResponseFailedEvent(BaseModel):
    """An event that is emitted when a response fails."""

    response: Response
    """The response that failed."""

    sequence_number: int
    """The sequence number of this event."""

    type: Literal["response.failed"]
    """The type of the event. Always `response.failed`."""
