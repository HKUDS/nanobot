"""Utility functions for nanobot."""

from nanobot.utils.helpers import ensure_dir, get_workspace_path, get_data_path
from nanobot.utils.errors import (
    # Base exceptions
    NanobotError,
    ErrorInfo,
    ErrorSeverity,
    ErrorRecoverability,
    # Provider errors
    ProviderError,
    ProviderAuthError,
    ProviderRateLimitError,
    ProviderConnectionError,
    ProviderModelNotFoundError,
    ProviderTimeoutError,
    # Channel errors
    ChannelError,
    ChannelAuthError,
    ChannelConnectionError,
    ChannelSendError,
    ChannelReceiveError,
    # Tool errors
    ToolError,
    ToolNotFoundError,
    ToolExecutionError,
    ToolTimeoutError,
    # Session errors
    SessionError,
    SessionNotFoundError,
    SessionExpiredError,
    # Memory errors
    MemoryError,
    MemoryNotFoundError,
    MemoryWriteError,
    # Retry and circuit breaker
    RetryPolicy,
    CircuitBreaker,
    CircuitState,
    with_retry,
    # Utility functions
    format_error_for_user,
    log_error,
    classify_exception,
)

__all__ = [
    # Helpers
    "ensure_dir",
    "get_workspace_path",
    "get_data_path",
    # Base exceptions
    "NanobotError",
    "ErrorInfo",
    "ErrorSeverity",
    "ErrorRecoverability",
    # Provider errors
    "ProviderError",
    "ProviderAuthError",
    "ProviderRateLimitError",
    "ProviderConnectionError",
    "ProviderModelNotFoundError",
    "ProviderTimeoutError",
    # Channel errors
    "ChannelError",
    "ChannelAuthError",
    "ChannelConnectionError",
    "ChannelSendError",
    "ChannelReceiveError",
    # Tool errors
    "ToolError",
    "ToolNotFoundError",
    "ToolExecutionError",
    "ToolTimeoutError",
    # Session errors
    "SessionError",
    "SessionNotFoundError",
    "SessionExpiredError",
    # Memory errors
    "MemoryError",
    "MemoryNotFoundError",
    "MemoryWriteError",
    # Retry and circuit breaker
    "RetryPolicy",
    "CircuitBreaker",
    "CircuitState",
    "with_retry",
    # Utility functions
    "format_error_for_user",
    "log_error",
    "classify_exception",
]
