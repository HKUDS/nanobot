# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from typing_extensions import Literal

from ...._models import BaseModel
from ..chatkit_workflow import ChatKitWorkflow
from .chat_session_status import ChatSessionStatus
from .chat_session_rate_limits import ChatSessionRateLimits
from .chat_session_chatkit_configuration import ChatSessionChatKitConfiguration

__all__ = ["ChatSession"]


class ChatSession(BaseModel):
    """Represents a ChatKit session and its resolved configuration."""

    id: str
    """Identifier for the ChatKit session."""

    chatkit_configuration: ChatSessionChatKitConfiguration
    """Resolved ChatKit feature configuration for the session."""

    client_secret: str
    """Ephemeral client secret that authenticates session requests."""

    expires_at: int
    """Unix timestamp (in seconds) for when the session expires."""

    max_requests_per_1_minute: int
    """Convenience copy of the per-minute request limit."""

    object: Literal["chatkit.session"]
    """Type discriminator that is always `chatkit.session`."""

    rate_limits: ChatSessionRateLimits
    """Resolved rate limit values."""

    status: ChatSessionStatus
    """Current lifecycle state of the session."""

    user: str
    """User identifier associated with the session."""

    workflow: ChatKitWorkflow
    """Workflow metadata for the session."""
