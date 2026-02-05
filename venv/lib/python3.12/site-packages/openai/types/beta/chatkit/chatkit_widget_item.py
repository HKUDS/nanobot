# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from typing_extensions import Literal

from ...._models import BaseModel

__all__ = ["ChatKitWidgetItem"]


class ChatKitWidgetItem(BaseModel):
    """Thread item that renders a widget payload."""

    id: str
    """Identifier of the thread item."""

    created_at: int
    """Unix timestamp (in seconds) for when the item was created."""

    object: Literal["chatkit.thread_item"]
    """Type discriminator that is always `chatkit.thread_item`."""

    thread_id: str
    """Identifier of the parent thread."""

    type: Literal["chatkit.widget"]
    """Type discriminator that is always `chatkit.widget`."""

    widget: str
    """Serialized widget payload rendered in the UI."""
