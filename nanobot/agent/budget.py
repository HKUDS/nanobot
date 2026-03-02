"""Token budget allocator for context window management."""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from nanobot.config.schema import TokenBudgetConfig

_CONTEXT_WINDOW_FALLBACK: dict[str, int] = {
    "gpt-4o": 128000,
    "gpt-4o-mini": 128000,
    "gpt-4-turbo": 128000,
    "gpt-3.5-turbo": 16385,
    "claude-3-5-sonnet": 200000,
    "claude-3-opus": 200000,
    "claude-3-sonnet": 200000,
    "claude-3-haiku": 200000,
    "anthropic/claude-opus-4-5": 200000,
    "anthropic/claude-sonnet-4": 200000,
}

_DEFAULT_CONTEXT_WINDOW = 128000

_encoding_cache = None


def _get_encoding():
    """Lazy-load tiktoken encoding. Uses cl100k_base (OpenAI-style) for broad compatibility."""
    global _encoding_cache
    if _encoding_cache is not None:
        return _encoding_cache
    try:
        import tiktoken
        _encoding_cache = tiktoken.get_encoding("cl100k_base")
        return _encoding_cache
    except Exception as e:
        logger.debug("TokenBudget: tiktoken unavailable, using char estimate: {}", e)
        return None


@lru_cache(maxsize=32)
def get_context_window(model: str | None) -> int:
    """Return the model's context window size (max input tokens). Cached per model."""
    if not model:
        return _DEFAULT_CONTEXT_WINDOW
    try:
        from litellm import get_max_tokens
        out = get_max_tokens(model=model)
        if out is not None and isinstance(out, (int, float)):
            logger.debug("TokenBudget: context window for '{}' = {} (from LiteLLM)", model, int(out))
            return int(out)
    except Exception:
        pass
    model_lower = model.lower().strip()
    for key, size in _CONTEXT_WINDOW_FALLBACK.items():
        if key in model_lower or model_lower.replace("-", "_") == key.replace("-", "_"):
            logger.debug("TokenBudget: context window for '{}' = {} (fallback)", model, size)
            return size
    logger.debug("TokenBudget: unknown model '{}', using default context window {}", model, _DEFAULT_CONTEXT_WINDOW)
    return _DEFAULT_CONTEXT_WINDOW


def count_tokens(text: str) -> int:
    """Count tokens in text. Uses tiktoken if available, else ~chars/4 estimate."""
    enc = _get_encoding()
    if enc is not None:
        return len(enc.encode(text))
    return max(1, len(text) // 4)


def truncate_to_budget(text: str, budget: int) -> str:
    """Truncate text to fit within token budget, preferring sentence boundaries."""
    if not text or budget <= 0:
        return ""
    current = count_tokens(text)
    if current <= budget:
        return text
    logger.debug("TokenBudget: truncating text from {} to {} tokens", current, budget)
    # Binary-search style: take progressively less until we fit
    ratio = budget / current
    target_chars = int(len(text) * ratio * 0.95)
    truncated = text[:target_chars]
    while count_tokens(truncated) > budget and target_chars > 0:
        target_chars -= 100
        truncated = text[:target_chars]
    if count_tokens(truncated) <= budget:
        # Try to end at a sentence boundary
        last_period = truncated.rfind(".")
        if last_period > target_chars // 2:
            candidate = truncated[: last_period + 1]
            if count_tokens(candidate) <= budget:
                return candidate
        return truncated.rstrip() + "\n... (truncated)"
    return truncated.rstrip() + "\n... (truncated)"


class TokenBudget:
    """
    Allocates token budgets per section and provides count/truncate helpers.
    """

    def __init__(
        self,
        model: str | None,
        max_tokens: int,
        token_budget_config: TokenBudgetConfig | None = None,
    ):
        from nanobot.config.schema import TokenBudgetConfig
        self.model = model
        self.max_tokens = max_tokens
        self.config = token_budget_config or TokenBudgetConfig()
        self._context_window = get_context_window(model)
        self._allocated: dict[str, int] = self._compute_allocation()

    def _compute_allocation(self) -> dict[str, int]:
        """Compute per-section token budgets using cached context window."""
        from nanobot.config.schema import TokenBudgetConfig
        cfg = self.config
        if not isinstance(cfg, TokenBudgetConfig):
            cfg = TokenBudgetConfig()
        reserved = (
            cfg.identity
            + cfg.memory
            + cfg.history_summary
            + cfg.bootstrap
            + cfg.tools
            + self.max_tokens
        )
        remaining = max(0, self._context_window - reserved)
        conversation = cfg.conversation if cfg.conversation > 0 else remaining
        return {
            "identity": cfg.identity,
            "memory": cfg.memory,
            "history_summary": cfg.history_summary,
            "conversation": min(conversation, remaining) if remaining else 0,
            "bootstrap": cfg.bootstrap,
            "tools": cfg.tools,
        }

    @property
    def context_window(self) -> int:
        return self._context_window

    def count_tokens(self, text: str) -> int:
        return count_tokens(text)

    def fits(self, text: str, section: str) -> bool:
        """Return True if text fits within the section's budget."""
        budget = self._allocated.get(section, 0)
        return budget > 0 and count_tokens(text) <= budget

    def truncate(self, text: str, section: str) -> str:
        """Truncate text to fit the section's budget."""
        budget = self._allocated.get(section, 0)
        return truncate_to_budget(text, budget) if budget > 0 else ""

    def get_budget(self, section: str) -> int:
        return self._allocated.get(section, 0)

    def remaining_after(self, *sections: str) -> int:
        """Sum of budgets for sections not listed (for 'conversation' fill)."""
        return sum(
            v for k, v in self._allocated.items()
            if k not in sections
        )
