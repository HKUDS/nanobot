# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from typing import Optional
from typing_extensions import Literal

from ..._models import BaseModel
from .conversation_item import ConversationItem

__all__ = ["ConversationItemAdded"]


class ConversationItemAdded(BaseModel):
    """Sent by the server when an Item is added to the default Conversation.

    This can happen in several cases:
    - When the client sends a `conversation.item.create` event.
    - When the input audio buffer is committed. In this case the item will be a user message containing the audio from the buffer.
    - When the model is generating a Response. In this case the `conversation.item.added` event will be sent when the model starts generating a specific Item, and thus it will not yet have any content (and `status` will be `in_progress`).

    The event will include the full content of the Item (except when model is generating a Response) except for audio data, which can be retrieved separately with a `conversation.item.retrieve` event if necessary.
    """

    event_id: str
    """The unique ID of the server event."""

    item: ConversationItem
    """A single item within a Realtime conversation."""

    type: Literal["conversation.item.added"]
    """The event type, must be `conversation.item.added`."""

    previous_item_id: Optional[str] = None
    """The ID of the item that precedes this one, if any.

    This is used to maintain ordering when items are inserted.
    """
