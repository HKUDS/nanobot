# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from typing_extensions import Literal

from ...._models import BaseModel

__all__ = ["ThreadDeleteResponse"]


class ThreadDeleteResponse(BaseModel):
    """Confirmation payload returned after deleting a thread."""

    id: str
    """Identifier of the deleted thread."""

    deleted: bool
    """Indicates that the thread has been deleted."""

    object: Literal["chatkit.thread.deleted"]
    """Type discriminator that is always `chatkit.thread.deleted`."""
