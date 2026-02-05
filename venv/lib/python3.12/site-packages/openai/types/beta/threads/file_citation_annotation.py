# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from typing_extensions import Literal

from ...._models import BaseModel

__all__ = ["FileCitationAnnotation", "FileCitation"]


class FileCitation(BaseModel):
    file_id: str
    """The ID of the specific File the citation is from."""


class FileCitationAnnotation(BaseModel):
    """
    A citation within the message that points to a specific quote from a specific File associated with the assistant or the message. Generated when the assistant uses the "file_search" tool to search files.
    """

    end_index: int

    file_citation: FileCitation

    start_index: int

    text: str
    """The text in the message content that needs to be replaced."""

    type: Literal["file_citation"]
    """Always `file_citation`."""
