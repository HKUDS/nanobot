# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from typing import List, Union
from typing_extensions import Literal, Annotated, TypeAlias

from ...._utils import PropertyInfo
from ...._models import BaseModel

__all__ = [
    "ChatKitResponseOutputText",
    "Annotation",
    "AnnotationFile",
    "AnnotationFileSource",
    "AnnotationURL",
    "AnnotationURLSource",
]


class AnnotationFileSource(BaseModel):
    """File attachment referenced by the annotation."""

    filename: str
    """Filename referenced by the annotation."""

    type: Literal["file"]
    """Type discriminator that is always `file`."""


class AnnotationFile(BaseModel):
    """Annotation that references an uploaded file."""

    source: AnnotationFileSource
    """File attachment referenced by the annotation."""

    type: Literal["file"]
    """Type discriminator that is always `file` for this annotation."""


class AnnotationURLSource(BaseModel):
    """URL referenced by the annotation."""

    type: Literal["url"]
    """Type discriminator that is always `url`."""

    url: str
    """URL referenced by the annotation."""


class AnnotationURL(BaseModel):
    """Annotation that references a URL."""

    source: AnnotationURLSource
    """URL referenced by the annotation."""

    type: Literal["url"]
    """Type discriminator that is always `url` for this annotation."""


Annotation: TypeAlias = Annotated[Union[AnnotationFile, AnnotationURL], PropertyInfo(discriminator="type")]


class ChatKitResponseOutputText(BaseModel):
    """Assistant response text accompanied by optional annotations."""

    annotations: List[Annotation]
    """Ordered list of annotations attached to the response text."""

    text: str
    """Assistant generated text."""

    type: Literal["output_text"]
    """Type discriminator that is always `output_text`."""
