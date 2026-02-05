"""Provider resolver for multi-provider routing."""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from nanobot.config.schema import ProvidersConfig

# Known provider API bases (applied when no explicit api_base is set)
_DEFAULT_API_BASES: dict[str, str] = {
    "openrouter": "https://openrouter.ai/api/v1",
}


class ProviderResolver:
    """Resolves provider credentials by name from config.

    Subsystems (embedding, compaction, extraction, consolidation) each specify
    an optional provider name. The resolver maps that name to (api_key, api_base)
    from the providers config section, falling back to priority-based resolution
    when no name is given.
    """

    def __init__(
        self,
        providers: ProvidersConfig,
        default_provider: str | None = None,
    ):
        """
        Args:
            providers: The ProvidersConfig from the root config.
            default_provider: Default provider name (from agents.defaults.provider).
        """
        self.providers = providers
        self.default_provider = default_provider

    def resolve(self, name: str | None = None) -> tuple[str | None, str | None]:
        """Return (api_key, api_base) for a named or default provider.

        Resolution chain:
          1. If ``name`` is given and matches a configured provider, use it.
          2. Otherwise fall back to ``self.default_provider``.
          3. If neither yields a result, fall back to priority-based scanning.

        Args:
            name: Explicit provider name to resolve.

        Returns:
            Tuple of (api_key, api_base). Either may be None.
        """
        # Try explicit name first, then default_provider
        for target in (name, self.default_provider):
            if not target:
                continue
            provider = getattr(self.providers, target, None)
            if provider and provider.api_key:
                api_base = provider.api_base
                if target in _DEFAULT_API_BASES and not api_base:
                    api_base = _DEFAULT_API_BASES[target]
                logger.debug(f"Resolved provider '{target}'")
                return provider.api_key, api_base

        # Fallback: priority-based scanning (matches Config.get_api_key order)
        return self._fallback_resolve()

    def _fallback_resolve(self) -> tuple[str | None, str | None]:
        """Priority-based provider resolution (existing behavior)."""
        p = self.providers
        priority = [
            ("openrouter", p.openrouter),
            ("anthropic", p.anthropic),
            ("openai", p.openai),
            ("gemini", p.gemini),
            ("zhipu", p.zhipu),
            ("groq", p.groq),
            ("vllm", p.vllm),
        ]
        for name, provider in priority:
            if provider.api_key:
                api_base = provider.api_base
                if name in _DEFAULT_API_BASES and not api_base:
                    api_base = _DEFAULT_API_BASES[name]
                return provider.api_key, api_base

        # vLLM special case: may have api_base without api_key
        if p.vllm.api_base:
            return None, p.vllm.api_base

        return None, None
