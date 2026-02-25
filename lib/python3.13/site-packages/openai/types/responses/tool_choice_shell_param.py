# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from __future__ import annotations

from typing_extensions import Literal, Required, TypedDict

__all__ = ["ToolChoiceShellParam"]


class ToolChoiceShellParam(TypedDict, total=False):
    """Forces the model to call the shell tool when a tool call is required."""

    type: Required[Literal["shell"]]
    """The tool to call. Always `shell`."""
