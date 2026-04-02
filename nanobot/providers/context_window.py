"""Context window auto-detection with fallback chain.

Priority: API dynamic fetch > lookup table > user config > hard default.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

from nanobot.cli.models import get_model_context_limit

if TYPE_CHECKING:
    from nanobot.providers.base import LLMProvider

_HARD_DEFAULT = 65_536


async def resolve_context_window(
    provider: LLMProvider,
    model: str,
    configured_value: int,
) -> tuple[int, str]:
    """Resolve context window tokens with fallback chain.

    Priority: API > lookup table > user config > hard default (65536).
    Returns (tokens, source) where source is "api" | "lookup" | "config" | "default".
    """
    # 1. Try API (async, with timeout handled inside provider)
    try:
        api_value = await provider.fetch_model_context_window(model)
        if api_value and api_value > 0:
            logger.info(
                "Context window: {:,} tokens (source: api, model: {})",
                api_value, model,
            )
            return api_value, "api"
    except Exception:
        logger.debug("API context window fetch failed for {}", model)

    # 2. Try lookup table
    lookup_value = get_model_context_limit(model)
    if lookup_value:
        logger.info(
            "Context window: {:,} tokens (source: lookup, model: {})",
            lookup_value, model,
        )
        return lookup_value, "lookup"

    # 3. Use user-configured value (if non-zero)
    if configured_value > 0:
        logger.info(
            "Context window: {:,} tokens (source: config, model: {})",
            configured_value, model,
        )
        return configured_value, "config"

    # 4. Hard default
    logger.warning(
        "Context window: {:,} tokens (source: default — consider setting "
        "contextWindowTokens in config, model: {})",
        _HARD_DEFAULT, model,
    )
    return _HARD_DEFAULT, "default"


def resolve_context_window_sync(
    model: str,
    configured_value: int,
) -> tuple[int, str]:
    """Synchronous resolve — lookup table + config only, no API call.

    Used by Nanobot.from_config() which is a sync method.
    """
    lookup_value = get_model_context_limit(model)
    if lookup_value:
        logger.info(
            "Context window: {:,} tokens (source: lookup, model: {})",
            lookup_value, model,
        )
        return lookup_value, "lookup"

    if configured_value > 0:
        logger.info(
            "Context window: {:,} tokens (source: config, model: {})",
            configured_value, model,
        )
        return configured_value, "config"

    logger.warning(
        "Context window: {:,} tokens (source: default — consider setting "
        "contextWindowTokens in config, model: {})",
        _HARD_DEFAULT, model,
    )
    return _HARD_DEFAULT, "default"
