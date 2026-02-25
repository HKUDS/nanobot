# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from typing_extensions import Literal

from ..._models import BaseModel

__all__ = ["ResponseLocalEnvironment"]


class ResponseLocalEnvironment(BaseModel):
    """Represents the use of a local environment to perform shell actions."""

    type: Literal["local"]
    """The environment type. Always `local`."""
