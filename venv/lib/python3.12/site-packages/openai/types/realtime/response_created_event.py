# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from typing_extensions import Literal

from ..._models import BaseModel
from .realtime_response import RealtimeResponse

__all__ = ["ResponseCreatedEvent"]


class ResponseCreatedEvent(BaseModel):
    """Returned when a new Response is created.

    The first event of response creation,
    where the response is in an initial state of `in_progress`.
    """

    event_id: str
    """The unique ID of the server event."""

    response: RealtimeResponse
    """The response resource."""

    type: Literal["response.created"]
    """The event type, must be `response.created`."""
