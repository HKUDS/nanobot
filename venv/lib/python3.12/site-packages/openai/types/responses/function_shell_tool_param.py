# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from __future__ import annotations

from typing_extensions import Literal, Required, TypedDict

__all__ = ["FunctionShellToolParam"]


class FunctionShellToolParam(TypedDict, total=False):
    """A tool that allows the model to execute shell commands."""

    type: Required[Literal["shell"]]
    """The type of the shell tool. Always `shell`."""
