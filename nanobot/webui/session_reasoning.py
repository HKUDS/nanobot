"""Preset reasoning recommendations and session-owned next-turn overrides."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from pathlib import Path
from typing import TypedDict, cast

import httpx

from nanobot.config.loader import load_config, resolve_config_env_vars
from nanobot.config.schema import Config, ModelPresetConfig
from nanobot.providers.factory import provider_signature
from nanobot.session.manager import SessionManager
from nanobot.session.model_selection import (
    SESSION_REASONING_EFFORT_METADATA_KEY,
    model_preset_from_metadata,
    reasoning_effort_for_snapshot,
    reasoning_effort_scope,
)
from nanobot.session.sqlite_store import SessionConflictError
from nanobot.webui.session_identity import is_valid_webui_chat_id, webui_chat_id
from nanobot.webui.settings_models import provider_models_payload, reasoning_effort_values_for


class ReasoningEffortPayload(TypedDict):
    preset: str
    scope: str
    options: list[str]
    value: str | None
    preset_value: str | None


class SessionReasoningError(ValueError):
    def __init__(self, message: str, *, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


def _catalog_efforts(payload: Mapping[str, object], model: str) -> list[str] | None:
    rows = payload.get("models")
    if not isinstance(rows, list):
        return None
    for value in cast(list[object], rows):
        if not isinstance(value, dict):
            continue
        row = cast(dict[str, object], value)
        if row.get("id") != model:
            continue
        levels = row.get("reasoning_efforts")
        if isinstance(levels, list) and all(isinstance(level, str) for level in cast(list[object], levels)):
            return cast(list[str], levels)
        return None
    return None


def reasoning_effort_options(config: Config, preset: ModelPresetConfig) -> list[str]:
    """Match the preset picker: catalog values first, then preset recommendations."""
    provider = config.get_provider_name(preset.model, preset=preset) or preset.provider
    catalog = provider_models_payload(config, {"provider": [provider]}, http_get=httpx.get)
    efforts = _catalog_efforts(catalog, preset.model)
    if efforts is None:
        efforts = reasoning_effort_values_for(provider, preset.model)
    return list(dict.fromkeys(effort for effort in efforts if effort))


def _session_key(value: object) -> str:
    if not isinstance(value, str) or not is_valid_webui_chat_id(webui_chat_id(value)):
        raise SessionReasoningError("session not found", status=404)
    return value


def _selected_preset(config: Config, metadata: Mapping[str, object]) -> str:
    return model_preset_from_metadata(metadata) or config.agents.defaults.model_preset or "default"


class WebUISessionReasoning:
    def __init__(self, config_path: Path, sessions: SessionManager) -> None:
        self._config_path = config_path
        self._sessions = sessions.state

    def _config(self) -> Config:
        # Atomic config-file replacement supplies a coherent read. Do not take
        # the settings mutation lock inside a session transaction: preset rename
        # operations acquire those owners in the opposite order.
        return resolve_config_env_vars(load_config(self._config_path), config_path=self._config_path)

    def _snapshot(self, name: str) -> tuple[Config, ModelPresetConfig, tuple[object, ...]]:
        config = self._config()
        try:
            preset = config.resolve_preset(name)
        except KeyError:
            raise SessionReasoningError("model preset is no longer available", status=409) from None
        return config, preset, provider_signature(config, preset=preset)

    @staticmethod
    def _payload(
        name: str, preset: ModelPresetConfig, signature: tuple[object, ...],
        options: list[str], metadata: Mapping[str, object],
    ) -> ReasoningEffortPayload:
        value = reasoning_effort_for_snapshot(metadata, preset=name, signature=signature)
        return {
            "preset": name, "scope": reasoning_effort_scope(signature), "options": options,
            "value": value, "preset_value": preset.reasoning_effort,
        }

    async def get(self, name: str, session_key: str | None) -> ReasoningEffortPayload:
        if not name:
            raise SessionReasoningError("model_preset is required")
        key = _session_key(session_key) if session_key is not None else None
        session = await self._sessions.read_header(key) if key is not None else None
        config, preset, signature = await asyncio.to_thread(self._snapshot, name)
        metadata = session.metadata if session is not None else {}
        if key is not None and _selected_preset(config, metadata) != name:
            raise SessionReasoningError("session model preset changed", status=409)
        options = await asyncio.to_thread(reasoning_effort_options, config, preset)
        latest, _, latest_signature = await asyncio.to_thread(self._snapshot, name)
        if latest_signature != signature:
            raise SessionReasoningError("model preset changed; reload reasoning effort", status=409)
        if key is not None:
            fresh = await self._sessions.read_header(key)
            if ((fresh.generation if fresh else None) != (session.generation if session else None)
                    or _selected_preset(latest, fresh.metadata if fresh else {}) != name):
                raise SessionReasoningError("session model preset changed", status=409)
            metadata = fresh.metadata if fresh else {}
        return self._payload(name, preset, signature, options, metadata)

    async def update(self, payload: Mapping[str, object]) -> ReasoningEffortPayload:
        key = _session_key(payload.get("session_key"))
        name, scope, value = payload.get("preset"), payload.get("scope"), payload.get("value")
        if not isinstance(name, str) or not name or not isinstance(scope, str) or not scope:
            raise SessionReasoningError("preset and scope are required")
        if "value" not in payload or (value is not None and not isinstance(value, str)):
            raise SessionReasoningError("value must be a reasoning effort or null")
        session = await self._sessions.read_header(key)
        config, preset, signature = await asyncio.to_thread(self._snapshot, name)
        if scope != reasoning_effort_scope(signature):
            raise SessionReasoningError("model preset changed; reload reasoning effort", status=409)
        if _selected_preset(config, session.metadata if session else {}) != name:
            raise SessionReasoningError("session model preset changed", status=409)
        options = await asyncio.to_thread(reasoning_effort_options, config, preset)
        if value is not None and value not in options:
            raise SessionReasoningError("unsupported reasoning effort")

        def change(metadata: dict[str, object]) -> None:
            latest, _, latest_signature = self._snapshot(name)
            if scope != reasoning_effort_scope(latest_signature):
                raise SessionReasoningError("model preset changed; reload reasoning effort", status=409)
            if _selected_preset(latest, metadata) != name:
                raise SessionReasoningError("session model preset changed", status=409)
            if value is None:
                metadata.pop(SESSION_REASONING_EFFORT_METADATA_KEY, None)
            else:
                metadata[SESSION_REASONING_EFFORT_METADATA_KEY] = {
                    "preset": name, "scope": scope, "value": value,
                }

        try:
            _, metadata = await self._sessions.mutate_metadata(
                key, change, expected_generation=session.generation if session else None,
                create_if_missing=True,
            )
        except SessionConflictError:
            raise SessionReasoningError("session changed; reload reasoning effort", status=409) from None
        return self._payload(name, preset, signature, options, metadata)
