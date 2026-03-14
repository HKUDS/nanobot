"""Config-backed /model command handling."""

from __future__ import annotations

import shlex
from dataclasses import dataclass
from pathlib import Path

from nanobot.config.loader import get_config_path, load_config, save_config
from nanobot.config.schema import Config
from nanobot.providers.factory import ProviderConfigurationError, create_provider
from nanobot.providers.registry import ProviderSpec, find_by_model, find_by_name, PROVIDERS

MODEL_CATALOG: dict[str, tuple[str, ...]] = {
    "anthropic": ("claude-sonnet-4-5", "claude-opus-4-5"),
    "openai": ("gpt-4o", "gpt-4o-mini", "gpt-5"),
    "gemini": ("gemini-2.5-pro", "gemini-2.5-flash"),
    "deepseek": ("deepseek-chat", "deepseek-reasoner"),
    "groq": ("llama-3.3-70b-versatile", "mixtral-8x7b-32768"),
    "dashscope": ("qwen-max", "qwen-plus"),
    "moonshot": ("kimi-k2.5", "moonshot-v1-8k"),
    "zhipu": ("glm-4-plus", "glm-4-air"),
    "minimax": ("MiniMax-M1", "MiniMax-Text-01"),
    "openrouter": ("anthropic/claude-sonnet-4-5", "openai/gpt-4o"),
    "aihubmix": ("gpt-4o", "claude-sonnet-4-5"),
    "siliconflow": ("Qwen/Qwen2.5-72B-Instruct", "deepseek-ai/DeepSeek-V3"),
    "volcengine": ("doubao-1-5-pro-32k-250115",),
    "openai_codex": ("openai-codex/gpt-5.1-codex",),
    "github_copilot": ("github-copilot/gpt-4o", "github-copilot/claude-sonnet-4"),
    "ollama": ("llama3.2", "qwen2.5-coder:7b"),
}

MODEL_PREFIX_ALIASES = {
    "openai_codex": "openai-codex",
    "github_copilot": "github-copilot",
}


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
            selection = _selection_from_full_model(command_parts[1])
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
    if not options:
        lines.extend(
            [
                "Available models:",
                "- No switchable models are available from the current config.",
            ]
        )
        return "\n".join(lines)

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
    current_display_model = _display_model_for_provider(
        find_by_name(current_provider_name) if current_provider_name else None,
        config.agents.defaults.model,
    )

    options: list[str] = []
    for spec in PROVIDERS:
        if not _is_provider_available(config, spec):
            continue
        models = list(MODEL_CATALOG.get(spec.name, ()))
        if current_provider_name == spec.name and current_display_model:
            if current_display_model not in models:
                models.insert(0, current_display_model)
        for model in models:
            options.append(f"{spec.name.replace('_', '-')} {model}")
    return options


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


def _model_prefix(spec: ProviderSpec) -> str:
    return MODEL_PREFIX_ALIASES.get(spec.name, spec.name).replace("_", "-")


def _normalize_provider_name(provider: str) -> str:
    return provider.strip().lower().replace("-", "_")
