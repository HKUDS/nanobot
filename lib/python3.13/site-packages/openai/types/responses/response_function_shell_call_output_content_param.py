# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from __future__ import annotations

from typing import Union
from typing_extensions import Literal, Required, TypeAlias, TypedDict

__all__ = ["ResponseFunctionShellCallOutputContentParam", "Outcome", "OutcomeTimeout", "OutcomeExit"]


class OutcomeTimeout(TypedDict, total=False):
    """Indicates that the shell call exceeded its configured time limit."""

    type: Required[Literal["timeout"]]
    """The outcome type. Always `timeout`."""


class OutcomeExit(TypedDict, total=False):
    """Indicates that the shell commands finished and returned an exit code."""

    exit_code: Required[int]
    """The exit code returned by the shell process."""

    type: Required[Literal["exit"]]
    """The outcome type. Always `exit`."""


Outcome: TypeAlias = Union[OutcomeTimeout, OutcomeExit]


class ResponseFunctionShellCallOutputContentParam(TypedDict, total=False):
    """Captured stdout and stderr for a portion of a shell tool call output."""

    outcome: Required[Outcome]
    """The exit or timeout outcome associated with this shell call."""

    stderr: Required[str]
    """Captured stderr output for the shell call."""

    stdout: Required[str]
    """Captured stdout output for the shell call."""
