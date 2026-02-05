# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from typing import Optional
from typing_extensions import Literal

from ..._models import BaseModel
from .conversation_item import ConversationItem

__all__ = ["ConversationItemCreatedEvent"]


class ConversationItemCreatedEvent(BaseModel):
    """Returned when a conversation item is created.

    There are several scenarios that produce this event:
      - The server is generating a Response, which if successful will produce
        either one or two Items, which will be of type `message`
        (role `assistant`) or type `function_call`.
      - The input audio buffer has been committed, either by the client or the
        server (in `server_vad` mode). The server will take the content of the
        input audio buffer and add it to a new user message Item.
      - The client has sent a `conversation.item.create` event to add a new Item
        to the Conversation.
    """

    event_id: str
    """The unique ID of the server event."""

    item: ConversationItem
    """A single item within a Realtime conversation."""

    type: Literal["conversation.item.created"]
    """The event type, must be `conversation.item.created`."""

    previous_item_id: Optional[str] = None
    """
    The ID of the preceding item in the Conversation context, allows the client to
    understand the order of the conversation. Can be `null` if the item has no
    predecessor.
    """
