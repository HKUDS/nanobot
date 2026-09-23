"""Session-scoped model preset metadata."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

# Session.metadata is public SDK data, so internal selectors use a reserved namespace.
SESSION_MODEL_PRESET_METADATA_KEY = "_nanobot_model_preset"


def model_preset_from_metadata(metadata: object) -> str | None:
    """Read the canonical session preset name from persisted metadata."""
    if not isinstance(metadata, Mapping):
        return None
    typed_metadata = cast(Mapping[object, object], metadata)
    if SESSION_MODEL_PRESET_METADATA_KEY not in typed_metadata:
        return None
    value = typed_metadata[SESSION_MODEL_PRESET_METADATA_KEY]
    if not isinstance(value, str) or not value.strip():
        raise ValueError("session model preset must be a non-empty string")
    return value.strip()


class SessionInitializationConflictError(ValueError):
    """A session initialization disagrees with an identity that already exists."""

    def __init__(self, session_key: str, requested_preset: str) -> None:
        super().__init__(
            f"session {session_key!r} already exists with a different model preset; "
            f"cannot initialize it as {requested_preset!r}"
        )
