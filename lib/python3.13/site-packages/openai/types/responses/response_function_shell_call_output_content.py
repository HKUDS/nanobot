# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from typing import Union
from typing_extensions import Literal, Annotated, TypeAlias

from ..._utils import PropertyInfo
from ..._models import BaseModel

__all__ = ["ResponseFunctionShellCallOutputContent", "Outcome", "OutcomeTimeout", "OutcomeExit"]


class OutcomeTimeout(BaseModel):
    """Indicates that the shell call exceeded its configured time limit."""

    type: Literal["timeout"]
    """The outcome type. Always `timeout`."""


class OutcomeExit(BaseModel):
    """Indicates that the shell commands finished and returned an exit code."""

    exit_code: int
    """The exit code returned by the shell process."""

    type: Literal["exit"]
    """The outcome type. Always `exit`."""


Outcome: TypeAlias = Annotated[Union[OutcomeTimeout, OutcomeExit], PropertyInfo(discriminator="type")]


class ResponseFunctionShellCallOutputContent(BaseModel):
    """Captured stdout and stderr for a portion of a shell tool call output."""

    outcome: Outcome
    """The exit or timeout outcome associated with this shell call."""

    stderr: str
    """Captured stderr output for the shell call."""

    stdout: str
    """Captured stdout output for the shell call."""
