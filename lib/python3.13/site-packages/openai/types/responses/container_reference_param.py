# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from __future__ import annotations

from typing_extensions import Literal, Required, TypedDict

__all__ = ["ContainerReferenceParam"]


class ContainerReferenceParam(TypedDict, total=False):
    container_id: Required[str]
    """The ID of the referenced container."""

    type: Required[Literal["container_reference"]]
    """References a container created with the /v1/containers endpoint"""
