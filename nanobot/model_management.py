"""Config-backed `/model` command handling."""

from __future__ import annotations

import shlex
from dataclasses import dataclass
from pathlib import Path

import httpx

from nanobot.config.loader import get_config_path, load_config, save_config
from nanobot.config.schema import Config
from nanobot.providers.factory import ProviderConfigurationError, create_provider
from nanobot.providers.registry import PROVIDERS, ProviderSpec, find_by_name

OPENAI_COMPATIBLE_PROVIDERS = frozenset(
    {
        "custom",
        "openai",
        "openrouter",
        "deepseek",
        "groq",
        "minimax",
        "aihubmix",
        "siliconflow",
        "volcengine",
        "dashscope",
        "moonshot",
        "zhipu",
        "vllm",
    }
)

HOSTED_PROVIDER_BASES = {
    "openai": "https://api.openai.com/v1",
    "anthropic": "https://api.anthropic.com/v1",
    "deepseek": "https://api.deepseek.com/v1",
    "groq": "https://api.groq.com/openai/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta",
    "dashscope": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "zhipu": "https://open.bigmodel.cn/api/paas/v4",
}

DISCOVERY_TIMEOUT = 3.0
MODEL_USAGE_TEXT = (
    "Usage:\n"
    "- /model\n"
    "- /model <model>\n"
    "- /model <current-provider> <model>"
)
PROVIDER_USAGE_TEXT = (
    "Usage:\n"
    "- /provider\n"
    "- /provider <provider>"
)


@dataclass(frozen=True)
class ModelSelection:
    """Normalized `/model` selection result."""

    provider: ProviderSpec
    config_model: str


class ModelCommandError(ValueError):
    """Raised when `/model` parsing or validation fails."""


def handle_provider_command(command_text: str) -> str:
    """Handle `/provider` by switching to a configured provider and its first discovered model."""
    config_path = get_config_path()
    config = load_config(config_path)

    try:
        command_parts = shlex.split(command_text)
    except ValueError:
        return f"Invalid command syntax.\n{PROVIDER_USAGE_TEXT}"

    if len(command_parts) == 1:
        return format_provider_status(config, config_path)

    if len(command_parts) != 2:
        return PROVIDER_USAGE_TEXT

    try:
        selection = _provider_selection(config, command_parts[1])
        _validate_selection(config, config_path, selection)
    except ModelCommandError as exc:
        return str(exc)

    candidate = config.model_copy(deep=True)
    candidate.agents.defaults.provider = selection.provider.name
    candidate.agents.defaults.model = selection.config_model
    save_config(candidate, config_path)

    return (
        "Saved provider configuration.\n"
        f"Config file: {config_path}\n"
        f"Provider: {selection.provider.name}\n"
        f"Model: {selection.config_model}\n"
        "Restart nanobot to apply."
    )


def handle_model_command(command_text: str) -> str:
    """Handle `/model` using the current configured provider only."""
    config_path = get_config_path()
    config = load_config(config_path)

    try:
        command_parts = shlex.split(command_text)
    except ValueError:
        return f"Invalid command syntax.\n{MODEL_USAGE_TEXT}"

    if len(command_parts) == 1:
        return format_model_status(config, config_path)

    if len(command_parts) not in {2, 3}:
        return MODEL_USAGE_TEXT

    try:
        current_spec = _current_provider_spec(config)
        selection = _selection_from_command(config, current_spec, command_parts)
        _validate_selection(config, config_path, selection)
    except ModelCommandError as exc:
        return str(exc)

    candidate = config.model_copy(deep=True)
    candidate.agents.defaults.provider = selection.provider.name
    candidate.agents.defaults.model = selection.config_model
    save_config(candidate, config_path)

    return (
        "Saved model configuration.\n"
        f"Config file: {config_path}\n"
        f"Provider: {selection.provider.name}\n"
        f"Model: {selection.config_model}\n"
        "Restart nanobot to apply."
    )


def format_provider_status(config: Config, config_path: Path) -> str:
    """Return the current provider and configured providers that can be switched to."""
    try:
        current_spec = _current_provider_spec(config)
    except ModelCommandError as exc:
        return str(exc)

    lines = [
        "Provider Configuration",
        f"Config file: {config_path}",
        f"Current provider: {current_spec.name}",
        f"Current model: {config.agents.defaults.model}",
        "",
        "Available providers:",
    ]

    available_specs = _available_provider_specs(config, current_spec)
    if not available_specs:
        lines.append("- No configured providers are available.")
        return "\n".join(lines)

    for spec in available_specs:
        provider_url = _provider_api_base(config, spec) or "(not configured)"
        lines.append(f"- /provider {spec.name} ({provider_url})")

    return "\n".join(lines)


