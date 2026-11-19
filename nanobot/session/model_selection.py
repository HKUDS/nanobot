from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast

from nanobot.providers.model_options import ModelOptions

# Session.metadata is public SDK data, so internal selectors use a reserved namespace.
SESSION_LOCAL_PRESET_KEY = "_nanobot_session_preset"
SESSION_MODEL_PRESET_METADATA_KEY = "_nanobot_model_preset"
SESSION_MODEL_OPTIONS_METADATA_KEY = "_nanobot_model_options"
LEGACY_MODEL_KEYS = (SESSION_MODEL_PRESET_METADATA_KEY, SESSION_MODEL_OPTIONS_METADATA_KEY)
SESSION_MODEL_KEYS = (SESSION_LOCAL_PRESET_KEY, *LEGACY_MODEL_KEYS)


def _parse_name(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("session model preset must be a non-empty string")
    return value.strip()


@dataclass(frozen=True, slots=True)
class SessionModelPreset:
    """A shared preset reference and the session's explicit differences."""

    base_preset: str | None = None
    overrides: ModelOptions = ModelOptions()

    def metadata_update(self) -> dict[str, object]:
        if self == SessionModelPreset():
            return {}
        return {SESSION_LOCAL_PRESET_KEY: {
            "base_preset": self.base_preset,
            "overrides": {key: value for key, value in self.overrides.to_dict().items() if value is not None},
        }}

    @classmethod
    def from_metadata(cls, metadata: object) -> SessionModelPreset:
        if not isinstance(metadata, Mapping):
            return cls()
        data = cast(Mapping[object, object], metadata)
        if SESSION_LOCAL_PRESET_KEY in data:
            record = data[SESSION_LOCAL_PRESET_KEY]
            if not isinstance(record, Mapping):
                raise ValueError("session preset must be an object")
            fields = cast(Mapping[object, object], record)
            name = fields.get("base_preset")
            return cls(_parse_name(name) if name is not None else None, ModelOptions.parse(fields.get("overrides", {})))
        # Upgrade the old split record on the next write, without losing saved choices.
        name = _parse_name(data[SESSION_MODEL_PRESET_METADATA_KEY]) if SESSION_MODEL_PRESET_METADATA_KEY in data else None
        return cls(name, ModelOptions.parse(data.get(SESSION_MODEL_OPTIONS_METADATA_KEY, {})))
