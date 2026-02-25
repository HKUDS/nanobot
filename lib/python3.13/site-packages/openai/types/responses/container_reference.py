# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from typing_extensions import Literal

from ..._models import BaseModel

__all__ = ["ContainerReference"]


class ContainerReference(BaseModel):
    container_id: str
    """The ID of the referenced container."""

    type: Literal["container_reference"]
    """References a container created with the /v1/containers endpoint"""
