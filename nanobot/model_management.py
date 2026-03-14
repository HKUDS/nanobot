"""Config-backed /model command handling."""

from __future__ import annotations

import shlex
from dataclasses import dataclass
from pathlib import Path

import httpx

from nanobot.config.loader import get_config_path, load_config, save_config
from nanobot.config.schema import Config
from nanobot.providers.factory import ProviderConfigurationError, create_provider
from nanobot.providers.registry import ProviderSpec, find_by_model, find_by_name, PROVIDERS

MODEL_PREFIX_ALIASES = {
    "openai_codex": "openai-codex",
    "github_copilot": "github-copilot",
}

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
MINIMAX_ANTHROPIC_BASE_KEYWORD = "api.minimaxi.com/anthropic"
MINIMAX_SHORTCUT_MODEL = "MiniMax-M2.5"


@dataclass(frozen=True)
class ModelSelection:
    """Normalized /model selection result."""

    provider: ProviderSpec
    config_model: str
    display_model: str


class ModelCommandError(ValueError):
    """Raised when /model parsing or validation fails."""


def handle_model_command(command_text: str) -> str:
    """Handle `/model` command using the active config file as the source of truth."""
    config_path = get_config_path()
    config = load_config(config_path)
    command_parts = shlex.split(command_text)

    if len(command_parts) == 1:
        return format_model_status(config, config_path)

    if len(command_parts) not in {2, 3}:
        return (
            "Usage:\n"
            "- /model\n"
            "- /model <provider> <model>\n"
            "- /model <full-model-id>"
        )

    try:
        if len(command_parts) == 2:
            shortcut = _shortcut_selections(config).get(_normalize_shortcut(command_parts[1]))
            selection = shortcut or _selection_from_full_model(command_parts[1])
        else:
            selection = _selection_from_provider_and_model(command_parts[1], command_parts[2])
    except ModelCommandError as exc:
        return str(exc)

    try:
        _validate_selection(config, config_path, selection)
    except ModelCommandError as exc:
        return f"Cannot switch to `{selection.display_model}`.\nReason: {exc}"

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


def format_model_status(config: Config, config_path: Path) -> str:
    """Return a readable status block for `/model` with selectable options."""
    current_provider = config.get_provider_name(config.agents.defaults.model) or config.agents.defaults.provider
    current_model = config.agents.defaults.model
    lines = [
        "Model Configuration",
        f"Config file: {config_path}",
        f"Current provider: {current_provider}",
        f"Current model: {current_model}",
        "",
    ]

    options = list_switchable_models(config)
    shortcuts = _shortcut_selections(config)
    if not options:
        lines.extend(
            [
                "Available models:",
                "- No switchable models are available from the current config.",
            ]
        )
        return "\n".join(lines)

    if shortcuts:
        lines.append("Available shortcuts:")
        for name, selection in shortcuts.items():
            lines.append(f"- /model {name} -> {selection.config_model}")
        lines.append("")

    lines.append("Available models:")
    for option in options:
        lines.append(f"- /model {option}")

    direct_examples = _direct_examples(options)
    if direct_examples:
        lines.extend(["", "Direct set:"])
        for option in direct_examples:
            lines.append(f"- /model {option}")

    return "\n".join(lines)


def list_switchable_models(config: Config) -> list[str]:
    """List all switchable `/model <provider> <model>` options for usable providers."""
    current_provider_name = config.get_provider_name(config.agents.defaults.model) or config.agents.defaults.provider
    current_option_model = _option_model_for_provider(
        find_by_name(current_provider_name) if current_provider_name else None,
        config.agents.defaults.model,
    )

    options: list[str] = []
    minimax_compat = _minimax_shortcut_selection(config)
    for spec in PROVIDERS:
        if not _is_provider_available(config, spec):
            continue
        models = [
            _option_model_for_provider(spec, model)
            for model in discover_models_for_provider(config, spec)
        ]
        models = [model for model in models if model]
        if current_provider_name == spec.name and current_option_model:
            if spec.name == "minimax" and minimax_compat is not None:
                pass
            elif current_option_model not in models:
                models.insert(0, current_option_model)
        if not models:
            continue
        for model in models:
            options.append(f"{spec.name.replace('_', '-')} {model}")
    if minimax_compat is not None:
        compat_option = (
            f"{minimax_compat.provider.name.replace('_', '-')} "
            f"{_option_model_for_provider(minimax_compat.provider, minimax_compat.config_model)}"
        )
        if compat_option not in options:
            options.append(compat_option)
    return options


