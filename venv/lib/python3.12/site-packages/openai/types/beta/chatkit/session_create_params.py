# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from __future__ import annotations

from typing_extensions import Required, TypedDict

from .chat_session_workflow_param import ChatSessionWorkflowParam
from .chat_session_rate_limits_param import ChatSessionRateLimitsParam
from .chat_session_expires_after_param import ChatSessionExpiresAfterParam
from .chat_session_chatkit_configuration_param import ChatSessionChatKitConfigurationParam

__all__ = ["SessionCreateParams"]


class SessionCreateParams(TypedDict, total=False):
    user: Required[str]
    """
    A free-form string that identifies your end user; ensures this Session can
    access other objects that have the same `user` scope.
    """

    workflow: Required[ChatSessionWorkflowParam]
    """Workflow that powers the session."""

    chatkit_configuration: ChatSessionChatKitConfigurationParam
    """Optional overrides for ChatKit runtime configuration features"""

    expires_after: ChatSessionExpiresAfterParam
    """Optional override for session expiration timing in seconds from creation.

    Defaults to 10 minutes.
    """

    rate_limits: ChatSessionRateLimitsParam
    """Optional override for per-minute request limits. When omitted, defaults to 10."""
