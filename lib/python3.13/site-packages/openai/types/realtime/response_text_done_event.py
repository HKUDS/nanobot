# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from typing_extensions import Literal

from ..._models import BaseModel

__all__ = ["ResponseTextDoneEvent"]


class ResponseTextDoneEvent(BaseModel):
    """Returned when the text value of an "output_text" content part is done streaming.

    Also
    emitted when a Response is interrupted, incomplete, or cancelled.
    """

    content_index: int
    """The index of the content part in the item's content array."""

    event_id: str
    """The unique ID of the server event."""

    item_id: str
    """The ID of the item."""

    output_index: int
    """The index of the output item in the response."""

    response_id: str
    """The ID of the response."""

    text: str
    """The final text content."""

    type: Literal["response.output_text.done"]
    """The event type, must be `response.output_text.done`."""
