# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from __future__ import annotations

from typing_extensions import Required, TypedDict

__all__ = ["ContainerNetworkPolicyDomainSecretParam"]


class ContainerNetworkPolicyDomainSecretParam(TypedDict, total=False):
    domain: Required[str]
    """The domain associated with the secret."""

    name: Required[str]
    """The name of the secret to inject for the domain."""

    value: Required[str]
    """The secret value to inject for the domain."""
