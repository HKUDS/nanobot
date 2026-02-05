# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from __future__ import annotations

from typing_extensions import Literal, Required, TypedDict

__all__ = ["ResponseCancelEventParam"]


class ResponseCancelEventParam(TypedDict, total=False):
    """Send this event to cancel an in-progress response.

    The server will respond
    with a `response.done` event with a status of `response.status=cancelled`. If
    there is no response to cancel, the server will respond with an error. It's safe
    to call `response.cancel` even if no response is in progress, an error will be
    returned the session will remain unaffected.
    """

    type: Required[Literal["response.cancel"]]
    """The event type, must be `response.cancel`."""

    event_id: str
    """Optional client-generated ID used to identify this event."""

    response_id: str
    """
    A specific response ID to cancel - if not provided, will cancel an in-progress
    response in the default conversation.
    """
