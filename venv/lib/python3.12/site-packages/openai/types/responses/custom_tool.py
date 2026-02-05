# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from typing import Optional
from typing_extensions import Literal

from ..._models import BaseModel
from ..shared.custom_tool_input_format import CustomToolInputFormat

__all__ = ["CustomTool"]


class CustomTool(BaseModel):
    """A custom tool that processes input using a specified format.

    Learn more about   [custom tools](https://platform.openai.com/docs/guides/function-calling#custom-tools)
    """

    name: str
    """The name of the custom tool, used to identify it in tool calls."""

    type: Literal["custom"]
    """The type of the custom tool. Always `custom`."""

    description: Optional[str] = None
    """Optional description of the custom tool, used to provide more context."""

    format: Optional[CustomToolInputFormat] = None
    """The input format for the custom tool. Default is unconstrained text."""
