# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from __future__ import annotations

from typing import Union, Iterable, Optional
from typing_extensions import Literal, Required, TypeAlias, TypedDict

from ..._types import SequenceNotStr
from .inline_skill_param import InlineSkillParam
from .skill_reference_param import SkillReferenceParam
from .container_network_policy_disabled_param import ContainerNetworkPolicyDisabledParam
from .container_network_policy_allowlist_param import ContainerNetworkPolicyAllowlistParam

__all__ = ["ContainerAutoParam", "NetworkPolicy", "Skill"]

NetworkPolicy: TypeAlias = Union[ContainerNetworkPolicyDisabledParam, ContainerNetworkPolicyAllowlistParam]

Skill: TypeAlias = Union[SkillReferenceParam, InlineSkillParam]


class ContainerAutoParam(TypedDict, total=False):
    type: Required[Literal["container_auto"]]
    """Automatically creates a container for this request"""

    file_ids: SequenceNotStr[str]
    """An optional list of uploaded files to make available to your code."""

    memory_limit: Optional[Literal["1g", "4g", "16g", "64g"]]
    """The memory limit for the container."""

    network_policy: NetworkPolicy
    """Network access policy for the container."""

    skills: Iterable[Skill]
    """An optional list of skills referenced by id or inline data."""
