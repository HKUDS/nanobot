# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from __future__ import annotations

from typing_extensions import Literal, Required, TypedDict

from .._types import FileTypes
from .file_purpose import FilePurpose

__all__ = ["FileCreateParams", "ExpiresAfter"]


class FileCreateParams(TypedDict, total=False):
    file: Required[FileTypes]
    """The File object (not file name) to be uploaded."""

    purpose: Required[FilePurpose]
    """The intended purpose of the uploaded file. One of:

    - `assistants`: Used in the Assistants API
    - `batch`: Used in the Batch API
    - `fine-tune`: Used for fine-tuning
    - `vision`: Images used for vision fine-tuning
    - `user_data`: Flexible file type for any purpose
    - `evals`: Used for eval data sets
    """

    expires_after: ExpiresAfter
    """The expiration policy for a file.

    By default, files with `purpose=batch` expire after 30 days and all other files
    are persisted until they are manually deleted.
    """


class ExpiresAfter(TypedDict, total=False):
    """The expiration policy for a file.

    By default, files with `purpose=batch` expire after 30 days and all other files are persisted until they are manually deleted.
    """

    anchor: Required[Literal["created_at"]]
    """Anchor timestamp after which the expiration policy applies.

    Supported anchors: `created_at`.
    """

    seconds: Required[int]
    """The number of seconds after the anchor time that the file will expire.

    Must be between 3600 (1 hour) and 2592000 (30 days).
    """
