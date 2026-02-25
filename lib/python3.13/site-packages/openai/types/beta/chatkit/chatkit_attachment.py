# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from typing import Optional
from typing_extensions import Literal

from ...._models import BaseModel

__all__ = ["ChatKitAttachment"]


class ChatKitAttachment(BaseModel):
    """Attachment metadata included on thread items."""

    id: str
    """Identifier for the attachment."""

    mime_type: str
    """MIME type of the attachment."""

    name: str
    """Original display name for the attachment."""

    preview_url: Optional[str] = None
    """Preview URL for rendering the attachment inline."""

    type: Literal["image", "file"]
    """Attachment discriminator."""
