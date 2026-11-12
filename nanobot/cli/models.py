"""Model discovery for the onboard wizard, shared with WebUI settings."""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from nanobot.config.schema import Config, ModelPresetConfig
from nanobot.webui.settings_contracts import WebUISettingsError
from nanobot.webui.settings_models import provider_models_payload


@dataclass(frozen=True)
class ModelInfo:
    id: str
    context_window: int | None


def get_model_catalog(
    config: Config, provider: str, model: str = "",
) -> list[ModelInfo]:
    """Read the selected provider's advisory catalog using the current wizard draft."""
    if provider == "auto":
        provider = config.get_provider_name(preset=ModelPresetConfig(model=model)) or ""
    if not provider:
        return []
    try:
        payload = provider_models_payload(
            config, {"provider": [provider]}, http_get=httpx.get,
        )
    except WebUISettingsError:
        return []
    return [
        ModelInfo(row["id"], row["context_window"])
        for row in payload["models"]
    ]


def get_model_context_limit(
    model: str, provider: str, *, config: Config,
) -> int | None:
    if provider == "auto":
        provider = config.get_provider_name(preset=ModelPresetConfig(model=model)) or ""
    rows = get_model_catalog(config, provider, model)
    for row in rows:
        if row.id == model:
            return row.context_window
    # Explicit provider prefixes are accepted by the wizard as well as bare IDs.
    prefix, separator, bare_model = model.partition("/")
    if separator and prefix.replace("-", "_") == provider.replace("-", "_"):
        return next((row.context_window for row in rows if row.id == bare_model), None)
    return None


def format_token_count(tokens: int) -> str:
    """Format token count for display (e.g., 200000 -> '200,000')."""
    return f"{tokens:,}"
