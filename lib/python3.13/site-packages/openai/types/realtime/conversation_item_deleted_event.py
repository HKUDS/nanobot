# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from typing_extensions import Literal

from ..._models import BaseModel

__all__ = ["ConversationItemDeletedEvent"]


class ConversationItemDeletedEvent(BaseModel):
    """
    Returned when an item in the conversation is deleted by the client with a
    `conversation.item.delete` event. This event is used to synchronize the
    server's understanding of the conversation history with the client's view.
    """

    event_id: str
    """The unique ID of the server event."""

    item_id: str
    """The ID of the item that was deleted."""

    type: Literal["conversation.item.deleted"]
    """The event type, must be `conversation.item.deleted`."""
