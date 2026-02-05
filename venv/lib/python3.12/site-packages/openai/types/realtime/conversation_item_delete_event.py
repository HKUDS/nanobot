# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from typing import Optional
from typing_extensions import Literal

from ..._models import BaseModel

__all__ = ["ConversationItemDeleteEvent"]


class ConversationItemDeleteEvent(BaseModel):
    """Send this event when you want to remove any item from the conversation
    history.

    The server will respond with a `conversation.item.deleted` event,
    unless the item does not exist in the conversation history, in which case the
    server will respond with an error.
    """

    item_id: str
    """The ID of the item to delete."""

    type: Literal["conversation.item.delete"]
    """The event type, must be `conversation.item.delete`."""

    event_id: Optional[str] = None
    """Optional client-generated ID used to identify this event."""
