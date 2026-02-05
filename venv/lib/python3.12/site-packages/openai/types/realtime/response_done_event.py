# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from typing_extensions import Literal

from ..._models import BaseModel
from .realtime_response import RealtimeResponse

__all__ = ["ResponseDoneEvent"]


class ResponseDoneEvent(BaseModel):
    """Returned when a Response is done streaming.

    Always emitted, no matter the
    final state. The Response object included in the `response.done` event will
    include all output Items in the Response but will omit the raw audio data.

    Clients should check the `status` field of the Response to determine if it was successful
    (`completed`) or if there was another outcome: `cancelled`, `failed`, or `incomplete`.

    A response will contain all output items that were generated during the response, excluding
    any audio content.
    """

    event_id: str
    """The unique ID of the server event."""

    response: RealtimeResponse
    """The response resource."""

    type: Literal["response.done"]
    """The event type, must be `response.done`."""
