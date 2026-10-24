"""Session-scoped model preset metadata."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
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


SESSION_REASONING_EFFORT_METADATA_KEY = "_nanobot_reasoning_effort"


@dataclass(frozen=True, slots=True)
class SessionReasoningEffort:
    preset: str
    scope: str
    value: str


def reasoning_effort_scope(signature: tuple[object, ...]) -> str:
    """Bind an override to a provider snapshot without persisting its secrets."""
    encoded = json.dumps(signature, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def reasoning_effort_from_metadata(metadata: Mapping[str, object]) -> SessionReasoningEffort | None:
    """Parse the reserved selector at the persisted/SDK metadata boundary."""
    raw = metadata.get(SESSION_REASONING_EFFORT_METADATA_KEY)
    if raw is None:
        return None
    if isinstance(raw, Mapping):
        record = cast(Mapping[object, object], raw)
        preset, scope, value = record.get("preset"), record.get("scope"), record.get("value")
        if (isinstance(preset, str) and preset and isinstance(scope, str)
                and len(scope) == 64 and all(char in "0123456789abcdef" for char in scope)
                and isinstance(value, str) and value.strip() == value and value):
            return SessionReasoningEffort(preset=preset, scope=scope, value=value)
    raise ValueError("invalid session reasoning effort metadata")


def reasoning_effort_for_snapshot(
    metadata: Mapping[str, object],
    *,
    preset: str | None,
    signature: tuple[object, ...] | None,
) -> str | None:
    """Ignore selectors for a different preset or a changed runtime snapshot."""
    selection = reasoning_effort_from_metadata(metadata)
    if (selection is None or signature is None or selection.preset != (preset or "default")
            or selection.scope != reasoning_effort_scope(signature)):
        return None
    return selection.value
