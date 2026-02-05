# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from typing_extensions import Literal

from ..._models import BaseModel

__all__ = ["FunctionShellTool"]


class FunctionShellTool(BaseModel):
    """A tool that allows the model to execute shell commands."""

    type: Literal["shell"]
    """The type of the shell tool. Always `shell`."""
