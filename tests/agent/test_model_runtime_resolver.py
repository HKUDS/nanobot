from dataclasses import FrozenInstanceError
from unittest.mock import MagicMock

import pytest

from nanobot.agent.model_runtime import ModelRuntimeResolver
from nanobot.config.schema import ModelPresetConfig
from nanobot.providers.base import GenerationSettings
from nanobot.providers.factory import ProviderSnapshot
from nanobot.utils.llm_runtime import LLMRuntime, runtime_from_provider_snapshot


def _provider(
    *,
    temperature: float = 0.1,
    max_tokens: int = 1024,
    reasoning_effort: str | None = None,
) -> MagicMock:
    provider = MagicMock()
    provider.generation = GenerationSettings(
        temperature=temperature,
        max_tokens=max_tokens,
        reasoning_effort=reasoning_effort,
    )
    return provider


def _runtime(provider: MagicMock | None = None) -> LLMRuntime:
    return LLMRuntime.capture(
        provider or _provider(),
        "base-model",
        context_window_tokens=10_000,
        snapshot_signature=("base-model", "auto"),
    )


def test_runtime_captures_generation_and_is_immutable() -> None:
    provider = _provider(temperature=0.2, max_tokens=2048, reasoning_effort="low")
    runtime = _runtime(provider)

    provider.generation = GenerationSettings(temperature=0.9, max_tokens=99)

    assert runtime.generation == GenerationSettings(0.2, 2048, "low")
    with pytest.raises(FrozenInstanceError):
        runtime.model = "changed"  # type: ignore[misc]


def test_provider_snapshot_has_one_canonical_runtime_conversion() -> None:
    provider = _provider(temperature=0.3, max_tokens=4096)
    snapshot = ProviderSnapshot(
        provider=provider,
        model="snapshot-model",
        context_window_tokens=32_768,
        signature=("snapshot-model", "openai"),
        model_preset="fast",
    )

    runtime = runtime_from_provider_snapshot(snapshot)

    assert runtime.provider is provider
    assert runtime.model == "snapshot-model"
    assert runtime.generation == GenerationSettings(0.3, 4096, None)
    assert runtime.context_window_tokens == 32_768
    assert runtime.model_preset == "fast"
    assert runtime.snapshot_signature == snapshot.signature


def test_resolver_resolves_preset_without_mutating_selected_runtime() -> None:
    initial = _runtime()
    preset_provider = _provider(temperature=0.5, max_tokens=512)
    preset = ModelPresetConfig(
        model="fast-model",
        temperature=0.5,
        max_tokens=512,
        context_window_tokens=8192,
    )
    resolver = ModelRuntimeResolver(
        initial,
        model_presets={"fast": preset},
        preset_snapshot_loader=lambda name: ProviderSnapshot(
            provider=preset_provider,
            model=preset.model,
            context_window_tokens=preset.context_window_tokens,
            signature=(name, preset.model),
        ),
    )

    resolved = resolver.resolve_preset("fast")

    assert resolved.model == "fast-model"
    assert resolved.model_preset == "fast"
    assert resolver.runtime is initial
    assert resolver.model_preset is None
    assert initial.provider.generation == GenerationSettings(0.1, 1024, None)
    assert resolved.generation == GenerationSettings(0.5, 512, None)


def test_resolver_reuses_preset_until_runtime_config_is_invalidated() -> None:
    initial = _runtime()
    preset = ModelPresetConfig(model="fast-model")
    load_count = 0
    preset_signature = ("fast-model", "auto", "initial")

    def load_preset(_name: str) -> ProviderSnapshot:
        nonlocal load_count
        load_count += 1
        return ProviderSnapshot(
            provider=_provider(),
            model="fast-model",
            context_window_tokens=20_000,
            signature=preset_signature,
        )

    resolver = ModelRuntimeResolver(
        initial,
        model_presets={"fast": preset},
        preset_snapshot_loader=load_preset,
    )

    first = resolver.resolve_preset("fast")
    second = resolver.resolve_preset("fast")

    assert first is second
    assert load_count == 1

    preset_signature = ("fast-model", "auto", "new-credential")
    resolver.invalidate()
    refreshed = resolver.resolve_preset("fast")

    assert refreshed is not first
    assert load_count == 2


def test_resolver_refreshes_preset_catalog_after_invalidation() -> None:
    provider = _provider()
    catalog = {
        "old": ModelPresetConfig(model="old-model", provider="openai"),
    }
    default_name = "old"

    def load_preset(name: str) -> ProviderSnapshot:
        preset = catalog[name]
        return ProviderSnapshot(
            provider=provider,
            model=preset.model,
            context_window_tokens=preset.context_window_tokens,
            signature=(preset.model, preset.provider),
            model_preset=name,
        )

    resolver = ModelRuntimeResolver(
        runtime_from_provider_snapshot(load_preset("old")),
        model_presets=catalog,
        preset_catalog_loader=lambda: catalog,
        configured_default_preset="old",
        provider_snapshot_loader=lambda: load_preset(default_name),
        preset_snapshot_loader=load_preset,
    )

    catalog["new"] = ModelPresetConfig(model="new-model", provider="openai")
    default_name = "new"
    resolver.invalidate()

    assert resolver.admit().model_preset == "new"
    assert set(resolver.model_presets) == {"old", "new"}

    del catalog["old"]
    resolver.invalidate()

    assert resolver.admit().model_preset == "new"
    assert set(resolver.model_presets) == {"new"}


