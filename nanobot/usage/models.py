"""Usage tracking data models."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class UsageRecord:
    """
    Single LLM API call usage record.
    
    Captures token counts, cost, and metadata for a single API call.
    """
    
    timestamp: str  # ISO format: YYYY-MM-DDTHH:MM:SS
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost_usd: float
    channel: str = "cli"
    session_key: str = ""
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "timestamp": self.timestamp,
            "model": self.model,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "cost_usd": self.cost_usd,
            "channel": self.channel,
            "session_key": self.session_key,
        }
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "UsageRecord":
        """Create from dictionary."""
        return cls(
            timestamp=data.get("timestamp", ""),
            model=data.get("model", ""),
            prompt_tokens=data.get("prompt_tokens", 0),
            completion_tokens=data.get("completion_tokens", 0),
            total_tokens=data.get("total_tokens", 0),
            cost_usd=data.get("cost_usd", 0.0),
            channel=data.get("channel", "cli"),
            session_key=data.get("session_key", ""),
        )


@dataclass
class DailySummary:
    """
    Daily usage summary.
    
    Aggregates all usage records for a single day.
    """
    
    date: str  # YYYY-MM-DD
    total_requests: int = 0
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    records: list[UsageRecord] = field(default_factory=list)
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "date": self.date,
            "total_requests": self.total_requests,
            "total_prompt_tokens": self.total_prompt_tokens,
            "total_completion_tokens": self.total_completion_tokens,
            "total_tokens": self.total_tokens,
            "total_cost_usd": self.total_cost_usd,
            "records": [r.to_dict() for r in self.records],
        }
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DailySummary":
        """Create from dictionary."""
        records = [UsageRecord.from_dict(r) for r in data.get("records", [])]
        return cls(
            date=data.get("date", ""),
            total_requests=data.get("total_requests", len(records)),
            total_prompt_tokens=data.get("total_prompt_tokens", 0),
            total_completion_tokens=data.get("total_completion_tokens", 0),
            total_tokens=data.get("total_tokens", 0),
            total_cost_usd=data.get("total_cost_usd", 0.0),
            records=records,
        )
    
    def add_record(self, record: UsageRecord) -> None:
        """Add a record and update totals."""
        self.records.append(record)
        self.total_requests += 1
        self.total_prompt_tokens += record.prompt_tokens
        self.total_completion_tokens += record.completion_tokens
        self.total_tokens += record.total_tokens
        self.total_cost_usd += record.cost_usd
