"""Data models for usage tracking and cost monitoring."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional


@dataclass
class TokenUsage:
    """Token usage information from a single LLM call."""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    def cost_usd(self, provider: str = "unknown", model: str = "") -> float:
        """Calculate cost in USD based on provider and model pricing."""
        return calculate_token_cost(
            provider=provider,
            model=model,
            prompt_tokens=self.prompt_tokens,
            completion_tokens=self.completion_tokens
        )


def calculate_token_cost(
    provider: str,
    model: str,
    prompt_tokens: int,
    completion_tokens: int
) -> float:
    """
    Calculate token cost in USD based on provider and model.
    
    Uses current pricing as of late 2024. This should be updated periodically
    or made configurable for accuracy.
    """
    # Pricing per 1K tokens (as of late 2024)
    pricing = {
        "openai": {
            "gpt-4o": {"prompt": 0.0025, "completion": 0.01},
            "gpt-4o-mini": {"prompt": 0.00015, "completion": 0.0006},
            "gpt-4-turbo": {"prompt": 0.01, "completion": 0.03},
            "gpt-4": {"prompt": 0.03, "completion": 0.06},
            "gpt-3.5-turbo": {"prompt": 0.0005, "completion": 0.0015},
        },
        "anthropic": {
            "claude-3-5-sonnet": {"prompt": 0.003, "completion": 0.015},
            "claude-3-opus": {"prompt": 0.015, "completion": 0.075},
            "claude-3-haiku": {"prompt": 0.00025, "completion": 0.00125},
            "claude-3-sonnet": {"prompt": 0.003, "completion": 0.015},
        },
        "openrouter": {
            # OpenRouter pricing is dynamic, use approximate averages
            "anthropic/claude-3-5-sonnet": {"prompt": 0.003, "completion": 0.015},
            "openai/gpt-4o": {"prompt": 0.0025, "completion": 0.01},
            "openai/gpt-4o-mini": {"prompt": 0.00015, "completion": 0.0006},
        },
        "gemini": {
            "gemini-1.5-pro": {"prompt": 0.00125, "completion": 0.005},
            "gemini-1.5-flash": {"prompt": 0.000075, "completion": 0.0003},
        },
        "zhipu": {
            "glm-4": {"prompt": 0.00014, "completion": 0.00014},
            "glm-3-turbo": {"prompt": 0.00007, "completion": 0.00007},
        }
    }
    
    # Extract model name without provider prefix
    clean_model = model.split("/")[-1] if "/" in model else model
    
    # Get pricing for provider/model combination
    provider_pricing = pricing.get(provider.lower(), {})
    model_pricing = provider_pricing.get(clean_model.lower(), {})
    
    # If exact model not found, try partial matches
    if not model_pricing:
        for model_key, prices in provider_pricing.items():
            if model_key.lower() in clean_model.lower():
                model_pricing = prices
                break
    
    # If still no pricing found, use fallback based on provider
    if not model_pricing:
        fallbacks = {
            "openai": {"prompt": 0.01, "completion": 0.03},  # GPT-4 level
            "anthropic": {"prompt": 0.015, "completion": 0.075},  # Claude Opus level
            "openrouter": {"prompt": 0.01, "completion": 0.03},  # Average
            "gemini": {"prompt": 0.00125, "completion": 0.005},  # Gemini Pro level
            "zhipu": {"prompt": 0.00014, "completion": 0.00014},  # GLM-4 level
        }
        model_pricing = fallbacks.get(provider.lower(), {"prompt": 0.01, "completion": 0.03})
    
    # Calculate cost
    prompt_cost = (prompt_tokens / 1000) * model_pricing["prompt"]
    completion_cost = (completion_tokens / 1000) * model_pricing["completion"]
    
    return prompt_cost + completion_cost


@dataclass
class UsageRecord:
    """A single usage record for an LLM call."""
    timestamp: datetime
    model: str
    channel: str  # cli, telegram, whatsapp
    session_key: str
    token_usage: TokenUsage
    cost_usd: float = 0.0
    provider: Optional[str] = None  # anthropic, openai, etc.


@dataclass
class DailyUsage:
    """Usage data for a single day."""
    date: str  # YYYY-MM-DD format
    records: List[UsageRecord] = field(default_factory=list)
    total_cost_usd: float = 0.0

    def add_record(self, record: UsageRecord) -> None:
        """Add a usage record and update totals."""
        self.records.append(record)
        self.total_cost_usd += record.cost_usd

    @property
    def total_tokens(self) -> int:
        """Total tokens used today."""
        return sum(record.token_usage.total_tokens for record in self.records)

    @property
    def model_breakdown(self) -> Dict[str, int]:
        """Breakdown of usage by model."""
        breakdown = {}
        for record in self.records:
            breakdown[record.model] = breakdown.get(record.model, 0) + record.token_usage.total_tokens
        return breakdown

    @property
    def channel_breakdown(self) -> Dict[str, int]:
        """Breakdown of usage by channel."""
        breakdown = {}
        for record in self.records:
            breakdown[record.channel] = breakdown.get(record.channel, 0) + record.token_usage.total_tokens
        return breakdown


@dataclass
class UsageConfig:
    """Configuration for usage tracking and budget monitoring."""
    monthly_budget_usd: float = 20.0
    alert_thresholds: List[float] = field(default_factory=lambda: [0.5, 0.8, 1.0])

    def get_alert_levels(self) -> List[float]:
        """Get alert levels as absolute USD amounts."""
        return [self.monthly_budget_usd * threshold for threshold in self.alert_thresholds]


@dataclass
class BudgetStatus:
    """Current budget status and alerts."""
    monthly_budget_usd: float
    current_spend_usd: float
    remaining_budget_usd: float
    alert_thresholds: List[float]
    alerts: List[str] = field(default_factory=list)

    @property
    def utilization_percentage(self) -> float:
        """Current utilization as percentage."""
        if self.monthly_budget_usd == 0:
            return 0.0
        return (self.current_spend_usd / self.monthly_budget_usd) * 100

    def check_alerts(self) -> None:
        """Check if any alert thresholds have been exceeded."""
        self.alerts = []
        for threshold in self.alert_thresholds:
            if self.current_spend_usd >= threshold:
                percentage = (threshold / self.monthly_budget_usd) * 100
                self.alerts.append(".1f")

        if self.current_spend_usd >= self.monthly_budget_usd:
            self.alerts.append(f"Budget exceeded! Spent ${self.current_spend_usd:.2f} of ${self.monthly_budget_usd:.2f}")
