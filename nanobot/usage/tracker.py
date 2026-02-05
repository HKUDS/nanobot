"""Token usage tracker for monitoring LLM API consumption."""

import json
from pathlib import Path
from datetime import datetime, date
from dataclasses import dataclass, field, asdict
from typing import Any

from loguru import logger

from nanobot.utils.helpers import ensure_dir


@dataclass
class UsageRecord:
    """A single usage record for an LLM call."""
    
    timestamp: str
    session_key: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    metadata: dict[str, Any] = field(default_factory=dict)
    
    @property
    def date(self) -> str:
        """Get the date (YYYY-MM-DD) of this record."""
        return self.timestamp.split("T")[0]


@dataclass
class UsageStats:
    """Aggregated usage statistics."""
    
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    call_count: int = 0
    
    def add(self, record: UsageRecord) -> None:
        """Add a usage record to the stats."""
        self.prompt_tokens += record.prompt_tokens
        self.completion_tokens += record.completion_tokens
        self.total_tokens += record.total_tokens
        self.call_count += 1
    
    def to_dict(self) -> dict[str, int]:
        """Convert to dictionary."""
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "call_count": self.call_count,
        }


class UsageTracker:
    """
    Track and persist token usage statistics.
    
    Stores usage data in JSON format with the following structure:
    {
        "total": {"prompt_tokens": 1000, "completion_tokens": 500, ...},
        "sessions": {
            "cli:default": {"prompt_tokens": 100, ...}
        },
        "daily": {
            "2026-02-05": {"prompt_tokens": 500, ...}
        },
        "records": [
            {"timestamp": "...", "session_key": "...", "model": "...", ...}
        ]
    }
    """
    
    def __init__(self, data_dir: Path | None = None):
        """
        Initialize the usage tracker.
        
        Args:
            data_dir: Directory to store usage data. Defaults to ~/.nanobot/usage
        """
        self.data_dir = data_dir or ensure_dir(Path.home() / ".nanobot" / "usage")
        self.stats_file = self.data_dir / "stats.json"
        
        # In-memory cache
        self._total = UsageStats()
        self._sessions: dict[str, UsageStats] = {}
        self._daily: dict[str, UsageStats] = {}
        self._records: list[UsageRecord] = []
        
        # Load existing data
        self._load()
    
    def track(
        self,
        session_key: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int | None = None,
        **metadata: Any
    ) -> None:
        """
        Track a single LLM API call.
        
        Args:
            session_key: Session identifier (e.g., "cli:default")
            model: Model name (e.g., "anthropic/claude-opus-4-5")
            prompt_tokens: Number of prompt tokens
            completion_tokens: Number of completion tokens
            total_tokens: Total tokens (auto-calculated if None)
            **metadata: Additional metadata to store
        """
        if total_tokens is None:
            total_tokens = prompt_tokens + completion_tokens
        
        # Create record
        record = UsageRecord(
            timestamp=datetime.now().isoformat(),
            session_key=session_key,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            metadata=metadata
        )
        
        # Update stats
        self._total.add(record)
        
        if session_key not in self._sessions:
            self._sessions[session_key] = UsageStats()
        self._sessions[session_key].add(record)
        
        record_date = record.date
        if record_date not in self._daily:
            self._daily[record_date] = UsageStats()
        self._daily[record_date].add(record)
        
        # Store record
        self._records.append(record)
        
        # Persist to disk periodically to reduce I/O overhead
        # Save every 10 records or when total is divisible by 10
        if len(self._records) % 10 == 0:
            self._save()
        
        logger.debug(
            f"Tracked usage: {session_key} | {model} | "
            f"{prompt_tokens}+{completion_tokens}={total_tokens} tokens"
        )
    
    def get_total(self) -> dict[str, int]:
        """Get total usage statistics."""
        return self._total.to_dict()
    
    def get_session(self, session_key: str) -> dict[str, int] | None:
        """Get usage statistics for a specific session."""
        stats = self._sessions.get(session_key)
        return stats.to_dict() if stats else None
    
    def get_daily(self, date_str: str | None = None) -> dict[str, int] | None:
        """
        Get usage statistics for a specific date.
        
        Args:
            date_str: Date in YYYY-MM-DD format. Defaults to today.
        """
        if date_str is None:
            date_str = date.today().isoformat()
        
        stats = self._daily.get(date_str)
        return stats.to_dict() if stats else None
    
    def get_week(self) -> dict[str, int]:
        """Get usage statistics for the current week."""
        from datetime import timedelta
        
        today = date.today()
        week_start = today - timedelta(days=today.weekday())
        
        week_stats = UsageStats()
        for i in range(7):
            day = week_start + timedelta(days=i)
            day_str = day.isoformat()
            if day_str in self._daily:
                daily = self._daily[day_str]
                week_stats.prompt_tokens += daily.prompt_tokens
                week_stats.completion_tokens += daily.completion_tokens
                week_stats.total_tokens += daily.total_tokens
                week_stats.call_count += daily.call_count
        
        return week_stats.to_dict()
    
    def get_all_sessions(self) -> dict[str, dict[str, int]]:
        """Get usage statistics for all sessions."""
        return {key: stats.to_dict() for key, stats in self._sessions.items()}
    
    def export(self) -> dict[str, Any]:
        """
        Export all usage data.
        
        Returns:
            Dictionary with all usage data including records.
        """
        return {
            "total": self._total.to_dict(),
            "sessions": {k: v.to_dict() for k, v in self._sessions.items()},
            "daily": {k: v.to_dict() for k, v in self._daily.items()},
            "records": [asdict(r) for r in self._records],
        }
    
    def clear(self) -> None:
        """Clear all usage data."""
        self._total = UsageStats()
        self._sessions = {}
        self._daily = {}
        self._records = []
        self._save()
        logger.info("Cleared all usage data")
    
    def _load(self) -> None:
        """Load usage data from disk."""
        if not self.stats_file.exists():
            return
        
        try:
            with open(self.stats_file) as f:
                data = json.load(f)
            
            # Load total stats
            if "total" in data:
                self._total = UsageStats(**data["total"])
            
            # Load session stats
            if "sessions" in data:
                self._sessions = {
                    key: UsageStats(**stats)
                    for key, stats in data["sessions"].items()
                }
            
            # Load daily stats
            if "daily" in data:
                self._daily = {
                    key: UsageStats(**stats)
                    for key, stats in data["daily"].items()
                }
            
            # Load records
            if "records" in data:
                self._records = [
                    UsageRecord(**record)
                    for record in data["records"]
                ]
            
            logger.debug(f"Loaded usage data: {self._total.call_count} total calls")
        except Exception as e:
            logger.warning(f"Failed to load usage data: {e}")
    
    def _save(self) -> None:
        """Save usage data to disk."""
        try:
            data = self.export()
            with open(self.stats_file, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save usage data: {e}")
