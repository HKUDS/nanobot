"""Budget monitor for usage tracking and alerts."""

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from .models import BudgetStatus, UsageConfig
from .tracker import UsageTracker


class UsageMonitor:
    """
    Monitors usage against budget limits and generates alerts.

    Checks current spending against configured thresholds and provides
    status information for budget management.
    """

    def __init__(self, tracker: UsageTracker, config: UsageConfig):
        """
        Initialize the usage monitor.

        Args:
            tracker: UsageTracker instance
            config: Usage configuration with budget settings
        """
        self.tracker = tracker
        self.config = config

    def get_budget_status(self) -> BudgetStatus:
        """
        Get current budget status for the current month.

        Returns:
            BudgetStatus with current spending and alerts
        """
        now = datetime.now()
        current_month = now.month
        current_year = now.year

        # Get all usage for current month
        monthly_usage = self.tracker.get_monthly_usage(current_year, current_month)

        # Calculate total spend for month
        current_spend = sum(daily.total_cost_usd for daily in monthly_usage)
        remaining_budget = self.config.monthly_budget_usd - current_spend

        # Create budget status
        status = BudgetStatus(
            monthly_budget_usd=self.config.monthly_budget_usd,
            current_spend_usd=current_spend,
            remaining_budget_usd=remaining_budget,
            alert_thresholds=self.config.get_alert_levels()
        )

        # Check for alerts
        status.check_alerts()

        return status

    def get_budget_alerts(self) -> List[str]:
        """
        Get current budget alerts.

        Returns:
            List of alert messages
        """
        status = self.get_budget_status()
        return status.alerts

    def is_over_budget(self) -> bool:
        """
        Check if current spending has exceeded the monthly budget.

        Returns:
            True if over budget, False otherwise
        """
        status = self.get_budget_status()
        return status.current_spend_usd >= status.monthly_budget_usd

    def get_remaining_budget_percentage(self) -> float:
        """
        Get remaining budget as a percentage.

        Returns:
            Percentage of budget remaining (can be negative if over budget)
        """
        status = self.get_budget_status()
        if status.monthly_budget_usd == 0:
            return 100.0
        return (status.remaining_budget_usd / status.monthly_budget_usd) * 100

    def get_usage_forecast(self, days_ahead: int = 30) -> Dict:
        """
        Get usage forecast for the remaining days of the month.

        Args:
            days_ahead: Number of days to forecast

        Returns:
            Dictionary with forecast information
        """
        status = self.get_budget_status()
        now = datetime.now()

        # Calculate days remaining in month
        if now.month == 12:
            next_month = 1
            next_year = now.year + 1
        else:
            next_month = now.month + 1
            next_year = now.year

        first_of_next_month = datetime(next_year, next_month, 1)
        days_remaining = (first_of_next_month - now).days

        # Get recent daily average (last 7 days)
        recent_usage = self.tracker.get_usage_summary(days=7)
        if recent_usage['record_count'] > 0:
            daily_average_cost = recent_usage['total_cost_usd'] / 7
            daily_average_tokens = recent_usage['total_tokens'] / 7
        else:
            daily_average_cost = 0.0
            daily_average_tokens = 0

        # Forecast remaining spend
        projected_remaining_spend = daily_average_cost * min(days_ahead, days_remaining)

        return {
            "current_spend_usd": status.current_spend_usd,
            "projected_total_usd": status.current_spend_usd + projected_remaining_spend,
            "budget_usd": status.monthly_budget_usd,
            "days_remaining": days_remaining,
            "daily_average_cost_usd": daily_average_cost,
            "daily_average_tokens": daily_average_tokens,
            "projected_remaining_spend_usd": projected_remaining_spend,
            "will_exceed_budget": (status.current_spend_usd + projected_remaining_spend) > status.monthly_budget_usd
        }

    async def monitor_budget_async(self, check_interval_seconds: int = 3600) -> None:
        """
        Asynchronously monitor budget and log alerts.

        This method runs indefinitely, checking budget status at regular intervals
        and logging any alerts to the console.

        Args:
            check_interval_seconds: How often to check budget status
        """
        while True:
            try:
                alerts = self.get_budget_alerts()
                if alerts:
                    print("Budget Alerts:")
                    for alert in alerts:
                        print(f"  ⚠️  {alert}")

                # Wait for next check
                await asyncio.sleep(check_interval_seconds)

            except Exception as e:
                print(f"Error in budget monitoring: {e}")
                await asyncio.sleep(check_interval_seconds)

    def format_budget_status(self) -> str:
        """
        Format budget status as a human-readable string.

        Returns:
            Formatted budget status string
        """
        status = self.get_budget_status()

        lines = []
        lines.append(f"Monthly Budget: ${status.monthly_budget_usd:.2f}")
        lines.append(f"Current Spend: ${status.current_spend_usd:.2f}")
        lines.append(f"Remaining: ${status.remaining_budget_usd:.2f}")
        lines.append(f"Utilization: {status.utilization_percentage:.1f}%")

        if status.alerts:
            lines.append("")
            lines.append("Alerts:")
            for alert in status.alerts:
                lines.append(f"  ⚠️  {alert}")

        return "\n".join(lines)
