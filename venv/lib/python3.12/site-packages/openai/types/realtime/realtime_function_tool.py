# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from typing import Optional
from typing_extensions import Literal

from ..._models import BaseModel

__all__ = ["RealtimeFunctionTool"]


class RealtimeFunctionTool(BaseModel):
    description: Optional[str] = None
    """
    The description of the function, including guidance on when and how to call it,
    and guidance about what to tell the user when calling (if anything).
    """

    name: Optional[str] = None
    """The name of the function."""

    parameters: Optional[object] = None
    """Parameters of the function in JSON Schema."""

    type: Optional[Literal["function"]] = None
    """The type of the tool, i.e. `function`."""