def discover_models_for_provider(config: Config, spec: ProviderSpec) -> list[str]:
    """Return dynamically discovered models for one provider."""
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


def _direct_examples(options: list[str]) -> list[str]:
    """Build `/model <full-model-id>` examples for standard providers."""
    direct: list[str] = []
    for option in options:
        provider_raw, model = option.split(" ", 1)
        spec = find_by_name(_normalize_provider_name(provider_raw))
        if not spec or spec.is_gateway or spec.is_local or spec.is_direct:
            continue
        direct.append(f"{provider_raw}/{model}")
    return direct[:8]


def _shortcut_selections(config: Config) -> dict[str, ModelSelection]:
    shortcuts: dict[str, ModelSelection] = {}
    for option in list_switchable_models(config):
        provider_raw, model = option.split(" ", 1)
        selection = _selection_from_provider_and_model(provider_raw, model)
        alias = _shortcut_alias(selection)
        if alias and alias not in shortcuts:
            shortcuts[alias] = selection
    minimax_compat = _minimax_shortcut_selection(config)
    if minimax_compat is not None:
        shortcuts["minimax"] = minimax_compat
    return shortcuts


def _shortcut_alias(selection: ModelSelection) -> str | None:
    model = _option_model_for_provider(selection.provider, selection.config_model).lower()
    if model.startswith("gpt"):
        return "gpt"
    if model.startswith("minimax"):
        return "minimax"
    return None


def _minimax_shortcut_selection(config: Config) -> ModelSelection | None:
    anthropic_config = getattr(config.providers, "anthropic", None)
    if not anthropic_config or not anthropic_config.api_key or not anthropic_config.api_base:
        return None
    if MINIMAX_ANTHROPIC_BASE_KEYWORD not in anthropic_config.api_base:
        return None
    spec = find_by_name("anthropic")
    if spec is None:
        return None
    model_name = _preferred_minimax_model(config)
    return ModelSelection(
        provider=spec,
        config_model=f"anthropic/{model_name}",
        display_model=f"anthropic/{model_name}",
    )


def _preferred_minimax_model(config: Config) -> str:
    current_model = config.agents.defaults.model
    current_lower = current_model.lower()
    if "minimax" in current_lower:
        return current_model.split("/", 1)[1] if "/" in current_model else current_model
    return MINIMAX_SHORTCUT_MODEL


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


def _selection_from_full_model(model: str) -> ModelSelection:
    spec = _infer_provider_from_model(model)
    if not spec:
        raise ModelCommandError(
            f"Cannot infer a configured provider from `{model}`. Use `/model <provider> <model>`."
        )
    return _build_selection(spec, model)


def _selection_from_provider_and_model(provider: str, model: str) -> ModelSelection:
    spec = find_by_name(_normalize_provider_name(provider))
    if not spec:
        raise ModelCommandError(f"Unknown provider `{provider}`.")
    return _build_selection(spec, model)


def _build_selection(spec: ProviderSpec, model: str) -> ModelSelection:
    normalized_model = model.strip()
    if not normalized_model:
        raise ModelCommandError("Model name is required.")

    if spec.is_gateway or spec.is_local or spec.is_direct:
        config_model = _strip_provider_prefix(spec, normalized_model)
    else:
        config_model = _ensure_prefixed_model(spec, normalized_model)

    display_model = _display_model_for_provider(spec, config_model)
    return ModelSelection(provider=spec, config_model=config_model, display_model=display_model)


def _validate_selection(config: Config, config_path: Path, selection: ModelSelection) -> None:
    spec = selection.provider
    if not _is_provider_available(config, spec):
        raise ModelCommandError(_provider_availability_error(config_path, spec))
    if not _model_matches_provider(spec, selection.display_model):
        raise ModelCommandError(
            f"`{selection.display_model}` does not match provider `{spec.name}`."
        )

    candidate = config.model_copy(deep=True)
    candidate.agents.defaults.provider = spec.name
    candidate.agents.defaults.model = selection.config_model

    try:
        create_provider(candidate)
    except ProviderConfigurationError as exc:
        raise ModelCommandError(f"{exc} ({config_path})") from exc
    except Exception as exc:
        raise ModelCommandError(str(exc)) from exc


