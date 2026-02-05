# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from __future__ import annotations

from typing_extensions import Literal, Required, TypedDict

from .file_purpose import FilePurpose

__all__ = ["UploadCreateParams", "ExpiresAfter"]


class UploadCreateParams(TypedDict, total=False):
    bytes: Required[int]
    """The number of bytes in the file you are uploading."""

    filename: Required[str]
    """The name of the file to upload."""

    mime_type: Required[str]
    """The MIME type of the file.

    This must fall within the supported MIME types for your file purpose. See the
    supported MIME types for assistants and vision.
    """

    purpose: Required[FilePurpose]
    """The intended purpose of the uploaded file.

    See the
    [documentation on File purposes](https://platform.openai.com/docs/api-reference/files/create#files-create-purpose).
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
