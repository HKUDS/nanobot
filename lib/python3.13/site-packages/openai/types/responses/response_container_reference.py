# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from typing_extensions import Literal

from ..._models import BaseModel

__all__ = ["ResponseContainerReference"]


class ResponseContainerReference(BaseModel):
    """Represents a container created with /v1/containers."""

    container_id: str

    type: Literal["container_reference"]
    """The environment type. Always `container_reference`."""
