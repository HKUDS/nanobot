"""Error handling utilities for nanobot.

This module provides:
- Custom exception hierarchy for structured error handling
- Retry decorator with exponential backoff and jitter
- Circuit breaker pattern for external service resilience
- Error context extraction for debugging
"""

from __future__ import annotations

import asyncio
import functools
import random
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Coroutine, ParamSpec, TypeVar

from loguru import logger

P = ParamSpec("P")
T = TypeVar("T")


# =============================================================================
# Exception Hierarchy
# =============================================================================


class NanobotError(Exception):
    """Base exception for all nanobot errors."""

    def __init__(self, message: str, context: dict[str, Any] | None = None):
        super().__init__(message)
        self.message = message
        self.context = context or {}

    def __str__(self) -> str:
        if self.context:
            ctx_str = ", ".join(f"{k}={v}" for k, v in self.context.items())
            return f"{self.message} ({ctx_str})"
        return self.message


# --- Provider Errors ---

class ProviderError(NanobotError):
    """Base error for LLM provider issues."""
    pass


class ProviderConnectionError(ProviderError):
    """Failed to connect to provider API."""
    pass


class ProviderRateLimitError(ProviderError):
    """Rate limit exceeded from provider."""
    
    def __init__(
        self, 
        message: str, 
        retry_after: float | None = None,
        context: dict[str, Any] | None = None
    ):
        super().__init__(message, context)
        self.retry_after = retry_after


class ProviderAuthError(ProviderError):
    """Authentication failed with provider."""
    pass


class ProviderModelNotFoundError(ProviderError):
    """Requested model not available."""
    pass


class ProviderResponseError(ProviderError):
    """Invalid or unexpected response from provider."""
    pass


# --- Channel Errors ---

class ChannelError(NanobotError):
    """Base error for channel issues."""
    pass


class ChannelConnectionError(ChannelError):
    """Failed to connect to channel."""
    pass


class ChannelAuthError(ChannelError):
    """Authentication failed with channel."""
    pass


class ChannelSendError(ChannelError):
    """Failed to send message through channel."""
    pass


class ChannelReceiveError(ChannelError):
    """Failed to receive message from channel."""
    pass


# --- Tool Errors ---

class ToolError(NanobotError):
    """Base error for tool execution issues."""
    pass


class ToolNotFoundError(ToolError):
    """Requested tool not found."""
    pass


class ToolValidationError(ToolError):
    """Tool parameter validation failed."""
    pass


class ToolExecutionError(ToolError):
    """Tool execution failed."""
    pass


class ToolTimeoutError(ToolError):
    """Tool execution timed out."""
    pass


# --- Session Errors ---

class SessionError(NanobotError):
    """Base error for session issues."""
    pass


class SessionNotFoundError(SessionError):
    """Session not found."""
    pass


class SessionCorruptedError(SessionError):
    """Session data is corrupted."""
    pass


# --- Memory Errors ---

class MemoryError(NanobotError):
    """Base error for memory issues."""
    pass


class MemoryWriteError(MemoryError):
    """Failed to write to memory."""
    pass


class MemoryReadError(MemoryError):
    """Failed to read from memory."""
    pass


# =============================================================================
# Error Classification
# =============================================================================


class ErrorSeverity(Enum):
    """Error severity levels."""
    LOW = "low"          # Minor issue, operation can continue
    MEDIUM = "medium"    # Operation failed, but system is stable
    HIGH = "high"        # Significant issue, may affect other operations
    CRITICAL = "critical"  # System-level failure


class ErrorRecoverability(Enum):
    """Whether an error can be recovered from."""
    RECOVERABLE = "recoverable"        # Retry might succeed
    TRANSIENT = "transient"            # Temporary condition, wait and retry
    PERMANENT = "permanent"            # No amount of retrying will help
    UNKNOWN = "unknown"                # Unclear if recoverable