def format_model_status(config: Config, config_path: Path) -> str:
    """Return the current provider and models discovered from its URL."""
    try:
        current_spec = _current_provider_spec(config)
    except ModelCommandError as exc:
        return str(exc)

    current_model = config.agents.defaults.model
    current_option_model = _option_model_for_provider(current_spec, current_model)
    models = discover_models_for_provider(config, current_spec)
    if current_option_model and current_option_model not in models:
        models.insert(0, current_option_model)

    lines = [
        "Model Configuration",
        f"Config file: {config_path}",
        f"Current provider: {current_spec.name}",
        f"Current model: {current_model}",
        f"Provider URL: {_provider_api_base(config, current_spec) or '(not configured)'}",
        "",
        "Available models:",
    ]

    if not models:
        lines.append("- No models discovered from the current provider URL.")
        return "\n".join(lines)

    for model in models:
        lines.append(f"- /model {model}")

    return "\n".join(lines)


def discover_models_for_provider(config: Config, spec: ProviderSpec) -> list[str]:
    """Return models discovered for a single provider."""
    provider_config = getattr(config.providers, spec.name, None)
    if provider_config is None:
        return []

    try:
        if spec.name == "ollama":
            return _discover_ollama_models(_provider_api_base(config, spec))
        if spec.name == "anthropic":
            return _discover_anthropic_models(
                _provider_api_base(config, spec),
                provider_config.api_key,
            )
        if spec.name == "gemini":
            return _discover_gemini_models(
                _provider_api_base(config, spec),
                provider_config.api_key,
            )
        if spec.name in OPENAI_COMPATIBLE_PROVIDERS:
            return _discover_openai_compatible_models(
                _provider_api_base(config, spec),
                provider_config.api_key,
                provider_config.extra_headers or {},
            )
    except Exception:
        return []

    return []


def _selection_from_command(
    config: Config,
    current_spec: ProviderSpec,
    command_parts: list[str],
) -> ModelSelection:
    if len(command_parts) == 2:
        return _build_selection(current_spec, command_parts[1])

    requested_provider = _normalize_provider_name(command_parts[1])
    if requested_provider != current_spec.name:
        raise ModelCommandError(
            f"Current provider is `{current_spec.name}`. `/model` only selects models from that provider URL."
        )
    return _build_selection(current_spec, command_parts[2])


def _provider_selection(config: Config, provider: str) -> ModelSelection:
    spec = find_by_name(_normalize_provider_name(provider))
    if spec is None:
        raise ModelCommandError(f"Unknown provider `{provider}`.")
    if not _is_provider_available(config, spec):
        raise ModelCommandError(f"Provider `{spec.name}` is not configured for use.")

    models = discover_models_for_provider(config, spec)
    if not models:
        raise ModelCommandError(
            f"No models discovered for `{spec.name}`. Check its apiKey/apiBase and try again."
        )
    return _build_selection(spec, models[0])


def _build_selection(spec: ProviderSpec, model: str) -> ModelSelection:
    normalized_model = model.strip()
    if not normalized_model:
        raise ModelCommandError("Model name is required.")

    if "/" in normalized_model:
        prefix, remainder = normalized_model.split("/", 1)
        if _normalize_provider_name(prefix) != spec.name:
            raise ModelCommandError(
                f"Current provider is `{spec.name}`. `/model` only selects models from that provider URL."
            )
        normalized_model = remainder

    if spec.is_gateway or spec.is_local or spec.is_direct:
        config_model = normalized_model
    else:
        config_model = f"{spec.name.replace('_', '-')}/{normalized_model}"

    return ModelSelection(provider=spec, config_model=config_model)


def _validate_selection(config: Config, config_path: Path, selection: ModelSelection) -> None:
    candidate = config.model_copy(deep=True)
    candidate.agents.defaults.provider = selection.provider.name
    candidate.agents.defaults.model = selection.config_model

    try:
        create_provider(candidate)
    except ProviderConfigurationError as exc:
        raise ModelCommandError(f"Cannot save model.\nReason: {exc} ({config_path})") from exc
    except Exception as exc:
        raise ModelCommandError(f"Cannot save model.\nReason: {exc}") from exc


def _available_provider_specs(config: Config, current_spec: ProviderSpec) -> list[ProviderSpec]:
    return [spec for spec in PROVIDERS if spec == current_spec or _is_provider_available(config, spec)]


