"""Token usage and cost tracking."""

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.utils.helpers import ensure_dir


@dataclass
class UsageEntry:
    """A single usage entry."""

    timestamp: float
    model: str
    provider: str
    prompt_tokens: int
    completion_tokens: int
    cached_tokens: int = 0
    session_key: str | None = None
    cost: float = 0.0


# Pricing per 1M tokens (USD)
# Source: Common provider prices as of May 2024 (approximate)
PRICING = {
    # Gemini (Google)
    "gemini-1.5-pro": {"prompt": 3.5, "completion": 10.5},
    "gemini-1.5-flash": {"prompt": 0.35, "completion": 1.05},
    "gemini-1.0-pro": {"prompt": 0.5, "completion": 1.5},
    # OpenAI
    "o1": {"prompt": 15.0, "completion": 60.0},
    "gpt-4o": {"prompt": 5.0, "completion": 15.0},
    "gpt-4o-mini": {"prompt": 0.15, "completion": 0.60},
    "gpt-4-turbo": {"prompt": 10.0, "completion": 30.0},
    "gpt-4": {"prompt": 30.0, "completion": 60.0},
    "gpt-3.5-turbo": {"prompt": 0.5, "completion": 1.5},
    # Anthropic
    "claude-3-5-sonnet": {"prompt": 3.0, "completion": 15.0},
    "claude-3-opus": {"prompt": 15.0, "completion": 75.0},
    "claude-3-sonnet": {"prompt": 3.0, "completion": 15.0},
    "claude-3-haiku": {"prompt": 0.25, "completion": 1.25},
    # DeepSeek
    "deepseek-chat": {"prompt": 0.14, "completion": 0.28},
    "deepseek-coder": {"prompt": 0.14, "completion": 0.28},
    "deepseek-v3": {"prompt": 0.14, "completion": 0.28},
    # Groq (Llama 3)
    "llama-3.1-70b": {"prompt": 0.59, "completion": 0.79},
    "llama-3.1-8b": {"prompt": 0.05, "completion": 0.08},
}


def calculate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Calculate the cost of a turn based on model pricing."""
    # Try exact match first, then prefix match
    price = PRICING.get(model)
    if not price:
        for pattern, p in PRICING.items():
            if model.startswith(pattern):
                price = p
                break

    if not price:
        return 0.0

    prompt_cost = (prompt_tokens / 1_000_000) * price["prompt"]
    completion_cost = (completion_tokens / 1_000_000) * price["completion"]
    return prompt_cost + completion_cost


class UsageManager:
    """Manages token usage logging and aggregation."""

    def __init__(self, workspace: Path):
        self.workspace = workspace
        self.usage_file = workspace / "usage.jsonl"

    def log_usage(
        self,
        model: str,
        provider: str,
        prompt_tokens: int,
        completion_tokens: int,
        cached_tokens: int = 0,
        session_key: str | None = None,
    ) -> None:
        """Log a new usage entry."""
        if prompt_tokens <= 0 and completion_tokens <= 0:
            return

        cost = calculate_cost(model, prompt_tokens, completion_tokens)
        entry = UsageEntry(
            timestamp=time.time(),
            model=model,
            provider=provider,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cached_tokens=cached_tokens,
            session_key=session_key,
            cost=cost,
        )

        try:
            with open(self.usage_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(asdict(entry), ensure_ascii=False) + "\n")
        except Exception as e:
            logger.warning("Failed to log usage: {}", e)

    def get_summary(self) -> dict[str, Any]:
        """Get aggregated usage stats."""
        total_prompt = 0
        total_completion = 0
        total_cached = 0
        total_cost = 0.0
        total_messages = 0
        
        model_stats: dict[str, dict[str, Any]] = {}
        daily_stats: dict[str, dict[str, Any]] = {}

        if not self.usage_file.exists():
            return {
                "total": {
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "cached_tokens": 0,
                    "cost": 0.0,
                    "messages": 0,
                },
                "by_model": {},
                "by_day": {},
            }

        try:
            with open(self.usage_file, encoding="utf-8") as f:
                for line in f:
                    data = json.loads(line)
                    total_prompt += data["prompt_tokens"]
                    total_completion += data["completion_tokens"]
                    total_cached += data.get("cached_tokens", 0)
                    total_cost += data["cost"]
                    total_messages += 1

                    # Model aggregation
                    m = data["model"]
                    ms = model_stats.setdefault(m, {"prompt_tokens": 0, "completion_tokens": 0, "cost": 0.0, "messages": 0})
                    ms["prompt_tokens"] += data["prompt_tokens"]
                    ms["completion_tokens"] += data["completion_tokens"]
                    ms["cost"] += data["cost"]
                    ms["messages"] += 1

                    # Daily aggregation
                    day = time.strftime("%Y-%m-%d", time.localtime(data["timestamp"]))
                    ds = daily_stats.setdefault(day, {"prompt_tokens": 0, "completion_tokens": 0, "cost": 0.0, "messages": 0})
                    ds["prompt_tokens"] += data["prompt_tokens"]
                    ds["completion_tokens"] += data["completion_tokens"]
                    ds["cost"] += data["cost"]
                    ds["messages"] += 1

            return {
                "total": {
                    "prompt_tokens": total_prompt,
                    "completion_tokens": total_completion,
                    "cached_tokens": total_cached,
                    "cost": round(total_cost, 4),
                    "messages": total_messages,
                },
                "by_model": model_stats,
                "by_day": daily_stats,
            }
        except Exception as e:
            logger.warning("Failed to read usage stats: {}", e)
            return {"error": str(e)}
