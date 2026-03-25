"""Model information helpers for the onboard wizard.

Model database / autocomplete is temporarily disabled while litellm is
being replaced. All public function signatures are preserved so callers
continue to work without changes.
"""

from __future__ import annotations

from typing import Any


def get_all_models() -> list[str]:
    return []


def find_model_info(model_name: str) -> dict[str, Any] | None:
    return None


def get_model_context_limit(model: str, provider: str = "auto") -> int | None:
    return None


def get_model_suggestions(partial: str, provider: str = "auto", limit: int = 20) -> list[str]:
    return []


def format_token_count(tokens: int) -> str:
    """Format token count for display (e.g., 200000 -> '200,000')."""
    return f"{tokens:,}"
