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
    )

    runtime = runtime_from_provider_snapshot(snapshot, model_preset="fast")

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
    refreshed = resolver.current(refresh=True)

    assert admitted.generation == GenerationSettings(0.2, 2048, None)
    assert refreshed.generation == GenerationSettings(0.8, 512, None)


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
    refreshed = resolver.current(refresh=True)

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
