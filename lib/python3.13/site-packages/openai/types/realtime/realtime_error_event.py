# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from typing_extensions import Literal

from ..._models import BaseModel
from .realtime_error import RealtimeError

__all__ = ["RealtimeErrorEvent"]


class RealtimeErrorEvent(BaseModel):
    """
    Returned when an error occurs, which could be a client problem or a server
    problem. Most errors are recoverable and the session will stay open, we
    recommend to implementors to monitor and log error messages by default.
    """

    error: RealtimeError
    """Details of the error."""

    event_id: str
    """The unique ID of the server event."""

    type: Literal["error"]
    """The event type, must be `error`."""
