# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from typing import List, Optional
from typing_extensions import Literal

from ..._models import BaseModel
from .container_network_policy_domain_secret import ContainerNetworkPolicyDomainSecret

__all__ = ["ContainerNetworkPolicyAllowlist"]


class ContainerNetworkPolicyAllowlist(BaseModel):
    allowed_domains: List[str]
    """A list of allowed domains when type is `allowlist`."""

    type: Literal["allowlist"]
    """Allow outbound network access only to specified domains. Always `allowlist`."""

    domain_secrets: Optional[List[ContainerNetworkPolicyDomainSecret]] = None
    """Optional domain-scoped secrets for allowlisted domains."""
