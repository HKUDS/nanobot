# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from typing_extensions import Literal

from ..._models import BaseModel

__all__ = ["ToolChoiceCustom"]


class ToolChoiceCustom(BaseModel):
    """Use this option to force the model to call a specific custom tool."""

    name: str
    """The name of the custom tool to call."""

    type: Literal["custom"]
    """For custom tool calling, the type is always `custom`."""
