"""Usage tracker for recording LLM API calls and token usage."""

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

from .models import DailyUsage, TokenUsage, UsageRecord


class UsageTracker:
    """
    Tracks LLM API usage and stores data in daily JSON files.

    Usage data is stored in ~/.nanobot/usage/YYYY-MM-DD.json
    """

    def __init__(self, data_dir: Optional[Path] = None):
        """
        Initialize the usage tracker.

        Args:
            data_dir: Directory to store usage data. Defaults to ~/.nanobot/usage
        """
        if data_dir is None:
            data_dir = Path.home() / ".nanobot" / "usage"
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def record_usage(
        self,
        model: str,
        channel: str,
        session_key: str,
        token_usage: TokenUsage,
        provider: Optional[str] = None,
        cost_usd: Optional[float] = None
    ) -> UsageRecord:
        """
        Record a usage event.

        Args:
            model: The model used (e.g., 'claude-3-5-sonnet')
            channel: The channel (cli, telegram, whatsapp)
            session_key: Unique session identifier
            token_usage: Token usage information
            provider: The provider (anthropic, openai, etc.)
            cost_usd: Cost in USD (if not provided, will be calculated)

        Returns:
            The created usage record
        """
        timestamp = datetime.now()

        # Calculate cost if not provided (placeholder - will be implemented with pricing)
        if cost_usd is None:
            cost_usd = token_usage.cost_usd

        record = UsageRecord(
            timestamp=timestamp,
            model=model,
            channel=channel,
            session_key=session_key,
            token_usage=token_usage,
            cost_usd=cost_usd,
            provider=provider
        )

        # Get or create daily usage file
        date_str = timestamp.strftime("%Y-%m-%d")
        daily_usage = self._load_daily_usage(date_str)
        daily_usage.add_record(record)

        # Save back to file
        self._save_daily_usage(daily_usage)

        return record

    def get_daily_usage(self, date_str: str) -> DailyUsage:
        """
        Get usage data for a specific date.

        Args:
            date_str: Date in YYYY-MM-DD format

        Returns:
            DailyUsage object for the date
        """
        return self._load_daily_usage(date_str)

    def get_monthly_usage(self, year: int, month: int) -> List[DailyUsage]:
        """
        Get usage data for all days in a month.

        Args:
            year: Year (e.g., 2024)
            month: Month (1-12)

        Returns:
            List of DailyUsage objects for each day in the month
        """
        usages = []
        days_in_month = self._get_days_in_month(year, month)

        for day in range(1, days_in_month + 1):
            date_str = "02d"
            usage = self._load_daily_usage(date_str)
            usages.append(usage)

        return usages

    def get_usage_summary(
        self,
        days: int = 30,
        model_filter: Optional[str] = None,
        channel_filter: Optional[str] = None
    ) -> Dict:
        """
        Get a summary of usage over the last N days.

        Args:
            days: Number of days to look back
            model_filter: Filter by specific model
            channel_filter: Filter by specific channel

        Returns:
            Dictionary with usage summary
        """
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)

        total_tokens = 0
        total_cost = 0.0
        model_breakdown = {}
        channel_breakdown = {}
        records = []

        current_date = start_date
        while current_date <= end_date:
            date_str = current_date.strftime("%Y-%m-%d")
            daily_usage = self._load_daily_usage(date_str)

            for record in daily_usage.records:
                # Apply filters
                if model_filter and record.model != model_filter:
                    continue
                if channel_filter and record.channel != channel_filter:
                    continue

                records.append(record)
                total_tokens += record.token_usage.total_tokens
                total_cost += record.cost_usd

                # Update breakdowns
                model_breakdown[record.model] = model_breakdown.get(record.model, 0) + record.token_usage.total_tokens
                channel_breakdown[record.channel] = channel_breakdown.get(record.channel, 0) + record.token_usage.total_tokens

            current_date += timedelta(days=1)

        return {
            "period_days": days,
            "total_tokens": total_tokens,
            "total_cost_usd": total_cost,
            "model_breakdown": model_breakdown,
            "channel_breakdown": channel_breakdown,
            "record_count": len(records)
        }

    def _load_daily_usage(self, date_str: str) -> DailyUsage:
        """Load daily usage from file."""
        file_path = self.data_dir / f"{date_str}.json"

        if not file_path.exists():
            return DailyUsage(date=date_str)

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            # Reconstruct DailyUsage from JSON
            records = []
            for record_data in data.get('records', []):
                # Parse timestamp
                timestamp = datetime.fromisoformat(record_data['timestamp'])

                # Reconstruct TokenUsage
                token_usage_data = record_data['token_usage']
                token_usage = TokenUsage(
                    prompt_tokens=token_usage_data['prompt_tokens'],
                    completion_tokens=token_usage_data['completion_tokens'],
                    total_tokens=token_usage_data['total_tokens']
                )

                record = UsageRecord(
                    timestamp=timestamp,
                    model=record_data['model'],
                    channel=record_data['channel'],
                    session_key=record_data['session_key'],
                    token_usage=token_usage,
                    cost_usd=record_data.get('cost_usd', 0.0),
                    provider=record_data.get('provider')
                )
                records.append(record)

            daily_usage = DailyUsage(
                date=date_str,
                records=records,
                total_cost_usd=data.get('total_cost_usd', 0.0)
            )

            return daily_usage

        except (json.JSONDecodeError, KeyError, ValueError) as e:
            # If file is corrupted, return empty usage
            print(f"Warning: Could not load usage file {file_path}: {e}")
            return DailyUsage(date=date_str)

    def _save_daily_usage(self, daily_usage: DailyUsage) -> None:
        """Save daily usage to file."""
        file_path = self.data_dir / f"{daily_usage.date}.json"

        # Convert to JSON-serializable format
        data = {
            'date': daily_usage.date,
            'total_cost_usd': daily_usage.total_cost_usd,
            'records': []
        }

        for record in daily_usage.records:
            record_data = {
                'timestamp': record.timestamp.isoformat(),
                'model': record.model,
                'channel': record.channel,
                'session_key': record.session_key,
                'token_usage': {
                    'prompt_tokens': record.token_usage.prompt_tokens,
                    'completion_tokens': record.token_usage.completion_tokens,
                    'total_tokens': record.token_usage.total_tokens
                },
                'cost_usd': record.cost_usd,
                'provider': record.provider
            }
            data['records'].append(record_data)

        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def _get_days_in_month(self, year: int, month: int) -> int:
        """Get the number of days in a month."""
        if month == 12:
            next_month = 1
            next_year = year + 1
        else:
            next_month = month + 1
            next_year = year

        first_of_next_month = datetime(next_year, next_month, 1)
        last_of_month = first_of_next_month - timedelta(days=1)
        return last_of_month.day
