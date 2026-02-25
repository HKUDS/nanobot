# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from typing_extensions import Literal

from ..._models import BaseModel

__all__ = ["ContainerNetworkPolicyDisabled"]


class ContainerNetworkPolicyDisabled(BaseModel):
    type: Literal["disabled"]
    """Disable outbound network access. Always `disabled`."""
