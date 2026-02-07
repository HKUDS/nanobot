"""Shared error types for nanobot.

Goal: don't silently turn infrastructure failures into model "content".
Provider/tool failures should be explicit and handled at the right layer.
"""


class NanobotError(Exception):
    """Base error for nanobot."""


class ProviderCallError(NanobotError):
    """LLM/provider call failed (network/auth/model/etc.)."""


class ToolNotFoundError(NanobotError):
    """Tool name requested by LLM isn't registered."""


class ToolValidationError(NanobotError):
    """Tool arguments failed schema validation."""


class ToolExecutionError(NanobotError):
    """Tool threw while executing."""

