# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from ..._models import BaseModel

__all__ = ["ContainerNetworkPolicyDomainSecret"]


class ContainerNetworkPolicyDomainSecret(BaseModel):
    domain: str
    """The domain associated with the secret."""

    name: str
    """The name of the secret to inject for the domain."""

    value: str
    """The secret value to inject for the domain."""
