# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from __future__ import annotations

from typing import Union, Optional
from typing_extensions import Literal, Required, TypeAlias, TypedDict

from .container_auto_param import ContainerAutoParam
from .local_environment_param import LocalEnvironmentParam
from .container_reference_param import ContainerReferenceParam

__all__ = ["FunctionShellToolParam", "Environment"]

Environment: TypeAlias = Union[ContainerAutoParam, LocalEnvironmentParam, ContainerReferenceParam]


class FunctionShellToolParam(TypedDict, total=False):
    """A tool that allows the model to execute shell commands."""

    type: Required[Literal["shell"]]
    """The type of the shell tool. Always `shell`."""

    environment: Optional[Environment]