def _current_provider_spec(config: Config) -> ProviderSpec:
    provider_name = config.get_provider_name(config.agents.defaults.model) or config.agents.defaults.provider
    spec = find_by_name(provider_name) if provider_name else None
    if spec is None:
        raise ModelCommandError("Current model does not resolve to a known provider.")
    return spec


def _is_provider_available(config: Config, spec: ProviderSpec) -> bool:
    current_spec = _current_provider_spec(config)
    if current_spec.name == spec.name:
        return True

    provider_config = getattr(config.providers, spec.name, None)
    if provider_config is None:
        return False
    if spec.name in {"custom", "azure_openai"}:
        return bool(provider_config.api_key and provider_config.api_base)
    if spec.is_oauth:
        return _oauth_provider_available(spec)
    if spec.is_local:
        return bool(provider_config.api_base)
    if spec.is_gateway:
        return bool(provider_config.api_key)
    return bool(provider_config.api_key)


def _oauth_provider_available(spec: ProviderSpec) -> bool:
    if spec.name == "openai_codex":
        try:
            from oauth_cli_kit import get_token

            token = get_token()
            return bool(token and getattr(token, "access", None))
        except Exception:
            return False
    return False


def _provider_api_base(config: Config, spec: ProviderSpec) -> str | None:
    provider_config = getattr(config.providers, spec.name, None)
    if provider_config and provider_config.api_base:
        return provider_config.api_base.rstrip("/")
    if spec.default_api_base:
        return spec.default_api_base.rstrip("/")
    default_base = HOSTED_PROVIDER_BASES.get(spec.name)
    return default_base.rstrip("/") if default_base else None


def _discover_openai_compatible_models(
    api_base: str | None,
    api_key: str | None,
    extra_headers: dict[str, str],
) -> list[str]:
    if not api_base:
        return []

    headers = {"Accept": "application/json", **extra_headers}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    with httpx.Client(timeout=DISCOVERY_TIMEOUT, follow_redirects=True) as client:
        response = client.get(f"{api_base.rstrip('/')}/models", headers=headers)
        if response.status_code >= 400:
            return []
        payload = response.json()

    items = payload.get("data") or payload.get("models") or []
    return _unique_strings(item.get("id") or item.get("name") for item in items if isinstance(item, dict))


def _discover_ollama_models(api_base: str | None) -> list[str]:
    if not api_base:
        return []

    with httpx.Client(timeout=DISCOVERY_TIMEOUT, follow_redirects=True) as client:
        response = client.get(f"{api_base.rstrip('/')}/api/tags")
        if response.status_code >= 400:
            return []
        payload = response.json()

    items = payload.get("models") or []
    return _unique_strings(item.get("name") for item in items if isinstance(item, dict))


def _discover_anthropic_models(api_base: str | None, api_key: str | None) -> list[str]:
    if not api_base or not api_key:
        return []

    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "Accept": "application/json",
    }

    with httpx.Client(timeout=DISCOVERY_TIMEOUT, follow_redirects=True) as client:
        response = client.get(f"{api_base.rstrip('/')}/models", headers=headers)
        if response.status_code >= 400:
            return []
        payload = response.json()

    items = payload.get("data") or payload.get("models") or []
    return _unique_strings(item.get("id") or item.get("name") for item in items if isinstance(item, dict))


def _discover_gemini_models(api_base: str | None, api_key: str | None) -> list[str]:
    if not api_base or not api_key:
        return []

    with httpx.Client(timeout=DISCOVERY_TIMEOUT, follow_redirects=True) as client:
        response = client.get(
            f"{api_base.rstrip('/')}/models",
            params={"key": api_key},
            headers={"Accept": "application/json"},
        )
        if response.status_code >= 400:
            return []
        payload = response.json()

    items = payload.get("models") or []
    models: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        methods = item.get("supportedGenerationMethods") or []
        if methods and not any(method in {"generateContent", "streamGenerateContent"} for method in methods):
            continue
        name = item.get("name") or ""
        if name.startswith("models/"):
            name = name.split("/", 1)[1]
        if name:
            models.append(name)
    return _unique_strings(models)


def _unique_strings(values) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        if not value or not isinstance(value, str):
            continue
        if value in seen:
            continue
        seen.add(value)
        output.append(value)
    return output


def _option_model_for_provider(spec: ProviderSpec, model: str) -> str:
    if spec.is_gateway or spec.is_local or spec.is_direct:
        return model.split("/", 1)[1] if model.startswith(f"{spec.name}/") else model
    if "/" not in model:
        return model
    prefix, remainder = model.split("/", 1)
    if _normalize_provider_name(prefix) == spec.name:
        return remainder
    return model


def _normalize_provider_name(provider: str) -> str:
    return provider.strip().lower().replace("-", "_")