@dataclass
class ErrorInfo:
    """Structured information about an error."""
    error: Exception
    severity: ErrorSeverity = ErrorSeverity.MEDIUM
    recoverability: ErrorRecoverability = ErrorRecoverability.UNKNOWN
    retry_after: float | None = None
    suggested_action: str = ""
    context: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_exception(cls, error: Exception) -> "ErrorInfo":
        """Classify an exception into structured info."""
        # Provider errors
        if isinstance(error, ProviderRateLimitError):
            return cls(
                error=error,
                severity=ErrorSeverity.MEDIUM,
                recoverability=ErrorRecoverability.TRANSIENT,
                retry_after=error.retry_after,
                suggested_action="Wait and retry with backoff",
            )
        
        if isinstance(error, ProviderConnectionError):
            return cls(
                error=error,
                severity=ErrorSeverity.MEDIUM,
                recoverability=ErrorRecoverability.TRANSIENT,
                suggested_action="Check network connectivity and retry",
            )
        
        if isinstance(error, ProviderAuthError):
            return cls(
                error=error,
                severity=ErrorSeverity.HIGH,
                recoverability=ErrorRecoverability.PERMANENT,
                suggested_action="Check API key configuration",
            )
        
        # Channel errors
        if isinstance(error, ChannelConnectionError):
            return cls(
                error=error,
                severity=ErrorSeverity.MEDIUM,
                recoverability=ErrorRecoverability.TRANSIENT,
                suggested_action="Reconnect to channel",
            )
        
        if isinstance(error, ChannelAuthError):
            return cls(
                error=error,
                severity=ErrorSeverity.HIGH,
                recoverability=ErrorRecoverability.PERMANENT,
                suggested_action="Check channel credentials",
            )
        
        # Tool errors
        if isinstance(error, ToolTimeoutError):
            return cls(
                error=error,
                severity=ErrorSeverity.LOW,
                recoverability=ErrorRecoverability.TRANSIENT,
                suggested_action="Retry with longer timeout or simpler task",
            )
        
        if isinstance(error, ToolValidationError):
            return cls(
                error=error,
                severity=ErrorSeverity.LOW,
                recoverability=ErrorRecoverability.PERMANENT,
                suggested_action="Fix tool parameters",
            )
        
        # Generic classification
        error_str = str(error).lower()
        
        if "timeout" in error_str or "timed out" in error_str:
            return cls(
                error=error,
                severity=ErrorSeverity.LOW,
                recoverability=ErrorRecoverability.TRANSIENT,
                suggested_action="Retry operation",
            )
        
        if "rate limit" in error_str or "too many requests" in error_str:
            return cls(
                error=error,
                severity=ErrorSeverity.MEDIUM,
                recoverability=ErrorRecoverability.TRANSIENT,
                suggested_action="Wait and retry with backoff",
            )
        
        if "connection" in error_str or "network" in error_str:
            return cls(
                error=error,
                severity=ErrorSeverity.MEDIUM,
                recoverability=ErrorRecoverability.TRANSIENT,
                suggested_action="Check network and retry",
            )
        
        if "auth" in error_str or "unauthorized" in error_str or "forbidden" in error_str:
            return cls(
                error=error,
                severity=ErrorSeverity.HIGH,
                recoverability=ErrorRecoverability.PERMANENT,
                suggested_action="Check credentials",
            )
        
        return cls(
            error=error,
            severity=ErrorSeverity.MEDIUM,
            recoverability=ErrorRecoverability.UNKNOWN,
        )


# =============================================================================
# Retry Logic
# =============================================================================


