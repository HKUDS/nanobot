"""Setup templates create ordinary custom connections, not runtime providers."""

import re
from dataclasses import dataclass

from nanobot.config.schema import Config, ProviderAPIConfig, ProviderConfig
from nanobot.providers.registry import PROVIDERS, find_by_name


@dataclass(frozen=True)
class ProviderSetupTemplate:
    id: str
    label: str
    api_base: str
    api: ProviderAPIConfig
    search_aliases: str = ""


PROVIDER_SETUP_TEMPLATES = (
    ProviderSetupTemplate(
        id="shengsuanyun",
        label="ShengSuanYun Router",
        api_base="https://router.shengsuanyun.com/api/v1",
        api=ProviderAPIConfig(
            supported_apis=("chat_completions", "responses"), preferred_api="chat_completions",
        ),
        search_aliases="胜算云 勝算雲",
    ),
)


def dynamic_provider_items(config: Config) -> list[tuple[str, ProviderConfig]]:
    return [
        (key, provider)
        for key, provider in (config.providers.model_extra or {}).items()
        if isinstance(provider, ProviderConfig)
    ]


def custom_provider_key(config: Config, display_name: str) -> str:
    slug = re.sub(r"[^a-z0-9_-]+", "-", display_name.strip().lower()).strip("-_")
    base = f"custom-{slug or 'provider'}"[:56].rstrip("-_")
    existing = {key.replace("_", "-").lower() for key, _ in dynamic_provider_items(config)}
    candidate = base
    suffix = 2
    while candidate.replace("_", "-") in existing or find_by_name(candidate):
        candidate = f"{base}-{suffix}"
        suffix += 1
    return candidate


def provider_display_name_exists(
    config: Config, display_name: str, *, exclude_key: str | None = None,
) -> bool:
    normalized = display_name.strip().casefold()
    if any(spec.label.strip().casefold() == normalized for spec in PROVIDERS):
        return True
    return any(
        key != exclude_key
        and (provider.display_name or key.replace("-", " ").replace("_", " ")).strip().casefold()
        == normalized
        for key, provider in dynamic_provider_items(config)
    )


def setup_template_names(config: Config, template: ProviderSetupTemplate) -> tuple[str, str]:
    """Pick an unused display name and preset name for a new connection."""
    presets = {"default", "primary", *(name.casefold() for name in config.model_presets)}
    label, preset = template.label, template.id
    index = 2
    while preset.casefold() in presets or provider_display_name_exists(config, label):
        label, preset = f"{template.label} {index}", f"{template.id}-{index}"
        index += 1
    return label, preset
