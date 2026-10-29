"""Public resolution boundary for default and overridden LLM runtimes."""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import cast

from nanobot.agent import model_presets as preset_helpers
from nanobot.config.schema import Config, ModelPresetConfig
from nanobot.providers.factory import (
    ProviderSnapshot,
    build_isolated_provider_snapshot,
    build_provider_snapshot,
    provider_override_declarations,
    provider_signature,
    validate_provider_setup,
)
from nanobot.providers.request_overrides import isolate_request_overrides
from nanobot.providers.resources import ProviderResourcePool
from nanobot.utils.llm_runtime import LLMRuntime, runtime_from_provider_snapshot


def _override_key(value: object, active: set[int] | None = None) -> tuple[object, ...] | None:
    """Detach JSON-like identity without comparing application objects or mixing bool/int."""
    if value is None or type(value) in (str, bool, int):
        return (type(value), value)
    if type(value) is float:
        return (float, value) if math.isfinite(value) else None
    if type(value) not in (tuple, list, dict):
        return None
    active = active if active is not None else set()
    identity = id(value)
    if identity in active:
        return None
    active.add(identity)
    try:
        if isinstance(value, dict):
            mapping = cast(dict[object, object], value)
            if any(type(key) is not str for key in mapping):
                return None
            items: list[object] = []
            for name, item in mapping.items():
                key = _override_key(item, active)
                if key is None:
                    return None
                items.append((name, key))
            return (dict, tuple(items))
        items = []
        for item in cast(tuple[object, ...] | list[object], value):
            key = _override_key(item, active)
            if key is None:
                return None
            items.append(key)
        return (type(value), tuple(items))
    finally:
        active.remove(identity)


@dataclass(frozen=True, slots=True, repr=False)
class _RecentOverride:
    key: tuple[object, ...]
    runtime: LLMRuntime

    def borrow(self) -> LLMRuntime:
        return replace(self.runtime, snapshot_signature=deepcopy(self.runtime.snapshot_signature))