@dataclass
class RetryPolicy:
    """Configuration for retry behavior."""
    max_retries: int = 3
    base_delay: float = 1.0
    max_delay: float = 60.0
    exponential_base: float = 2.0
    jitter: bool = True
    jitter_factor: float = 0.1
    
    # Exceptions that should trigger retry
    retryable_exceptions: tuple[type[Exception], ...] = (
        ProviderConnectionError,
        ProviderRateLimitError,
        ChannelConnectionError,
        ToolTimeoutError,
        ConnectionError,
        TimeoutError,
    )
    
    # Exceptions that should NOT be retried
    non_retryable_exceptions: tuple[type[Exception], ...] = (
        ProviderAuthError,
        ChannelAuthError,
        ToolValidationError,
        ToolNotFoundError,
        ValueError,
        TypeError,
    )

    def should_retry(self, error: Exception, attempt: int) -> bool:
        """Determine if we should retry after an error."""
        if attempt >= self.max_retries:
            return False
        
        # Check non-retryable first
        if isinstance(error, self.non_retryable_exceptions):
            return False
        
        # Check retryable
        if isinstance(error, self.retryable_exceptions):
            return True
        
        # Check error message for hints
        error_info = ErrorInfo.from_exception(error)
        return error_info.recoverability in (
            ErrorRecoverability.RECOVERABLE,
            ErrorRecoverability.TRANSIENT,
        )

    def get_delay(self, attempt: int, error: Exception | None = None) -> float:
        """Calculate delay before next retry."""
        # Use retry_after from rate limit error if available
        if isinstance(error, ProviderRateLimitError) and error.retry_after:
            delay = error.retry_after
        else:
            # Exponential backoff
            delay = self.base_delay * (self.exponential_base ** (attempt - 1))
        
        # Cap at max delay
        delay = min(delay, self.max_delay)
        
        # Add jitter to avoid thundering herd
        if self.jitter:
            jitter_range = delay * self.jitter_factor
            delay += random.uniform(-jitter_range, jitter_range)
        
        return max(0, delay)


