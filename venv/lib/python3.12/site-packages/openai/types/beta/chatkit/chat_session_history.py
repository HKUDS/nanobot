# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from typing import Optional

from ...._models import BaseModel

__all__ = ["ChatSessionHistory"]


class ChatSessionHistory(BaseModel):
    """History retention preferences returned for the session."""

    enabled: bool
    """Indicates if chat history is persisted for the session."""

    recent_threads: Optional[int] = None
    """Number of prior threads surfaced in history views.

    Defaults to null when all history is retained.
    """
