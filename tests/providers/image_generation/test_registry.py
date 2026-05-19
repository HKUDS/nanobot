from __future__ import annotations

from types import SimpleNamespace

import pytest

from nanobot.providers.image_generation import (
    AIHubMixImageGenerationClient,
    GeminiImageGenerationClient,
    ImageGenerationProvider,
    MiniMaxImageGenerationClient,
    OpenRouterImageGenerationClient,
    get_image_gen_provider,
    image_gen_provider_configs,
    image_gen_provider_names,
    register_image_gen_provider,
)


def test_discover_builtin_providers_includes_all_four() -> None:
    assert get_image_gen_provider("openrouter") is OpenRouterImageGenerationClient
    assert get_image_gen_provider("aihubmix") is AIHubMixImageGenerationClient
    assert get_image_gen_provider("gemini") is GeminiImageGenerationClient
    assert get_image_gen_provider("minimax") is MiniMaxImageGenerationClient


def test_get_unknown_provider_returns_none() -> None:
    assert get_image_gen_provider("does-not-exist") is None


def test_image_gen_provider_names_returns_tuple_of_builtins() -> None:
    names = image_gen_provider_names()
    assert isinstance(names, tuple)
    assert {"openrouter", "aihubmix", "gemini", "minimax"} <= set(names)


def test_register_image_gen_provider_adds_external() -> None:
    class _StubProvider(ImageGenerationProvider):
        provider_name = "stub-test-only"

        async def generate(
            self,
            *,
            prompt: str,
            model: str,
            reference_images: list[str] | None = None,
            aspect_ratio: str | None = None,
            image_size: str | None = None,
        ):  # pragma: no cover - test stub
            raise NotImplementedError

    try:
        register_image_gen_provider(_StubProvider)
        assert get_image_gen_provider("stub-test-only") is _StubProvider
    finally:
        # Defensive cleanup so we don't leak state into other tests.
        from nanobot.providers.image_generation import registry as _registry

        _registry._ensure_providers().pop("stub-test-only", None)


def test_register_requires_provider_name() -> None:
    class _Nameless(ImageGenerationProvider):
        provider_name = ""

        async def generate(
            self,
            *,
            prompt: str,
            model: str,
            reference_images: list[str] | None = None,
            aspect_ratio: str | None = None,
            image_size: str | None = None,
        ):  # pragma: no cover - test stub
            raise NotImplementedError

    with pytest.raises(ValueError, match="provider_name"):
        register_image_gen_provider(_Nameless)


def test_image_gen_provider_configs_returns_only_registered_providers() -> None:
    providers_cfg = SimpleNamespace(
        openrouter="open-router-config",
        aihubmix="aihubmix-config",
        gemini="gemini-config",
        minimax="minimax-config",
        # Other LLM provider configs that aren't image gen — must be ignored.
        anthropic="anthropic-config",
        openai="openai-config",
    )
    config = SimpleNamespace(providers=providers_cfg)

    result = image_gen_provider_configs(config)

    assert set(result.keys()) == {"openrouter", "aihubmix", "gemini", "minimax"}
    assert result["openrouter"] == "open-router-config"
    assert result["minimax"] == "minimax-config"


def test_image_gen_provider_configs_skips_missing_fields() -> None:
    providers_cfg = SimpleNamespace(openrouter="only-this-one")
    config = SimpleNamespace(providers=providers_cfg)

    result = image_gen_provider_configs(config)

    assert "openrouter" in result
    assert "aihubmix" not in result
    assert "gemini" not in result
    assert "minimax" not in result


def test_every_discovered_provider_is_reexported_by_package() -> None:
    """Catch the 'added a new provider module but forgot __init__.py' bug."""
    from nanobot.providers import image_generation as pkg
    from nanobot.providers.image_generation.registry import _discover_builtin

    for provider_name, cls in _discover_builtin().items():
        attr = getattr(pkg, cls.__name__, None)
        assert attr is cls, (
            f"{cls.__name__} (provider {provider_name!r}) is discovered "
            f"but not re-exported from nanobot.providers.image_generation"
        )
        assert cls.__name__ in pkg.__all__, (
            f"{cls.__name__} (provider {provider_name!r}) is missing from __all__"
        )
