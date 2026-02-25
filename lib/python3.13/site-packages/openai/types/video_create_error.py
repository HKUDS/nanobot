# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from .._models import BaseModel

__all__ = ["VideoCreateError"]


class VideoCreateError(BaseModel):
    """An error that occurred while generating the response."""

    code: str
    """A machine-readable error code that was returned."""

    message: str
    """A human-readable description of the error that was returned."""
