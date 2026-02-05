# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from typing import Optional
from typing_extensions import Literal

from ..._models import BaseModel

__all__ = ["PythonGrader"]


class PythonGrader(BaseModel):
    """A PythonGrader object that runs a python script on the input."""

    name: str
    """The name of the grader."""

    source: str
    """The source code of the python script."""

    type: Literal["python"]
    """The object type, which is always `python`."""

    image_tag: Optional[str] = None
    """The image tag to use for the python script."""
