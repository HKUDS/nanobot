# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from __future__ import annotations

from typing_extensions import Literal, Required, TypedDict

__all__ = ["ConversationItemRetrieveEventParam"]


class ConversationItemRetrieveEventParam(TypedDict, total=False):
    """
    Send this event when you want to retrieve the server's representation of a specific item in the conversation history. This is useful, for example, to inspect user audio after noise cancellation and VAD.
    The server will respond with a `conversation.item.retrieved` event,
    unless the item does not exist in the conversation history, in which case the
    server will respond with an error.
    """

    item_id: Required[str]
    """The ID of the item to retrieve."""

    type: Required[Literal["conversation.item.retrieve"]]
    """The event type, must be `conversation.item.retrieve`."""

    event_id: str
    """Optional client-generated ID used to identify this event."""
