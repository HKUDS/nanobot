"""Model information helpers.

Provides a static lookup table for known model context windows and
helper utilities for model name normalization.
"""

from __future__ import annotations

import re
from typing import Any


# ---------------------------------------------------------------------------
# Context window lookup table
# ---------------------------------------------------------------------------

_KNOWN_CONTEXT_WINDOWS: dict[str, int] = {
    # Anthropic Claude 4.6
    "claude-opus-4-6": 1_000_000,
    "claude-sonnet-4-6": 1_000_000,
    # Anthropic Claude 4.5
    "claude-opus-4-5": 200_000,
    "claude-sonnet-4-5": 200_000,
    # Anthropic Claude 4
    "claude-opus-4": 200_000,
    "claude-sonnet-4": 200_000,
    # Anthropic Claude 3.x
    "claude-3-5-sonnet": 200_000,
    "claude-3-5-haiku": 200_000,
    "claude-3-opus": 200_000,
    "claude-3-sonnet": 200_000,
    "claude-3-haiku": 200_000,
    # OpenAI
    "gpt-4o-mini": 128_000,
    "gpt-4o": 128_000,
    "gpt-4-turbo": 128_000,
    "gpt-4": 8_192,
    "gpt-3.5-turbo": 16_385,
    "o1-mini": 128_000,
    "o1": 200_000,
    "o3-mini": 200_000,
    "o3": 200_000,
    "o4-mini": 200_000,
    # DeepSeek
    "deepseek-chat": 65_536,
    "deepseek-reasoner": 65_536,
    # Gemini
    "gemini-2.5-pro": 1_000_000,
    "gemini-2.5-flash": 1_000_000,
    "gemini-2.0-flash": 1_000_000,
    # Qwen
    "qwen-max": 131_072,
    "qwen-plus": 131_072,
    # Llama
    "llama-3.3": 131_072,
    "llama-3.2": 131_072,
    "llama-3.1": 131_072,
    # Mistral
    "mistral-large": 128_000,
}

# Pre-sorted by key length descending for longest-prefix-first matching.
_SORTED_KEYS = sorted(_KNOWN_CONTEXT_WINDOWS.keys(), key=len, reverse=True)

_DATE_SUFFIX_RE = re.compile(r"-\d{8}$")


def _normalize_model_name(model: str) -> str:
    """Strip provider prefix and date suffix from model name.

    Examples:
        "anthropic/claude-sonnet-4-6-20260301" → "claude-sonnet-4-6"
        "openrouter/anthropic/claude-sonnet-4-6" → "claude-sonnet-4-6"
        "claude-3-opus-20240229" → "claude-3-opus"
        "gpt-4o" → "gpt-4o"
    """
    # Strip provider prefix: take the last segment after "/"
    if "/" in model:
        model = model.rsplit("/", 1)[-1]
    # Strip date suffix: -YYYYMMDD
    model = _DATE_SUFFIX_RE.sub("", model)
    return model.lower()


def get_model_context_limit(model: str, provider: str = "auto") -> int | None:
    """Look up known context window for a model name.

    Returns the context window size in tokens, or None if the model is unknown.
    """
    normalized = _normalize_model_name(model)
    for key in _SORTED_KEYS:
        if normalized.startswith(key):
            return _KNOWN_CONTEXT_WINDOWS[key]
    return None


# ---------------------------------------------------------------------------
# Stubs — preserved for backward compatibility while litellm is replaced.
# ---------------------------------------------------------------------------

def get_all_models() -> list[str]:
    return []


def find_model_info(model_name: str) -> dict[str, Any] | None:
    return None


def get_model_suggestions(partial: str, provider: str = "auto", limit: int = 20) -> list[str]:
    return []


def format_token_count(tokens: int) -> str:
    """Format token count for display (e.g., 200000 -> '200,000')."""
    return f"{tokens:,}"
