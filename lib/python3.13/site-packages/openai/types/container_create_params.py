# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from __future__ import annotations

from typing import Union, Iterable
from typing_extensions import Literal, Required, TypeAlias, TypedDict

from .._types import SequenceNotStr
from .responses.inline_skill_param import InlineSkillParam
from .responses.skill_reference_param import SkillReferenceParam
from .responses.container_network_policy_disabled_param import ContainerNetworkPolicyDisabledParam
from .responses.container_network_policy_allowlist_param import ContainerNetworkPolicyAllowlistParam

__all__ = ["ContainerCreateParams", "ExpiresAfter", "NetworkPolicy", "Skill"]


class ContainerCreateParams(TypedDict, total=False):
    name: Required[str]
    """Name of the container to create."""

    expires_after: ExpiresAfter
    """Container expiration time in seconds relative to the 'anchor' time."""

    file_ids: SequenceNotStr[str]
    """IDs of files to copy to the container."""

    memory_limit: Literal["1g", "4g", "16g", "64g"]
    """Optional memory limit for the container. Defaults to "1g"."""

    network_policy: NetworkPolicy
    """Network access policy for the container."""

    skills: Iterable[Skill]
    """An optional list of skills referenced by id or inline data."""


class ExpiresAfter(TypedDict, total=False):
    """Container expiration time in seconds relative to the 'anchor' time."""

    anchor: Required[Literal["last_active_at"]]
    """Time anchor for the expiration time.

    Currently only 'last_active_at' is supported.
    """

    minutes: Required[int]


NetworkPolicy: TypeAlias = Union[ContainerNetworkPolicyDisabledParam, ContainerNetworkPolicyAllowlistParam]

Skill: TypeAlias = Union[SkillReferenceParam, InlineSkillParam]
