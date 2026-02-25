# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from typing_extensions import Literal

from ..._models import BaseModel

__all__ = ["ToolChoiceApplyPatch"]


class ToolChoiceApplyPatch(BaseModel):
    """Forces the model to call the apply_patch tool when executing a tool call."""

    type: Literal["apply_patch"]
    """The tool to call. Always `apply_patch`."""
