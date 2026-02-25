# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from typing import Optional
from typing_extensions import Literal

from ..._models import BaseModel
from .conversation_item import ConversationItem

__all__ = ["ConversationItemDone"]


class ConversationItemDone(BaseModel):
    """Returned when a conversation item is finalized.

    The event will include the full content of the Item except for audio data, which can be retrieved separately with a `conversation.item.retrieve` event if needed.
    """

    event_id: str
    """The unique ID of the server event."""

    item: ConversationItem
    """A single item within a Realtime conversation."""

    type: Literal["conversation.item.done"]
    """The event type, must be `conversation.item.done`."""

    previous_item_id: Optional[str] = None
    """The ID of the item that precedes this one, if any.

    This is used to maintain ordering when items are inserted.
    """
