"""Public resolution boundary for default and overridden LLM runtimes."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import replace

from nanobot.agent import model_presets as preset_helpers
from nanobot.config.schema import Config, ModelPresetConfig
from nanobot.providers.factory import ProviderSnapshot, build_provider_snapshot
from nanobot.utils.llm_runtime import LLMRuntime, runtime_from_provider_snapshot


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
        model_presets: Mapping[str, ModelPresetConfig] | None = None,
        provider_snapshot_loader: Callable[[], ProviderSnapshot] | None = None,
        preset_snapshot_loader: preset_helpers.PresetSnapshotLoader | None = None,
    ) -> None:
        self._runtime = initial_runtime
        self._model_presets = dict(model_presets or {})
        self._provider_snapshot_loader = provider_snapshot_loader
        self._preset_snapshot_loader = preset_snapshot_loader
        self._active_preset = initial_runtime.model_preset
        self._tracks_provider_generation = initial_runtime.model_preset is None
        self._default_selection_signature = preset_helpers.default_selection_signature(
            initial_runtime.snapshot_signature
        )

    @property
    def runtime(self) -> LLMRuntime:
        """Return the current immutable default without refreshing configuration."""
        return self._runtime

    @property
    def model_presets(self) -> Mapping[str, ModelPresetConfig]:
        return self._model_presets

    @property
    def model_preset(self) -> str | None:
        return self._active_preset

    @property
    def provider_signature(self) -> tuple[object, ...] | None:
        return self._runtime.snapshot_signature

    def current(self, *, refresh: bool = False) -> LLMRuntime:
        """Return the selected runtime, optionally refreshing the default source."""
        if refresh:
            self.refresh()
            self._refresh_provider_generation()
        return self._runtime

    def resolve_snapshot(
        self,
        snapshot: ProviderSnapshot,
        *,
        model_preset: str | None = None,
    ) -> LLMRuntime:
        """Resolve a factory snapshot without changing the selected default."""
        return runtime_from_provider_snapshot(snapshot, model_preset=model_preset)

    def adopt_snapshot(
        self,
        snapshot: ProviderSnapshot,
        *,
        model_preset: str | None = None,
    ) -> LLMRuntime:
        """Select a snapshot as the default for future turns."""
        runtime = self.resolve_snapshot(snapshot, model_preset=model_preset)
        self._runtime = runtime
        self._active_preset = model_preset
        self._tracks_provider_generation = model_preset is None
        self._default_selection_signature = preset_helpers.default_selection_signature(
            runtime.snapshot_signature
        )
        return runtime

    def resolve_preset(self, name: str | None) -> LLMRuntime:
        """Resolve a named preset without changing the selected default."""
        normalized = preset_helpers.normalize_preset_name(name, self._model_presets)
        snapshot = preset_helpers.build_runtime_preset_snapshot(
            name=normalized,
            presets=self._model_presets,
            provider=self._runtime.provider,
            loader=self._preset_snapshot_loader,
        )
        return self.resolve_snapshot(snapshot, model_preset=normalized)

    def select_preset(self, name: str | None) -> LLMRuntime:
        """Select a named preset as the default for future turns."""
        runtime = self.resolve_preset(name)
        self._runtime = runtime
        self._active_preset = runtime.model_preset
        self._tracks_provider_generation = False
        return runtime

    def select_model(self, model: str) -> LLMRuntime:
        """Change the default model without reconstructing downstream consumers."""
        if not isinstance(model, str) or not model.strip():
            raise ValueError("model must be a non-empty string")
        self._runtime = replace(
            self._runtime,
            model=model.strip(),
            model_preset=None,
        )
        self._active_preset = None
        return self._runtime

    def select_context_window(self, context_window_tokens: int) -> LLMRuntime:
        """Change the default context limit for future admissions."""
        if not isinstance(context_window_tokens, int) or isinstance(
            context_window_tokens,
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
        if self._provider_snapshot_loader is None:
            return None

        snapshot = self._provider_snapshot_loader()
        default_selection = preset_helpers.default_selection_signature(snapshot.signature)
        active_preset = self._active_preset
        if active_preset and self._default_selection_signature in (None, default_selection):
            self._default_selection_signature = default_selection
            runtime = self.resolve_preset(active_preset)
        else:
            active_preset = None
            self._active_preset = None
            self._default_selection_signature = default_selection
            runtime = self.resolve_snapshot(snapshot)

        if runtime.snapshot_signature == self._runtime.snapshot_signature:
            return None
        self._runtime = runtime
        self._active_preset = active_preset
        self._tracks_provider_generation = active_preset is None
        self._default_selection_signature = preset_helpers.default_selection_signature(
            runtime.snapshot_signature
        )
        return runtime

    def resolve_override(
        self,
        *,
        model: str | None,
        model_preset: str | None,
        config: Config | None = None,
    ) -> LLMRuntime | None:
        """Resolve an SDK-style per-run override without mutating the default."""
        if model is not None and model_preset is not None:
            raise ValueError("model and model_preset are mutually exclusive")
        if model_preset is not None:
            return self.resolve_preset(model_preset)
        if model is None:
            return None
        if config is None:
            return LLMRuntime(
                provider=self._runtime.provider,
                model=model,
                generation=self._runtime.generation,
                context_window_tokens=self._runtime.context_window_tokens,
                snapshot_signature=("model_override", model),
            )

        base = config.resolve_preset(self._active_preset)
        preset = base.model_copy(update={"model": model, "provider": "auto"})
        return self.resolve_snapshot(build_provider_snapshot(config, preset=preset))