def test_resolver_model_presets_are_read_only() -> None:
    resolver = ModelRuntimeResolver(
        _runtime(),
        model_presets={"fast": ModelPresetConfig(model="fast-model")},
    )

    exposed = resolver.model_presets
    with pytest.raises(TypeError):
        exposed["other"] = ModelPresetConfig(  # type: ignore[index]
            model="other-model"
        )

    exposed["fast"].model = "mutated-model"

    assert set(resolver.model_presets) == {"fast"}
    assert resolver.model_presets["fast"].model == "fast-model"
    assert resolver.resolve_preset("fast").model == "fast-model"


def test_resolver_model_override_is_derived_without_default_mutation() -> None:
    initial = _runtime()
    resolver = ModelRuntimeResolver(initial)

    override = resolver.resolve_override(
        model="override-model",
        model_preset=None,
    )

    assert override is not None
    assert override.model == "override-model"
    assert override.provider is initial.provider
    assert override.generation is initial.generation
    assert resolver.runtime is initial


def test_resolver_refresh_preserves_unchanged_active_preset() -> None:
    initial = _runtime()
    preset = ModelPresetConfig(model="fast-model")
    preset_provider = _provider()
    resolver = ModelRuntimeResolver(
        initial,
        model_presets={"fast": preset},
        provider_snapshot_loader=lambda: ProviderSnapshot(
            provider=_provider(),
            model="base-model",
            context_window_tokens=10_000,
            signature=("base-model", "auto", "refreshed"),
        ),
        preset_snapshot_loader=lambda _name: ProviderSnapshot(
            provider=preset_provider,
            model="fast-model",
            context_window_tokens=20_000,
            signature=("fast-model", "auto", "refreshed"),
        ),
    )
    resolver.select_preset("fast")

    refreshed = resolver.refresh()

    assert refreshed is None
    assert resolver.runtime.provider is preset_provider
    assert resolver.model_preset == "fast"


def test_refresh_clears_preset_when_new_default_has_same_snapshot_signature() -> None:
    initial = _runtime()
    preset_provider = _provider()
    preset_snapshot = ProviderSnapshot(
        provider=preset_provider,
        model="fast-model",
        context_window_tokens=20_000,
        signature=("fast-model", "auto", "same-runtime"),
    )
    default_snapshot = ProviderSnapshot(
        provider=preset_provider,
        model="fast-model",
        context_window_tokens=20_000,
        signature=preset_snapshot.signature,
    )
    resolver = ModelRuntimeResolver(
        initial,
        model_presets={"fast": ModelPresetConfig(model="fast-model")},
        provider_snapshot_loader=lambda: default_snapshot,
        preset_snapshot_loader=lambda _name: preset_snapshot,
    )
    resolver.select_preset("fast")

    refreshed = resolver.refresh()

    assert refreshed is resolver.runtime
    assert refreshed is not None
    assert resolver.model_preset is None
    assert resolver.runtime.model_preset is None
    assert "_active_preset" not in resolver.__dict__


def test_resolver_refreshes_provider_generation_for_next_default_turn() -> None:
    provider = _provider(temperature=0.2, max_tokens=2048)
    resolver = ModelRuntimeResolver(_runtime(provider))
    admitted = resolver.current()

    provider.generation = GenerationSettings(temperature=0.8, max_tokens=512)
    refreshed = resolver.admit()

    assert admitted.generation == GenerationSettings(0.2, 2048, None)
    assert refreshed.generation == GenerationSettings(0.8, 512, None)


def test_resolver_admission_reloads_config_only_after_invalidation() -> None:
    initial = _runtime()
    refreshed_provider = _provider()
    load_count = 0

    def load_snapshot() -> ProviderSnapshot:
        nonlocal load_count
        load_count += 1
        return ProviderSnapshot(
            provider=refreshed_provider,
            model="refreshed-model",
            context_window_tokens=20_000,
            signature=("refreshed-model", "auto"),
        )

    resolver = ModelRuntimeResolver(initial, provider_snapshot_loader=load_snapshot)

    assert resolver.admit() is initial
    assert load_count == 0

    resolver.invalidate()
    refreshed = resolver.admit()

    assert refreshed.provider is refreshed_provider
    assert refreshed.model == "refreshed-model"
    assert resolver.admit() is refreshed
    assert load_count == 1


def test_current_refresh_forces_config_reload() -> None:
    initial = _runtime()
    load_snapshot = MagicMock(
        return_value=ProviderSnapshot(
            provider=_provider(),
            model="refreshed-model",
            context_window_tokens=20_000,
            signature=("refreshed-model", "auto"),
        )
    )
    resolver = ModelRuntimeResolver(initial, provider_snapshot_loader=load_snapshot)

    refreshed = resolver.current(refresh=True)

    assert refreshed.model == "refreshed-model"
    load_snapshot.assert_called_once_with()


def test_selected_preset_generation_does_not_fall_back_to_provider_defaults() -> None:
    provider = _provider(temperature=0.1, max_tokens=1024)
    resolver = ModelRuntimeResolver(
        _runtime(provider),
        model_presets={
            "creative": ModelPresetConfig(
                model="creative-model",
                temperature=0.7,
                max_tokens=4096,
            )
        },
    )
    selected = resolver.select_preset("creative")

    provider.generation = GenerationSettings(temperature=0.9, max_tokens=64)
    refreshed = resolver.admit()

    assert refreshed is selected
    assert refreshed.generation == GenerationSettings(0.7, 4096, None)


def test_resolver_mutates_only_its_default_selection() -> None:
    initial = _runtime()
    resolver = ModelRuntimeResolver(initial)

    selected_model = resolver.select_model("next-model")
    selected_window = resolver.select_context_window(65_536)

    assert selected_model.model == "next-model"
    assert selected_window.model == "next-model"
    assert selected_window.context_window_tokens == 65_536
    assert resolver.runtime is selected_window
    assert resolver.model_preset is None
    assert initial.model == "base-model"
    assert initial.context_window_tokens == 10_000