class ModelRuntimeResolver:
    """Own model selection and resolve it to immutable execution values.

    The resolver is deliberately independent of ``AgentLoop``.  Command, SDK,
    and tool admission layers can depend on this public service without reading
    or mutating private loop state.
    """

    def __init__(
        self,
        initial_runtime: LLMRuntime,
        *,
        owns_provider: bool = False,
        model_presets: Mapping[str, ModelPresetConfig] | None = None,
        preset_catalog_loader: preset_helpers.PresetCatalogLoader | None = None,
        configured_default_preset: str | None = None,
        provider_snapshot_loader: Callable[[], ProviderSnapshot] | None = None,
        preset_snapshot_loader: preset_helpers.PresetSnapshotLoader | None = None,
    ) -> None:
        self._resources = ProviderResourcePool()
        self._borrowed_provider = initial_runtime.provider if not owns_provider else None
        self._runtime = (
            replace(initial_runtime, resource=self._resources.register(initial_runtime.provider))
            if owns_provider else initial_runtime
        )
        self._model_presets = dict(model_presets or {})
        self._preset_catalog_loader = preset_catalog_loader
        self._preset_catalog_refresh_required = False
        self._provider_snapshot_loader = provider_snapshot_loader
        self._preset_snapshot_loader = preset_snapshot_loader
        self._refresh_required = False
        self._resolved_presets: dict[str, LLMRuntime] = {}
        self._recent_override: _RecentOverride | None = None
        self._tracks_provider_generation = initial_runtime.model_preset is None
        self._default_selection_signature = preset_helpers.default_selection_signature(
            initial_runtime.snapshot_signature,
            configured_default_preset,
        )
        self._retain_cached_resources()

    def _require_open(self) -> None:
        if self._resources.closed:
            raise RuntimeError("model runtime resolver is closed")

    def _cached_runtimes(self) -> list[LLMRuntime]:
        return [
            self._runtime,
            *self._resolved_presets.values(),
            *([self._recent_override.runtime] if self._recent_override is not None else []),
        ]

    def _retain_cached_resources(self) -> None:
        self._resources.retain(
            runtime.resource for runtime in self._cached_runtimes() if runtime.resource is not None
        )

    @property
    def runtime(self) -> LLMRuntime:
        """Return the current immutable default without refreshing configuration."""
        return self._runtime

    @property
    def model_presets(self) -> Mapping[str, ModelPresetConfig]:
        self._refresh_preset_catalog()
        return MappingProxyType({
            name: preset.model_copy(deep=True)
            for name, preset in self._model_presets.items()
        })

    @property
    def model_preset(self) -> str | None:
        return self._runtime.model_preset

    @property
    def provider_signature(self) -> tuple[object, ...] | None:
        return self._runtime.snapshot_signature

    def current(self, *, refresh: bool = False) -> LLMRuntime:
        """Return the selected runtime, optionally refreshing the default source."""
        if refresh:
            self.refresh()
            self._refresh_provider_generation()
        return self._runtime

    def admit(self) -> LLMRuntime:
        """Resolve the immutable runtime for the next turn admission."""
        self._require_open()
        if self._refresh_required:
            self.refresh()
        self._refresh_provider_generation()
        return self._runtime

    def invalidate(self) -> None:
        """Refresh configured runtime state on the next admission."""
        self._refresh_required = True
        self._preset_catalog_refresh_required = True

    def _refresh_preset_catalog(self) -> None:
        if not self._preset_catalog_refresh_required:
            return
        if self._preset_catalog_loader is not None:
            self._model_presets = dict(self._preset_catalog_loader())
        # Revalidate previously used entries while they still participate in reuse.
        # Unrequested changed/removed presets must not keep obsolete clients alive.
        refreshed: dict[str, LLMRuntime] = {}
        for name in self._resolved_presets:
            if name in self._model_presets:
                snapshot = preset_helpers.build_runtime_preset_snapshot(
                    name=name,
                    presets=self._model_presets,
                    provider=self._runtime.provider,
                    loader=self._preset_snapshot_loader,
                )
                refreshed[name] = self.resolve_snapshot(snapshot, reuse=self._resolved_presets[name])
        self._resolved_presets = refreshed
        self._preset_catalog_refresh_required = False
        self._retain_cached_resources()

    def resolve_snapshot(
        self,
        snapshot: ProviderSnapshot,
        *,
        reuse: LLMRuntime | None = None,
    ) -> LLMRuntime:
        """Take ownership of a snapshot and return a borrowed execution value.

        Acquire its lease before awaiting or handing it to queued work. A factory
        snapshot transfers ownership unless explicitly marked borrowed.
        """
        self._require_open()
        runtime = runtime_from_provider_snapshot(snapshot)
        resource = self._resources.get(snapshot.provider)
        if resource is None and snapshot.owns_provider and snapshot.provider is not self._borrowed_provider:
            resource = self._resources.register(snapshot.provider)
        runtime = replace(runtime, resource=resource)
        self._resources.collect()
        key = _override_key(snapshot.signature)
        if reuse is not None and key is not None and key == _override_key(reuse.snapshot_signature):
            # The loader may have constructed a redundant client. Preserve the
            # existing connection and retire the unused new resource. Override
            # reuse is handled separately, including its declaration restrictions.
            return replace(runtime, provider=reuse.provider, resource=reuse.resource)
        return runtime

    async def aclose(self) -> None:
        """Stop resource admissions and drain leases before closing owned providers."""
        self._resolved_presets.clear()
        self._recent_override = None
        await self._resources.aclose()

    def adopt_snapshot(
        self,
        snapshot: ProviderSnapshot,
    ) -> LLMRuntime:
        """Select a snapshot as the default for future turns."""
        runtime = self.resolve_snapshot(snapshot, reuse=self._runtime)
        self._runtime = runtime
        self._tracks_provider_generation = runtime.model_preset is None
        self._default_selection_signature = preset_helpers.default_selection_signature(
            runtime.snapshot_signature,
            runtime.model_preset,
        )
        self._retain_cached_resources()
        return runtime

    def resolve_preset(self, name: str | None) -> LLMRuntime:
        """Resolve a named preset without changing the selected default."""
        self._require_open()
        self._refresh_preset_catalog()
        normalized = preset_helpers.normalize_preset_name(name, self._model_presets)
        cached = self._resolved_presets.get(normalized)
        if cached is not None:
            return cached
        snapshot = preset_helpers.build_runtime_preset_snapshot(
            name=normalized,
            presets=self._model_presets,
            provider=self._runtime.provider,
            loader=self._preset_snapshot_loader,
        )
        runtime = self.resolve_snapshot(snapshot)
        self._resolved_presets[normalized] = runtime
        self._retain_cached_resources()
        return runtime

    def select_preset(self, name: str | None) -> LLMRuntime:
        """Select a named preset as the default for future turns."""
        runtime = self.resolve_preset(name)
        self._runtime = runtime
        self._tracks_provider_generation = False
        self._retain_cached_resources()
        return runtime

    def select_model(self, model: str) -> LLMRuntime:
        """Change the default model without reconstructing downstream consumers."""
        if not isinstance(cast(object, model), str) or not model.strip():
            raise ValueError("model must be a non-empty string")
        self._runtime = replace(
            self._runtime,
            model=model.strip(),
            model_preset=None,
        )
        return self._runtime

    def select_context_window(self, context_window_tokens: int) -> LLMRuntime:
        """Change the default context limit for future admissions."""
        raw_context_window = cast(object, context_window_tokens)
        if not isinstance(raw_context_window, int) or isinstance(
            raw_context_window,
            bool,
        ):
            raise TypeError("context_window_tokens must be an integer")
        self._runtime = replace(
            self._runtime,
            context_window_tokens=context_window_tokens,
        )
        return self._runtime

    def _refresh_provider_generation(self) -> LLMRuntime | None:
        """Adopt direct provider-default changes only for provider-backed defaults."""
        if not self._tracks_provider_generation:
            return None
        runtime = self._runtime
        captured = LLMRuntime.capture(
            runtime.provider,
            runtime.model,
            context_window_tokens=runtime.context_window_tokens,
            model_preset=runtime.model_preset,
            snapshot_signature=runtime.snapshot_signature,
        )
        if captured.generation == runtime.generation:
            return None
        self._runtime = replace(runtime, generation=captured.generation)
        return self._runtime

    def refresh(self) -> LLMRuntime | None:
        """Refresh configured defaults and return the replacement when changed."""
        self._require_open()
        self._refresh_preset_catalog()
        if self._provider_snapshot_loader is None:
            self._refresh_required = False
            return None

        snapshot = self._provider_snapshot_loader()
        # Register even a snapshot that is not selected (a session-selected preset
        # can remain the default). Its unused provider must still be disposed of.
        configured = self.resolve_snapshot(snapshot, reuse=self._runtime)
        default_selection = preset_helpers.default_selection_signature(
            snapshot.signature,
            snapshot.model_preset,
        )
        active_preset = self._runtime.model_preset
        if active_preset and self._default_selection_signature in (None, default_selection):
            runtime = self.resolve_preset(active_preset)
        else:
            runtime = configured

        unchanged = (
            runtime.snapshot_signature == self._runtime.snapshot_signature
            and runtime.model_preset == self._runtime.model_preset
        )
        self._refresh_required = False
        if unchanged:
            self._default_selection_signature = default_selection
            self._retain_cached_resources()
            return None
        (
            self._runtime,
            self._tracks_provider_generation,
            self._default_selection_signature,
        ) = (
            runtime,
            runtime.model_preset is None,
            default_selection,
        )
        self._retain_cached_resources()
        return runtime

    def resolve_override(
        self,
        *,
        model: str | None,
        model_preset: str | None,
        config: Config | None = None,
    ) -> LLMRuntime | None:
        """Resolve an SDK-style per-run override without mutating the default."""
        self._require_open()
        if model is not None and model_preset is not None:
            raise ValueError("model and model_preset are mutually exclusive")
        if model_preset is not None:
            return self.resolve_preset(model_preset)
        if model is None:
            return None
        if config is None:
            return replace(
                self._runtime,
                model=model,
                model_preset=None,
                snapshot_signature=("model_override", model),
            )

        base = config.resolve_preset(self.model_preset)
        preset = base.model_copy(update={"model": model, "provider": "auto"})
        preset = isolate_request_overrides(
            preset, previous_provider=config.get_provider_name(preset=base),
            provider=config.get_provider_name(preset=preset),
        )
        declarations = provider_override_declarations(config, preset=preset)
        key = _override_key((provider_signature(config, preset=preset), declarations))
        if key is None:
            runtime = self.resolve_snapshot(build_provider_snapshot(config, preset=preset))
            self._retain_cached_resources()
            return runtime
        if self._recent_override is not None and self._recent_override.key == key:
            # Equivalent wire settings can still contain an unsupported preset override.
            validate_provider_setup(config, preset=preset)
            return self._recent_override.borrow()

        snapshot = build_isolated_provider_snapshot(config, preset=preset)
        runtime = self.resolve_snapshot(snapshot)
        key = _override_key((snapshot.signature, declarations))
        if key is None:
            return runtime
        self._recent_override = _RecentOverride(key, runtime)
        self._retain_cached_resources()
        return self._recent_override.borrow()
