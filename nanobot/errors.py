"""Structured error taxonomy for nanobot.

Typed exceptions enable the planning system and agent loop to make
smarter recovery decisions based on error category rather than parsing
error strings.
"""

from __future__ import annotations


class NanobotError(Exception):
    """Base class for all nanobot errors."""

    def __init__(self, message: str, *, recoverable: bool = True):
        super().__init__(message)
        self.recoverable = recoverable


# ---------------------------------------------------------------------------
# Delivery errors
# ---------------------------------------------------------------------------


class DeliverySkippedError(NanobotError):
    """A channel declined to deliver a message (config missing, channel down, etc.)."""

    def __init__(self, reason: str):
        super().__init__(reason, recoverable=True)


# ---------------------------------------------------------------------------
# Tool errors
# ---------------------------------------------------------------------------


class ToolExecutionError(NanobotError):
    """A tool failed during execution."""

    def __init__(
        self,
        tool_name: str,
        message: str,
        *,
        error_type: str = "unknown",
        recoverable: bool = True,
    ):
        super().__init__(message, recoverable=recoverable)
        self.tool_name = tool_name
        self.error_type = error_type


class ToolNotFoundError(ToolExecutionError):
    """Requested tool does not exist in the registry."""

    def __init__(self, tool_name: str, available: list[str] | None = None):
        avail = ", ".join(available or [])
        msg = f"Tool '{tool_name}' not found. Available: {avail}"
        super().__init__(tool_name, msg, error_type="not_found", recoverable=True)


class ToolValidationError(ToolExecutionError):
    """Tool parameter validation failed."""

    def __init__(self, tool_name: str, errors: list[str]):
        msg = f"Invalid parameters for tool '{tool_name}': {'; '.join(errors)}"
        super().__init__(tool_name, msg, error_type="validation", recoverable=True)
        self.validation_errors = errors


class ToolTimeoutError(ToolExecutionError):
    """Tool execution timed out."""

    def __init__(self, tool_name: str, timeout_seconds: int):
        msg = f"Tool '{tool_name}' timed out after {timeout_seconds}s"
        super().__init__(tool_name, msg, error_type="timeout", recoverable=True)
        self.timeout_seconds = timeout_seconds


class ToolPermissionError(ToolExecutionError):
    """Tool blocked by security policy."""

    def __init__(self, tool_name: str, reason: str):
        msg = f"Tool '{tool_name}' blocked: {reason}"
        super().__init__(tool_name, msg, error_type="permission", recoverable=False)


# ---------------------------------------------------------------------------
# Provider / LLM errors
# ---------------------------------------------------------------------------


class ProviderError(NanobotError):
    """An LLM provider call failed."""

    def __init__(
        self,
        provider: str,
        message: str,
        *,
        status_code: int | None = None,
        retryable: bool = True,
    ):
        super().__init__(message, recoverable=retryable)
        self.provider = provider
        self.status_code = status_code
        self.retryable = retryable


class BudgetExceededError(ProviderError):
    """Session LLM cost budget has been exceeded."""

    def __init__(self, spent_usd: float, budget_usd: float):
        super().__init__(
            "nanobot",
            f"Session cost budget exceeded: ${spent_usd:.4f} spent, limit is ${budget_usd:.4f}",
            retryable=False,
        )
        self.spent_usd = spent_usd
        self.budget_usd = budget_usd


# ---------------------------------------------------------------------------
# Context errors
# ---------------------------------------------------------------------------


class ContextOverflowError(NanobotError):
    """Messages exceed the context window budget."""

    def __init__(self, budget: int, actual: int):
        super().__init__(
            f"Context overflow: {actual} tokens exceeds budget of {budget}",
            recoverable=True,
        )
        self.budget = budget
        self.actual = actual


# ---------------------------------------------------------------------------
# Memory errors
# ---------------------------------------------------------------------------


class MemorySubsystemError(NanobotError):
    """A memory subsystem operation failed."""

    def __init__(self, operation: str, cause: str, *, recoverable: bool = True):
        super().__init__(f"Memory {operation} failed: {cause}", recoverable=recoverable)
        self.operation = operation
        self.cause = cause


class MemoryRetrievalError(MemorySubsystemError):
    """Memory retrieval failed."""

    def __init__(self, cause: str):
        super().__init__("retrieval", cause, recoverable=True)
