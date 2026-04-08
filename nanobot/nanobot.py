"""High-level programmatic interface to nanobot."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from nanobot.agent.hook import AgentHook
from nanobot.agent.loop import AgentLoop
from nanobot.bus.queue import MessageBus


@dataclass(slots=True)
class RunResult:
    """Result of a single agent run."""

    content: str
    tools_used: list[str]
    messages: list[dict[str, Any]]


class Nanobot:
    """Programmatic facade for running the nanobot agent.

    Usage::

        bot = Nanobot.from_config()
        result = await bot.run("Summarize this repo", hooks=[MyHook()])
        print(result.content)
    """

    def __init__(self, loop: AgentLoop) -> None:
        self._loop = loop

    @classmethod
    def from_config(
        cls,
        config_path: str | Path | None = None,
        *,
        workspace: str | Path | None = None,
    ) -> Nanobot:
        """Create a Nanobot instance from a config file.

        Args:
            config_path: Path to ``config.json``.  Defaults to
                ``~/.nanobot/config.json``.
            workspace: Override the workspace directory from config.
        """
        from nanobot.config.loader import load_config
        from nanobot.config.schema import Config

        resolved: Path | None = None
        if config_path is not None:
            resolved = Path(config_path).expanduser().resolve()
            if not resolved.exists():
                raise FileNotFoundError(f"Config not found: {resolved}")

        config: Config = load_config(resolved)
        if workspace is not None:
            config.agents.defaults.workspace = str(
                Path(workspace).expanduser().resolve()
            )

        provider = _make_provider(config)
        bus = MessageBus()
        defaults = config.agents.defaults

        from nanobot.providers.context_window import resolve_context_window_sync
        ctx_tokens, _ctx_source = resolve_context_window_sync(
            model=defaults.model,
            configured_value=defaults.context_window_tokens,
        )

        loop = AgentLoop(
            bus=bus,
            provider=provider,
            workspace=config.workspace_path,
            model=defaults.model,
            max_iterations=defaults.max_tool_iterations,
            context_window_tokens=ctx_tokens,
            web_config=config.tools.web,
            web_proxy=config.tools.web.proxy or None,
            exec_config=config.tools.exec,
            restrict_to_workspace=config.tools.restrict_to_workspace,
            mcp_servers=config.tools.mcp_servers,
            timezone=defaults.timezone,
            skills_config=defaults.skills,
            config=config,
        )
        return cls(loop)

    async def run(
        self,
        message: str,
        *,
        session_key: str = "sdk:default",
        hooks: list[AgentHook] | None = None,
    ) -> RunResult:
        """Run the agent once and return the result.

        Args:
            message: The user message to process.
            session_key: Session identifier for conversation isolation.
                Different keys get independent history.
            hooks: Optional lifecycle hooks for this run.
        """
        prev = self._loop._extra_hooks
        if hooks is not None:
            self._loop._extra_hooks = list(hooks)
        try:
            response = await self._loop.process_direct(
                message, session_key=session_key,
            )
        finally:
            self._loop._extra_hooks = prev

        content = (response.content if response else None) or ""
        return RunResult(content=content, tools_used=[], messages=[])


def _make_provider(config: Any) -> Any:
    """Create the LLM provider from config (extracted from CLI)."""
    from nanobot.providers.base import GenerationSettings
    from nanobot.providers.registry import find_by_name

    model = config.agents.defaults.model
    provider_name = config.get_provider_name(model)
    p = config.get_provider(model)
    spec = find_by_name(provider_name) if provider_name else None
    backend = spec.backend if spec else "openai_compat"

    if backend == "azure_openai":
        if not p or not p.api_key or not p.api_base:
            raise ValueError("Azure OpenAI requires api_key and api_base in config.")
    elif backend == "openai_compat" and not model.startswith("bedrock/"):
        needs_key = not (p and p.api_key)
        exempt = spec and (spec.is_oauth or spec.is_local or spec.is_direct)
        if needs_key and not exempt:
            raise ValueError(f"No API key configured for provider '{provider_name}'.")

    if backend == "openai_codex":
        from nanobot.providers.openai_codex_provider import OpenAICodexProvider

        provider = OpenAICodexProvider(default_model=model)
    elif backend == "azure_openai":
        from nanobot.providers.azure_openai_provider import AzureOpenAIProvider

        provider = AzureOpenAIProvider(
            api_key=p.api_key, api_base=p.api_base, default_model=model
        )
    elif backend == "anthropic":
        from nanobot.providers.anthropic_provider import AnthropicProvider

        provider = AnthropicProvider(
            api_key=p.api_key if p else None,
            api_base=config.get_api_base(model),
            default_model=model,
            extra_headers=p.extra_headers if p else None,
        )
    else:
        from nanobot.providers.openai_compat_provider import OpenAICompatProvider

        provider = OpenAICompatProvider(
            api_key=p.api_key if p else None,
            api_base=config.get_api_base(model),
            default_model=model,
            extra_headers=p.extra_headers if p else None,
            spec=spec,
        )

    defaults = config.agents.defaults
    provider.generation = GenerationSettings(
        temperature=defaults.temperature,
        max_tokens=defaults.max_tokens,
        reasoning_effort=defaults.reasoning_effort,
    )

    # 链式 fallback：primary 挂了自动降级
    if defaults.fallback_models:
        provider = _wrap_with_fallback(config, provider, defaults)

    return provider


def _make_single_provider(config: Any, model: str) -> Any:
    """Create a single LLM provider for the given model string.

    Supports explicit provider prefix: "openrouter_custom/claude-sonnet-4" will
    look up providers.openrouter_custom directly, bypassing keyword matching.
    """
    from nanobot.providers.registry import find_by_name

    # 显式 provider prefix 匹配：model 前缀是 config field name 时直接使用
    provider_name = None
    p = None
    spec = None
    if "/" in model:
        prefix = model.split("/", 1)[0].replace("-", "_")
        candidate = getattr(config.providers, prefix, None)
        if candidate is not None and hasattr(candidate, "api_key"):
            spec = find_by_name(prefix)
            if candidate.api_key or (spec and (spec.is_oauth or spec.is_local or spec.is_direct)):
                provider_name = prefix
                p = candidate

    # 回退到自动匹配
    if not provider_name:
        provider_name = config.get_provider_name(model)
        p = config.get_provider(model)
        spec = find_by_name(provider_name) if provider_name else None

    backend = spec.backend if spec else "openai_compat"

    if not p or (not p.api_key and not (spec and (spec.is_oauth or spec.is_local or spec.is_direct))):
        raise ValueError(f"No provider configured for fallback model '{model}'")

    # api_base: 优先 provider config 的显式配置，回退到 registry 默认
    api_base = p.api_base or config.get_api_base(model) or (spec.default_api_base if spec else None)

    if backend == "anthropic":
        from nanobot.providers.anthropic_provider import AnthropicProvider
        return AnthropicProvider(
            api_key=p.api_key,
            api_base=api_base,
            default_model=model,
            extra_headers=p.extra_headers,
        )
    else:
        from nanobot.providers.openai_compat_provider import OpenAICompatProvider
        return OpenAICompatProvider(
            api_key=p.api_key,
            api_base=api_base,
            default_model=model,
            extra_headers=p.extra_headers,
            spec=spec,
        )


def _wrap_with_fallback(config: Any, primary: Any, defaults: Any) -> Any:
    """Wrap primary provider with FallbackProvider chain."""
    from loguru import logger
    from nanobot.providers.fallback import FallbackProvider

    fallbacks = []
    for fb_model in defaults.fallback_models:
        try:
            fb_provider = _make_single_provider(config, fb_model)
        except Exception as e:
            logger.warning("Skipping fallback model {}: {}", fb_model, e)
            continue
        fallbacks.append((fb_provider, fb_model))

    if not fallbacks:
        return primary

    fb = FallbackProvider(
        primary=primary,
        fallbacks=fallbacks,
        cooldown_s=defaults.fallback_cooldown_s,
    )
    fb.generation = primary.generation
    return fb
