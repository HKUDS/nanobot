# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from typing import List
from typing_extensions import Literal

from ...._models import BaseModel
from .chatkit_response_output_text import ChatKitResponseOutputText

__all__ = ["ChatKitThreadAssistantMessageItem"]


class ChatKitThreadAssistantMessageItem(BaseModel):
    """Assistant-authored message within a thread."""

    id: str
    """Identifier of the thread item."""

    content: List[ChatKitResponseOutputText]
    """Ordered assistant response segments."""

    created_at: int
    """Unix timestamp (in seconds) for when the item was created."""

    object: Literal["chatkit.thread_item"]
    """Type discriminator that is always `chatkit.thread_item`."""

    thread_id: str
    """Identifier of the parent thread."""

    type: Literal["chatkit.assistant_message"]
    """Type discriminator that is always `chatkit.assistant_message`."""
