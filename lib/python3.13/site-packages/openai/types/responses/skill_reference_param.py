# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from __future__ import annotations

from typing_extensions import Literal, Required, TypedDict

__all__ = ["SkillReferenceParam"]


class SkillReferenceParam(TypedDict, total=False):
    skill_id: Required[str]
    """The ID of the referenced skill."""

    type: Required[Literal["skill_reference"]]
    """References a skill created with the /v1/skills endpoint."""

    version: str
    """Optional skill version. Use a positive integer or 'latest'. Omit for default."""
