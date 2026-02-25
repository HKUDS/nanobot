# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from __future__ import annotations

from typing_extensions import Literal, Required, TypedDict

__all__ = ["ConversationItemDeleteEventParam"]


class ConversationItemDeleteEventParam(TypedDict, total=False):
    """Send this event when you want to remove any item from the conversation
    history.

    The server will respond with a `conversation.item.deleted` event,
    unless the item does not exist in the conversation history, in which case the
    server will respond with an error.
    """

    item_id: Required[str]
    """The ID of the item to delete."""

    type: Required[Literal["conversation.item.delete"]]
    """The event type, must be `conversation.item.delete`."""

    event_id: str
    """Optional client-generated ID used to identify this event."""
