# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from __future__ import annotations

from typing_extensions import TypedDict

__all__ = ["ChatSessionChatKitConfigurationParam", "AutomaticThreadTitling", "FileUpload", "History"]


class AutomaticThreadTitling(TypedDict, total=False):
    """Configuration for automatic thread titling.

    When omitted, automatic thread titling is enabled by default.
    """

    enabled: bool
    """Enable automatic thread title generation. Defaults to true."""


class FileUpload(TypedDict, total=False):
    """Configuration for upload enablement and limits.

    When omitted, uploads are disabled by default (max_files 10, max_file_size 512 MB).
    """

    enabled: bool
    """Enable uploads for this session. Defaults to false."""

    max_file_size: int
    """Maximum size in megabytes for each uploaded file.

    Defaults to 512 MB, which is the maximum allowable size.
    """

    max_files: int
    """Maximum number of files that can be uploaded to the session. Defaults to 10."""


class History(TypedDict, total=False):
    """Configuration for chat history retention.

    When omitted, history is enabled by default with no limit on recent_threads (null).
    """

    enabled: bool
    """Enables chat users to access previous ChatKit threads. Defaults to true."""

    recent_threads: int
    """Number of recent ChatKit threads users have access to.

    Defaults to unlimited when unset.
    """


class ChatSessionChatKitConfigurationParam(TypedDict, total=False):
    """Optional per-session configuration settings for ChatKit behavior."""

    automatic_thread_titling: AutomaticThreadTitling
    """Configuration for automatic thread titling.

    When omitted, automatic thread titling is enabled by default.
    """

    file_upload: FileUpload
    """Configuration for upload enablement and limits.

    When omitted, uploads are disabled by default (max_files 10, max_file_size 512
    MB).
    """

    history: History
    """Configuration for chat history retention.

    When omitted, history is enabled by default with no limit on recent_threads
    (null).
    """
