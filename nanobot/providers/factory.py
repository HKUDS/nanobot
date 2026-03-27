"""Provider factory — reusable provider construction from Config.

Extracted from ``cli/commands.py::_make_provider`` so that both the CLI
and ``SubagentManager`` can build providers without CLI dependencies.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nanobot.config.schema import Config
    from nanobot.providers.base import LLMProvider


def make_provider(config: Config) -> LLMProvider:
    """Create the appropriate LLM provider from *config*.

    Raises ``ValueError`` on configuration errors (no API key, missing
    Azure fields, etc.) instead of calling ``typer.Exit``.
    """
    from nanobot.providers.base import GenerationSettings
    from nanobot.providers.registry import find_by_name

    model = config.active_defaults.model
    provider_name = config.get_provider_name(model)
    p = config.get_provider(model)
    spec = find_by_name(provider_name) if provider_name else None
    backend = spec.backend if spec else "openai_compat"

    # --- validation ---
    if backend == "azure_openai":
        if not p or not p.api_key or not p.api_base:
            raise ValueError(
                "Azure OpenAI requires api_key and api_base. "
                "Set them in ~/.nanobot/config.json under providers.azure_openai section."
            )
    elif backend == "openai_compat" and not model.startswith("bedrock/"):
        needs_key = not (p and p.api_key)
        exempt = spec and (spec.is_oauth or spec.is_local or spec.is_direct)
        if needs_key and not exempt:
            raise ValueError(
                "No API key configured. Set one in ~/.nanobot/config.json under providers section."
            )

    # --- instantiation by backend ---
    if backend == "openai_codex":
        from nanobot.providers.openai_codex_provider import OpenAICodexProvider

        provider = OpenAICodexProvider(default_model=model)
    elif backend == "azure_openai":
        from nanobot.providers.azure_openai_provider import AzureOpenAIProvider

        provider = AzureOpenAIProvider(
            api_key=p.api_key,
            api_base=p.api_base,
            default_model=model,
        )
    elif backend == "anthropic":
        from nanobot.providers.anthropic_provider import AnthropicProvider

        provider = AnthropicProvider(
            api_key=p.api_key if p else None,
            api_base=config.get_api_base(model),
            default_model=model,
            extra_headers=p.extra_headers if p else None,
        )
    elif provider_name == "ovms":
        from nanobot.providers.custom_provider import CustomProvider

        provider = CustomProvider(
            api_key=p.api_key if p else "no-key",
            api_base=config.get_api_base(model) or "http://localhost:8000/v3",
            default_model=model,
        )
    else:
        spec = find_by_name(provider_name)
        if not spec and p and p.api_key and config.get_api_base(model):
            from nanobot.providers.custom_provider import CustomProvider

            provider = CustomProvider(
                api_key=p.api_key,
                api_base=config.get_api_base(model),
                default_model=model,
                extra_headers=p.extra_headers if p else None,
            )
        else:
            from nanobot.providers.openai_compat_provider import OpenAICompatProvider

            if (
                not model.startswith("bedrock/")
                and not (p and p.api_key)
                and not (spec and (spec.is_oauth or spec.is_local))
            ):
                raise ValueError(
                    "No API key configured. "
                    "Set one in ~/.nanobot/config.json under providers section."
                )
            provider = OpenAICompatProvider(
                api_key=p.api_key if p else None,
                api_base=config.get_api_base(model),
                default_model=model,
                extra_headers=p.extra_headers if p else None,
                spec=spec,
            )

    defaults = config.active_defaults
    provider.generation = GenerationSettings(
        temperature=defaults.temperature,
        max_tokens=defaults.max_tokens,
        reasoning_effort=defaults.reasoning_effort,
    )
    return provider