def with_retry(
    policy: RetryPolicy | None = None,
    on_retry: Callable[[Exception, int, float], None] | None = None,
):
    """
    Decorator to add retry logic to async functions.
    
    Args:
        policy: Retry configuration. Uses defaults if not provided.
        on_retry: Optional callback called on each retry with (error, attempt, delay).
    
    Returns:
        Decorated function with retry logic.
    
    Example:
        @with_retry(RetryPolicy(max_retries=5, base_delay=2.0))
        async def fetch_data():
            return await api.get("/data")
    """
    if policy is None:
        policy = RetryPolicy()
    
    def decorator(func: Callable[P, Coroutine[Any, Any, T]]) -> Callable[P, Coroutine[Any, Any, T]]:
        @functools.wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            last_error: Exception | None = None
            
            for attempt in range(1, policy.max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    last_error = e
                    
                    if not policy.should_retry(e, attempt):
                        raise
                    
                    delay = policy.get_delay(attempt, e)
                    
                    if on_retry:
                        on_retry(e, attempt, delay)
                    else:
                        logger.warning(
                            f"Retry {attempt}/{policy.max_retries} for {func.__name__} "
                            f"after {delay:.2f}s: {e}"
                        )
                    
                    await asyncio.sleep(delay)
            
            # Should not reach here, but raise last error just in case
            if last_error:
                raise last_error
            raise RuntimeError("Unexpected state in retry logic")
        
        return wrapper
    
    return decorator


def sync_with_retry(
    policy: RetryPolicy | None = None,
    on_retry: Callable[[Exception, int, float], None] | None = None,
):
    """
    Decorator to add retry logic to synchronous functions.
    
    Args:
        policy: Retry configuration. Uses defaults if not provided.
        on_retry: Optional callback called on each retry with (error, attempt, delay).
    
    Returns:
        Decorated function with retry logic.
    """
    if policy is None:
        policy = RetryPolicy()
    
    def decorator(func: Callable[P, T]) -> Callable[P, T]:
        @functools.wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            last_error: Exception | None = None
            
            for attempt in range(1, policy.max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_error = e
                    
                    if not policy.should_retry(e, attempt):
                        raise
                    
                    delay = policy.get_delay(attempt, e)
                    
                    if on_retry:
                        on_retry(e, attempt, delay)
                    else:
                        logger.warning(
                            f"Retry {attempt}/{policy.max_retries} for {func.__name__} "
                            f"after {delay:.2f}s: {e}"
                        )
                    
                    time.sleep(delay)
            
            if last_error:
                raise last_error
            raise RuntimeError("Unexpected state in retry logic")
        
        return wrapper
    
    return decorator


# =============================================================================
# Circuit Breaker
# =============================================================================


class CircuitState(Enum):
    """Circuit breaker states."""
    CLOSED = "closed"      # Normal operation, requests flow through
    OPEN = "open"          # Failing, requests are blocked
    HALF_OPEN = "half_open"  # Testing if service recovered


@dataclass
class CircuitStats:
    """Statistics for circuit breaker."""
    failures: int = 0
    successes: int = 0
    last_failure_time: float | None = None
    last_success_time: float | None = None
    state_changed_at: float = field(default_factory=time.time)


class CircuitBreaker:
    """
    Circuit breaker for protecting external service calls.
    
    Implements the circuit breaker pattern to prevent cascading failures
    when an external service is unavailable.
    
    States:
    - CLOSED: Normal operation. Requests pass through.
    - OPEN: Service is failing. Requests are rejected immediately.
    - HALF_OPEN: Testing if service recovered. Limited requests allowed.
    
    Example:
        breaker = CircuitBreaker(name="openai", failure_threshold=5)
        
        async def call_api():
            return await breaker.call(api_client.generate)
    """
    
    def __init__(
        self,
        name: str = "default",
        failure_threshold: int = 5,
        success_threshold: int = 2,
        timeout: float = 30.0,
        half_open_max_calls: int = 3,
    ):
        """
        Initialize circuit breaker.
        
        Args:
            name: Identifier for logging.
            failure_threshold: Failures before opening circuit.
            success_threshold: Successes in half-open to close circuit.
            timeout: Seconds to wait before trying half-open.
            half_open_max_calls: Max calls allowed in half-open state.
        """
        self.name = name
        self.failure_threshold = failure_threshold
        self.success_threshold = success_threshold
        self.timeout = timeout
        self.half_open_max_calls = half_open_max_calls
        
        self._state = CircuitState.CLOSED
        self._stats = CircuitStats()
        self._half_open_calls = 0
        self._lock = asyncio.Lock()
    
    @property
    def state(self) -> CircuitState:
        """Current circuit state."""
        return self._state
    
    @property
    def is_closed(self) -> bool:
        """Check if circuit is closed (normal operation)."""
        return self._state == CircuitState.CLOSED
    
    @property
    def is_open(self) -> bool:
        """Check if circuit is open (failing)."""
        return self._state == CircuitState.OPEN
    
    def _should_allow_request(self) -> bool:
        """Check if request should be allowed through."""
        if self._state == CircuitState.CLOSED:
            return True
        
        if self._state == CircuitState.OPEN:
            # Check if timeout has passed
            if self._stats.last_failure_time is None:
                return False
            
            elapsed = time.time() - self._stats.last_failure_time
            if elapsed >= self.timeout:
                logger.info(f"Circuit '{self.name}' transitioning to HALF_OPEN")
                self._transition_to(CircuitState.HALF_OPEN)
                return True
            return False
        
        if self._state == CircuitState.HALF_OPEN:
            # Allow limited requests in half-open
            if self._half_open_calls < self.half_open_max_calls:
                self._half_open_calls += 1
                return True
            return False
        
        return False
    
    def _transition_to(self, new_state: CircuitState) -> None:
        """Transition to a new state."""
        old_state = self._state
        self._state = new_state
        self._stats.state_changed_at = time.time()
        
        if new_state == CircuitState.HALF_OPEN:
            self._half_open_calls = 0
        
        logger.info(f"Circuit '{self.name}' transitioned: {old_state.value} -> {new_state.value}")
    
    def record_success(self) -> None:
        """Record a successful call."""
        self._stats.successes += 1
        self._stats.last_success_time = time.time()
        
        if self._state == CircuitState.HALF_OPEN:
            if self._stats.successes >= self.success_threshold:
                logger.info(f"Circuit '{self.name}' recovered, closing")
                self._transition_to(CircuitState.CLOSED)
                self._stats.failures = 0
                self._stats.successes = 0
    
    def record_failure(self) -> None:
        """Record a failed call."""
        self._stats.failures += 1
        self._stats.last_failure_time = time.time()
        
        if self._state == CircuitState.HALF_OPEN:
            logger.warning(f"Circuit '{self.name}' failed in HALF_OPEN, reopening")
            self._transition_to(CircuitState.OPEN)
            self._stats.successes = 0
        
        elif self._state == CircuitState.CLOSED:
            if self._stats.failures >= self.failure_threshold:
                logger.warning(
                    f"Circuit '{self.name}' failure threshold reached "
                    f"({self._stats.failures}/{self.failure_threshold}), opening"
                )
                self._transition_to(CircuitState.OPEN)
    
    async def call(
        self, 
        func: Callable[P, Coroutine[Any, Any, T]], 
        *args: P.args, 
        **kwargs: P.kwargs
    ) -> T:
        """
        Execute a function through the circuit breaker.
        
        Args:
            func: Async function to call.
            *args: Positional arguments for the function.
            **kwargs: Keyword arguments for the function.
        
        Returns:
            Result of the function call.
        
        Raises:
            CircuitBreakerError: If circuit is open.
            Any exception raised by the function.
        """
        async with self._lock:
            if not self._should_allow_request():
                raise CircuitBreakerError(
                    f"Circuit '{self.name}' is open",
                    context={
                        "name": self.name,
                        "failures": self._stats.failures,
                        "last_failure": self._stats.last_failure_time,
                    }
                )
        
        try:
            result = await func(*args, **kwargs)
            async with self._lock:
                self.record_success()
            return result
        except Exception as e:
            async with self._lock:
                self.record_failure()
            raise
    
    def reset(self) -> None:
        """Reset the circuit breaker to closed state."""
        self._state = CircuitState.CLOSED
        self._stats = CircuitStats()
        self._half_open_calls = 0
        logger.info(f"Circuit '{self.name}' reset to CLOSED")


class CircuitBreakerError(NanobotError):
    """Raised when circuit breaker is open."""
    pass


# =============================================================================
# Error Context Helpers
# =============================================================================


def extract_error_context(error: Exception) -> dict[str, Any]:
    """
    Extract useful context from an exception for logging/debugging.
    
    Args:
        error: The exception to extract context from.
    
    Returns:
        Dictionary with error context.
    """
    context: dict[str, Any] = {
        "error_type": type(error).__name__,
        "error_message": str(error),
    }
    
    # Add nanobot-specific context if available
    if isinstance(error, NanobotError):
        context.update(error.context)
    
    # Add retry_after for rate limit errors
    if isinstance(error, ProviderRateLimitError):
        context["retry_after"] = error.retry_after
    
    # Add traceback for debugging
    import traceback
    context["traceback"] = traceback.format_exc()
    
    return context


def format_error_for_user(error: Exception) -> str:
    """
    Format an error message for user display.
    
    Creates a user-friendly message without exposing internal details.
    
    Args:
        error: The exception to format.
    
    Returns:
        User-friendly error message.
    """
    error_info = ErrorInfo.from_exception(error)
    
    # Map severity to user-friendly messages
    if isinstance(error, ProviderRateLimitError):
        return "The AI service is busy. Please try again in a moment."
    
    if isinstance(error, ProviderConnectionError):
        return "Unable to connect to the AI service. Please check your connection."
    
    if isinstance(error, ProviderAuthError):
        return "Authentication failed. Please check your API key configuration."
    
    if isinstance(error, ChannelConnectionError):
        return "Unable to connect to the chat service. Will retry automatically."
    
    if isinstance(error, ChannelAuthError):
        return "Chat service authentication failed. Please check your credentials."
    
    if isinstance(error, ToolTimeoutError):
        return "The operation took too long. Please try a simpler request."
    
    if isinstance(error, ToolValidationError):
        return f"Invalid request: {error.message}"
    
    # Generic fallback
    return f"An error occurred: {type(error).__name__}"


def log_error(
    error: Exception, 
    operation: str = "",
    extra_context: dict[str, Any] | None = None,
    level: str = "error",
) -> None:
    """
    Log an error with structured context.
    
    Args:
        error: The exception to log.
        operation: Description of what operation failed.
        extra_context: Additional context to include.
        level: Log level (debug, info, warning, error, critical).
    """
    context = extract_error_context(error)
    if extra_context:
        context.update(extra_context)
    
    error_info = ErrorInfo.from_exception(error)
    
    log_msg = f"{operation}: {error}" if operation else str(error)
    
    # Include context in log
    context_str = " | ".join(f"{k}={v}" for k, v in context.items() 
                             if k not in ("traceback", "error_message"))
    if context_str:
        log_msg = f"{log_msg} | {context_str}"
    
    # Log with appropriate level
    log_func = getattr(logger, level, logger.error)
    log_func(log_msg)
    
    # Log traceback at debug level
    logger.debug(f"Traceback for {operation or 'error'}:\n{context.get('traceback', '')}")
