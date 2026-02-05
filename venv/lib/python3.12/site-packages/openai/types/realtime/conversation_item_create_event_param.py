# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from __future__ import annotations

from typing_extensions import Literal, Required, TypedDict

from .conversation_item_param import ConversationItemParam

__all__ = ["ConversationItemCreateEventParam"]


class ConversationItemCreateEventParam(TypedDict, total=False):
    """
    Add a new Item to the Conversation's context, including messages, function
    calls, and function call responses. This event can be used both to populate a
    "history" of the conversation and to add new items mid-stream, but has the
    current limitation that it cannot populate assistant audio messages.

    If successful, the server will respond with a `conversation.item.created`
    event, otherwise an `error` event will be sent.
    """

    item: Required[ConversationItemParam]
    """A single item within a Realtime conversation."""

    type: Required[Literal["conversation.item.create"]]
    """The event type, must be `conversation.item.create`."""

    event_id: str
    """Optional client-generated ID used to identify this event."""

    previous_item_id: str
    """The ID of the preceding item after which the new item will be inserted.

    If not set, the new item will be appended to the end of the conversation.

    If set to `root`, the new item will be added to the beginning of the
    conversation.

    If set to an existing ID, it allows an item to be inserted mid-conversation. If
    the ID cannot be found, an error will be returned and the item will not be
    added.
    """