def _is_provider_available(config: Config, spec: ProviderSpec) -> bool:
    current_provider = config.get_provider_name(config.agents.defaults.model) or config.agents.defaults.provider
    if current_provider == spec.name:
        return True

    provider_config = getattr(config.providers, spec.name, None)
    if provider_config is None:
        return False

    if spec.name == "custom":
        return bool(provider_config.api_key and provider_config.api_base)
    if spec.name == "azure_openai":
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


def _provider_availability_error(config_path: Path, spec: ProviderSpec) -> str:
    if spec.name == "custom":
        return f"`providers.custom.apiKey` or `providers.custom.apiBase` is missing in {config_path}"
    if spec.name == "azure_openai":
        return f"`providers.azure_openai.apiKey` or `providers.azure_openai.apiBase` is missing in {config_path}"
    if spec.is_local:
        return f"`providers.{spec.name}.apiBase` is missing in {config_path}"
    if spec.is_oauth:
        return (
            f"`{spec.name}` is not logged in. Run `nanobot provider login {spec.name.replace('_', '-')}` "
            f"or switch back to an already active provider."
        )
    return f"`providers.{spec.name}.apiKey` is missing in {config_path}"


def _model_matches_provider(spec: ProviderSpec, model: str) -> bool:
    if spec.is_gateway or spec.is_local or spec.is_direct:
        return True
    if "/" in model:
        prefix = _normalize_provider_name(model.split("/", 1)[0])
        if prefix == spec.name:
            return True
        if find_by_name(prefix) and prefix != spec.name:
            return False
    model_lower = model.lower()
    model_normalized = model_lower.replace("-", "_")
    return any(
        keyword in model_lower or keyword.replace("-", "_") in model_normalized
        for keyword in spec.keywords
    )


def _infer_provider_from_model(model: str) -> ProviderSpec | None:
    if "/" in model:
        prefix = _normalize_provider_name(model.split("/", 1)[0])
        spec = find_by_name(prefix)
        if spec:
            return spec
    return find_by_model(model)


def _ensure_prefixed_model(spec: ProviderSpec, model: str) -> str:
    if "/" not in model:
        return f"{_model_prefix(spec)}/{model}"

    prefix, remainder = model.split("/", 1)
    normalized_prefix = _normalize_provider_name(prefix)
    if find_by_name(normalized_prefix) and normalized_prefix != spec.name:
        raise ModelCommandError(
            f"`{model}` targets `{normalized_prefix}`, not `{spec.name}`."
        )
    if normalized_prefix == spec.name:
        return f"{_model_prefix(spec)}/{remainder}"
    return f"{_model_prefix(spec)}/{model}"


def _strip_provider_prefix(spec: ProviderSpec, model: str) -> str:
    if "/" not in model:
        return model
    prefix, remainder = model.split("/", 1)
    if _normalize_provider_name(prefix) == spec.name:
        return remainder
    return model


def _display_model_for_provider(spec: ProviderSpec | None, model: str) -> str:
    if spec is None:
        return model
    if spec.is_gateway or spec.is_local or spec.is_direct:
        return _strip_provider_prefix(spec, model)
    if "/" in model:
        prefix, remainder = model.split("/", 1)
        if _normalize_provider_name(prefix) == spec.name:
            return f"{_model_prefix(spec)}/{remainder}"
    return f"{_model_prefix(spec)}/{model}"


def _option_model_for_provider(spec: ProviderSpec | None, model: str) -> str:
    if spec is None:
        return model
    if spec.is_gateway or spec.is_local or spec.is_direct:
        return _strip_provider_prefix(spec, model)
    if "/" in model:
        prefix, remainder = model.split("/", 1)
        if _normalize_provider_name(prefix) == spec.name:
            return remainder
    return model


def _model_prefix(spec: ProviderSpec) -> str:
    return MODEL_PREFIX_ALIASES.get(spec.name, spec.name).replace("_", "-")


def _normalize_provider_name(provider: str) -> str:
    return provider.strip().lower().replace("-", "_")


def _normalize_shortcut(value: str) -> str:
    return value.strip().lower()
