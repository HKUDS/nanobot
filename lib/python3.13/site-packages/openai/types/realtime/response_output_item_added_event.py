# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from typing_extensions import Literal

from ..._models import BaseModel
from .conversation_item import ConversationItem

__all__ = ["ResponseOutputItemAddedEvent"]


class ResponseOutputItemAddedEvent(BaseModel):
    """Returned when a new Item is created during Response generation."""

    event_id: str
    """The unique ID of the server event."""

    item: ConversationItem
    """A single item within a Realtime conversation."""

    output_index: int
    """The index of the output item in the Response."""

    response_id: str
    """The ID of the Response to which the item belongs."""

    type: Literal["response.output_item.added"]
    """The event type, must be `response.output_item.added`."""
