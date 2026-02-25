# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from ...._models import BaseModel

__all__ = ["ChatSessionAutomaticThreadTitling"]


class ChatSessionAutomaticThreadTitling(BaseModel):
    """Automatic thread title preferences for the session."""

    enabled: bool
    """Whether automatic thread titling is enabled."""
