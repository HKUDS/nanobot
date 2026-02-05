# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from typing_extensions import Literal

from ..._models import BaseModel

__all__ = ["ToolChoiceFunction"]


class ToolChoiceFunction(BaseModel):
    """Use this option to force the model to call a specific function."""

    name: str
    """The name of the function to call."""

    type: Literal["function"]
    """For function calling, the type is always `function`."""
