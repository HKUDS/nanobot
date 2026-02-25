# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from typing import List, Union, Optional
from typing_extensions import Literal, Annotated, TypeAlias

from ..._utils import PropertyInfo
from ..._models import BaseModel
from .inline_skill import InlineSkill
from .skill_reference import SkillReference
from .container_network_policy_disabled import ContainerNetworkPolicyDisabled
from .container_network_policy_allowlist import ContainerNetworkPolicyAllowlist

__all__ = ["ContainerAuto", "NetworkPolicy", "Skill"]

NetworkPolicy: TypeAlias = Annotated[
    Union[ContainerNetworkPolicyDisabled, ContainerNetworkPolicyAllowlist], PropertyInfo(discriminator="type")
]

Skill: TypeAlias = Annotated[Union[SkillReference, InlineSkill], PropertyInfo(discriminator="type")]


class ContainerAuto(BaseModel):
    type: Literal["container_auto"]
    """Automatically creates a container for this request"""

    file_ids: Optional[List[str]] = None
    """An optional list of uploaded files to make available to your code."""

    memory_limit: Optional[Literal["1g", "4g", "16g", "64g"]] = None
    """The memory limit for the container."""

    network_policy: Optional[NetworkPolicy] = None
    """Network access policy for the container."""

    skills: Optional[List[Skill]] = None
    """An optional list of skills referenced by id or inline data."""
