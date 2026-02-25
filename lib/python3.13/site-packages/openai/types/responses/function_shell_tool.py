# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from typing import Union, Optional
from typing_extensions import Literal, Annotated, TypeAlias

from ..._utils import PropertyInfo
from ..._models import BaseModel
from .container_auto import ContainerAuto
from .local_environment import LocalEnvironment
from .container_reference import ContainerReference

__all__ = ["FunctionShellTool", "Environment"]

Environment: TypeAlias = Annotated[
    Union[ContainerAuto, LocalEnvironment, ContainerReference, None], PropertyInfo(discriminator="type")
]


class FunctionShellTool(BaseModel):
    """A tool that allows the model to execute shell commands."""

    type: Literal["shell"]
    """The type of the shell tool. Always `shell`."""

    environment: Optional[Environment] = None
