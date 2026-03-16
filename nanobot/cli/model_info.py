"""Model information helpers for the onboard wizard.

Provides model context window lookup and autocomplete suggestions using litellm.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

import litellm


@lru_cache(maxsize=1)
def _get_model_cost_map() -> dict[str, Any]:
    """Get litellm's model cost map (cached)."""
    return getattr(litellm, "model_cost", {})


@lru_cache(maxsize=1)
def get_all_models() -> list[str]:
    """Get all known model names from litellm.
    """
    models = set()

    # From model_cost (has pricing info)
    cost_map = _get_model_cost_map()
    for k in cost_map.keys():
        if k != "sample_spec":
            models.add(k)

    # From models_by_provider (more complete provider coverage)
    for provider_models in getattr(litellm, "models_by_provider", {}).values():
        if isinstance(provider_models, (set, list)):
            models.update(provider_models)

    return sorted(models)


def _normalize_model_name(model: str) -> str:
    """Normalize model name for comparison."""
    return model.lower().replace("-", "_").replace(".", "")


def find_model_info(model_name: str) -> dict[str, Any] | None:
    """Find model info with fuzzy matching.

    Args:
        model_name: Model name in any common format

    Returns:
        Model info dict or None if not found
    """
    cost_map = _get_model_cost_map()
    if not cost_map:
        return None

    # Direct match
    if model_name in cost_map:
        return cost_map[model_name]

    # Extract base name (without provider prefix)
    base_name = model_name.split("/")[-1] if "/" in model_name else model_name
    base_normalized = _normalize_model_name(base_name)

    candidates = []

    for key, info in cost_map.items():
        if key == "sample_spec":
            continue

        key_base = key.split("/")[-1] if "/" in key else key
        key_base_normalized = _normalize_model_name(key_base)

        # Score the match
        score = 0

        # Exact base name match (highest priority)
        if base_normalized == key_base_normalized:
            score = 100
        # Base name contains model
        elif base_normalized in key_base_normalized:
            score = 80
        # Model contains base name
        elif key_base_normalized in base_normalized:
            score = 70
        # Partial match
        elif base_normalized[:10] in key_base_normalized:
            score = 50

        if score > 0:
            # Prefer models with max_input_tokens
            if info.get("max_input_tokens"):
                score += 10
            candidates.append((score, key, info))

    if not candidates:
        return None

    # Return the best match
    candidates.sort(key=lambda x: (-x[0], x[1]))
    return candidates[0][2]


def get_model_context_limit(model: str, provider: str = "auto") -> int | None:
    """Get the maximum input context tokens for a model.

    Args:
        model: Model name (e.g., "claude-3.5-sonnet", "gpt-4o")
        provider: Provider name for informational purposes (not yet used for filtering)

    Returns:
        Maximum input tokens, or None if unknown

    Note:
        The provider parameter is currently informational only. Future versions may
        use it to prefer provider-specific model variants in the lookup.
    """
    # First try fuzzy search in model_cost (has more accurate max_input_tokens)
    info = find_model_info(model)
    if info:
        # Prefer max_input_tokens (this is what we want for context window)
        max_input = info.get("max_input_tokens")
        if max_input and isinstance(max_input, int):
            return max_input

    # Fall back to litellm's get_max_tokens (returns max_output_tokens typically)
    try:
        result = litellm.get_max_tokens(model)
        if result and result > 0:
            return result
    except (KeyError, ValueError, AttributeError):
        # Model not found in litellm's database or invalid response
        pass

    # Last resort: use max_tokens from model_cost
    if info:
        max_tokens = info.get("max_tokens")
        if max_tokens and isinstance(max_tokens, int):
            return max_tokens

    return None


@lru_cache(maxsize=1)
def _get_provider_keywords() -> dict[str, list[str]]:
    """Build provider keywords mapping from nanobot's provider registry.

    Returns:
        Dict mapping provider name to list of keywords for model filtering.
    """
    try:
        from nanobot.providers.registry import PROVIDERS

        mapping = {}
        for spec in PROVIDERS:
            if spec.keywords:
                mapping[spec.name] = list(spec.keywords)
        return mapping
    except ImportError:
        return {}


def get_model_suggestions(partial: str, provider: str = "auto", limit: int = 20) -> list[str]:
    """Get autocomplete suggestions for model names.

    Args:
        partial: Partial model name typed by user
        provider: Provider name for filtering (e.g., "openrouter", "minimax")
        limit: Maximum number of suggestions to return

    Returns:
        List of matching model names
    """
    all_models = get_all_models()
    if not all_models:
        return []

    partial_lower = partial.lower()
    partial_normalized = _normalize_model_name(partial)

    # Get provider keywords from registry
    provider_keywords = _get_provider_keywords()

    # Filter by provider if specified
    allowed_keywords = None
    if provider and provider != "auto":
        allowed_keywords = provider_keywords.get(provider.lower())

    matches = []

    for model in all_models:
        model_lower = model.lower()

        # Apply provider filter
        if allowed_keywords:
            if not any(kw in model_lower for kw in allowed_keywords):
                continue

        # Match against partial input
        if not partial:
            matches.append(model)
            continue

        if partial_lower in model_lower:
            # Score by position of match (earlier = better)
            pos = model_lower.find(partial_lower)
            score = 100 - pos
            matches.append((score, model))
        elif partial_normalized in _normalize_model_name(model):
            score = 50
            matches.append((score, model))

    # Sort by score if we have scored matches
    if matches and isinstance(matches[0], tuple):
        matches.sort(key=lambda x: (-x[0], x[1]))
        matches = [m[1] for m in matches]
    else:
        matches.sort()

    return matches[:limit]


def format_token_count(tokens: int) -> str:
    """Format token count for display (e.g., 200000 -> '200,000')."""
    return f"{tokens:,}"
