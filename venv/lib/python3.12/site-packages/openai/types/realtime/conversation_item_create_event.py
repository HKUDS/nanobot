# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from typing import Optional
from typing_extensions import Literal

from ..._models import BaseModel
from .conversation_item import ConversationItem

__all__ = ["ConversationItemCreateEvent"]


class ConversationItemCreateEvent(BaseModel):
    """
    Add a new Item to the Conversation's context, including messages, function
    calls, and function call responses. This event can be used both to populate a
    "history" of the conversation and to add new items mid-stream, but has the
    current limitation that it cannot populate assistant audio messages.

    If successful, the server will respond with a `conversation.item.created`
    event, otherwise an `error` event will be sent.
    """

    item: ConversationItem
    """A single item within a Realtime conversation."""

    type: Literal["conversation.item.create"]
    """The event type, must be `conversation.item.create`."""

    event_id: Optional[str] = None
    """Optional client-generated ID used to identify this event."""

    previous_item_id: Optional[str] = None
    """The ID of the preceding item after which the new item will be inserted.

    If not set, the new item will be appended to the end of the conversation.

    If set to `root`, the new item will be added to the beginning of the
    conversation.

    If set to an existing ID, it allows an item to be inserted mid-conversation. If
    the ID cannot be found, an error will be returned and the item will not be
    added.
    """
