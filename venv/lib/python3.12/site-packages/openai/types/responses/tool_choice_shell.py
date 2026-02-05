# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from typing_extensions import Literal

from ..._models import BaseModel

__all__ = ["ToolChoiceShell"]


class ToolChoiceShell(BaseModel):
    """Forces the model to call the shell tool when a tool call is required."""

    type: Literal["shell"]
    """The tool to call. Always `shell`."""
