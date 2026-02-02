"""Usage tracking and storage."""

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.usage.models import DailySummary, UsageRecord
from nanobot.utils.helpers import ensure_dir


class UsageTracker:
    """
    Tracks and stores LLM API usage.
    
    Usage data is stored as daily JSON files in ~/.nanobot/usage/.
    Each file contains all API calls for that day with their token
    counts and costs.
    """
    
    def __init__(self, data_dir: Path | None = None):
        """
        Initialize the usage tracker.
        
        Args:
            data_dir: Base data directory. Defaults to ~/.nanobot
        """
        if data_dir is None:
            data_dir = Path.home() / ".nanobot"
        self.usage_dir = ensure_dir(data_dir / "usage")
    
    def _get_file_path(self, date: str) -> Path:
        """Get the file path for a specific date."""
        return self.usage_dir / f"{date}.json"
    
    def _today(self) -> str:
        """Get today's date string."""
        return datetime.now().strftime("%Y-%m-%d")
    
    def _load_daily(self, date: str) -> DailySummary:
        """Load or create daily summary for a date."""
        file_path = self._get_file_path(date)
        
        if file_path.exists():
            try:
                data = json.loads(file_path.read_text(encoding="utf-8"))
                return DailySummary.from_dict(data)
            except (json.JSONDecodeError, KeyError) as e:
                logger.warning(f"Failed to load usage file {file_path}: {e}")
        
        return DailySummary(date=date)
    
    def _save_daily(self, summary: DailySummary) -> None:
        """Save daily summary to file."""
        file_path = self._get_file_path(summary.date)
        
        try:
            file_path.write_text(
                json.dumps(summary.to_dict(), indent=2, ensure_ascii=False),
                encoding="utf-8"
            )
        except Exception as e:
            logger.error(f"Failed to save usage file {file_path}: {e}")
    
    def record(
        self,
        model: str,
        usage: dict[str, int],
        cost_usd: float,
        channel: str = "cli",
        session_key: str = "",
    ) -> UsageRecord:
        """
        Record a single API call.
        
        Args:
            model: Model name (e.g., 'anthropic/claude-opus-4')
            usage: Dict with 'prompt_tokens', 'completion_tokens', 'total_tokens'
            cost_usd: Cost in USD
            channel: Source channel (cli, telegram, whatsapp)
            session_key: Session identifier
        
        Returns:
            The created UsageRecord
        """
        now = datetime.now()
        date_str = now.strftime("%Y-%m-%d")
        
        record = UsageRecord(
            timestamp=now.isoformat(timespec="seconds"),
            model=model,
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            total_tokens=usage.get("total_tokens", 0),
            cost_usd=cost_usd,
            channel=channel,
            session_key=session_key,
        )
        
        # Load, update, save
        summary = self._load_daily(date_str)
        summary.add_record(record)
        self._save_daily(summary)
        
        logger.debug(
            f"Recorded usage: {model} - {record.total_tokens} tokens, ${cost_usd:.6f}"
        )
        
        return record
    
    def get_today(self) -> DailySummary:
        """Get today's usage summary."""
        return self._load_daily(self._today())
    
    def get_date(self, date: str) -> DailySummary:
        """
        Get usage summary for a specific date.
        
        Args:
            date: Date string in YYYY-MM-DD format
        """
        return self._load_daily(date)
    
    def get_range(self, days: int = 7) -> list[DailySummary]:
        """
        Get usage summaries for the last N days.
        
        Args:
            days: Number of days to retrieve (including today)
        
        Returns:
            List of DailySummary objects, most recent first
        """
        summaries = []
        today = datetime.now().date()
        
        for i in range(days):
            date = today - timedelta(days=i)
            date_str = date.strftime("%Y-%m-%d")
            summary = self._load_daily(date_str)
            
            # Only include days with actual usage
            if summary.total_requests > 0:
                summaries.append(summary)
        
        return summaries
    
    def get_total_cost(self, days: int = 1) -> float:
        """
        Get total cost for the last N days.
        
        Args:
            days: Number of days to sum
        
        Returns:
            Total cost in USD
        """
        summaries = self.get_range(days)
        return sum(s.total_cost_usd for s in summaries)
    
    def get_aggregate(self, days: int = 7) -> DailySummary:
        """
        Get aggregated summary for multiple days.
        
        Args:
            days: Number of days to aggregate
        
        Returns:
            Combined DailySummary (date field will be "aggregate")
        """
        from nanobot.usage.models import GroupedStats
        
        summaries = self.get_range(days)
        
        aggregate = DailySummary(date="aggregate")
        for s in summaries:
            aggregate.total_requests += s.total_requests
            aggregate.total_prompt_tokens += s.total_prompt_tokens
            aggregate.total_completion_tokens += s.total_completion_tokens
            aggregate.total_tokens += s.total_tokens
            aggregate.total_cost_usd += s.total_cost_usd
            
            # Merge model breakdowns
            for model, stats in s.by_model.items():
                if model not in aggregate.by_model:
                    aggregate.by_model[model] = GroupedStats(name=model)
                agg_stats = aggregate.by_model[model]
                agg_stats.requests += stats.requests
                agg_stats.prompt_tokens += stats.prompt_tokens
                agg_stats.completion_tokens += stats.completion_tokens
                agg_stats.total_tokens += stats.total_tokens
                agg_stats.cost_usd += stats.cost_usd
            
            # Merge channel breakdowns
            for channel, stats in s.by_channel.items():
                if channel not in aggregate.by_channel:
                    aggregate.by_channel[channel] = GroupedStats(name=channel)
                agg_stats = aggregate.by_channel[channel]
                agg_stats.requests += stats.requests
                agg_stats.prompt_tokens += stats.prompt_tokens
                agg_stats.completion_tokens += stats.completion_tokens
                agg_stats.total_tokens += stats.total_tokens
                agg_stats.cost_usd += stats.cost_usd
        
        return aggregate
    
    def get_monthly_cost(self) -> float:
        """
        Get total cost for the current month.
        
        Returns:
            Total cost in USD for this month
        """
        from datetime import date
        
        today = date.today()
        days_in_month = today.day  # Days from start of month to today
        return self.get_total_cost(days_in_month)
