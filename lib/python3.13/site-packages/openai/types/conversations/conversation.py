# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from typing_extensions import Literal

from ..._models import BaseModel

__all__ = ["Conversation"]


class Conversation(BaseModel):
    id: str
    """The unique ID of the conversation."""

    created_at: int
    """
    The time at which the conversation was created, measured in seconds since the
    Unix epoch.
    """

    metadata: object
    """Set of 16 key-value pairs that can be attached to an object.

    This can be useful for storing additional information about the object in a
    structured format, and querying for objects via API or the dashboard. Keys are
    strings with a maximum length of 64 characters. Values are strings with a
    maximum length of 512 characters.
    """

    object: Literal["conversation"]
    """The object type, which is always `conversation`."""
