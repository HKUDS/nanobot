# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from ...._models import BaseModel
from .chat_session_history import ChatSessionHistory
from .chat_session_file_upload import ChatSessionFileUpload
from .chat_session_automatic_thread_titling import ChatSessionAutomaticThreadTitling

__all__ = ["ChatSessionChatKitConfiguration"]


class ChatSessionChatKitConfiguration(BaseModel):
    """ChatKit configuration for the session."""

    automatic_thread_titling: ChatSessionAutomaticThreadTitling
    """Automatic thread titling preferences."""

    file_upload: ChatSessionFileUpload
    """Upload settings for the session."""

    history: ChatSessionHistory
    """History retention configuration."""
