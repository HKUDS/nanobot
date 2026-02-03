"""Budget monitoring and automatic alerting."""

from datetime import datetime
from typing import Callable, Awaitable

from loguru import logger

from nanobot.config.schema import UsageConfig
from nanobot.usage import UsageTracker


class BudgetAlert:
    """Represents a budget alert to be sent."""
    
    DAILY_WARNING = "daily_warning"
    DAILY_EXCEEDED = "daily_exceeded"
    MONTHLY_WARNING = "monthly_warning"
    MONTHLY_EXCEEDED = "monthly_exceeded"
    
    def __init__(self, alert_type: str, current: float, budget: float, percent: float):
        self.alert_type = alert_type
        self.current = current
        self.budget = budget
        self.percent = percent
    
    def format_message(self) -> str:
        """Format the alert as a user-friendly message."""
        if self.alert_type == self.DAILY_EXCEEDED:
            return (
                f"🚨 **Daily Budget Exceeded!**\n\n"
                f"You've spent **${self.current:.4f}** today, "
                f"which exceeds your daily budget of **${self.budget:.2f}** ({self.percent:.1f}%).\n\n"
                f"Consider pausing usage or adjusting your budget."
            )
        elif self.alert_type == self.DAILY_WARNING:
            return (
                f"⚠️ **Daily Budget Warning**\n\n"
                f"You've used **{self.percent:.1f}%** of your daily budget.\n"
                f"Spent: ${self.current:.4f} / ${self.budget:.2f}"
            )
        elif self.alert_type == self.MONTHLY_EXCEEDED:
            return (
                f"🚨 **Monthly Budget Exceeded!**\n\n"
                f"You've spent **${self.current:.4f}** this month, "
                f"which exceeds your monthly budget of **${self.budget:.2f}** ({self.percent:.1f}%).\n\n"
                f"Consider pausing usage until next month."
            )
        elif self.alert_type == self.MONTHLY_WARNING:
            return (
                f"⚠️ **Monthly Budget Warning**\n\n"
                f"You've used **{self.percent:.1f}%** of your monthly budget.\n"
                f"Spent: ${self.current:.4f} / ${self.budget:.2f}"
            )
        return f"Budget alert: {self.alert_type}"


class BudgetMonitor:
    """
    Monitors token usage against budget thresholds and triggers alerts.
    
    Features:
    - Checks daily and monthly budgets after each API call
    - Sends alerts when thresholds are exceeded
    - Cooldown mechanism to avoid alert spam (default: 1 hour)
    """
    
    # Cooldown between alerts of the same type (in seconds)
    DEFAULT_COOLDOWN_S = 3600  # 1 hour
    
    def __init__(
        self,
        tracker: UsageTracker,
        config: UsageConfig,
        cooldown_s: int = DEFAULT_COOLDOWN_S,
    ):
        self.tracker = tracker
        self.config = config
        self.cooldown_s = cooldown_s
        
        # Track last alert time for each alert type to prevent spam
        self._last_alert: dict[str, datetime] = {}
    
    def _can_alert(self, alert_type: str) -> bool:
        """Check if we can send an alert (respects cooldown)."""
        if alert_type not in self._last_alert:
            return True
        
        elapsed = datetime.now() - self._last_alert[alert_type]
        return elapsed.total_seconds() >= self.cooldown_s
    
    def _mark_alerted(self, alert_type: str) -> None:
        """Mark that we sent an alert."""
        self._last_alert[alert_type] = datetime.now()
    
    def check_budgets(self, exceeded_only: bool = True) -> BudgetAlert | None:
        """
        Check current usage against budget thresholds.
        
        Args:
            exceeded_only: If True, only alert when budget is exceeded (100%+).
                          If False, also alert at warning threshold.
                          Default True since Agent can use UsageTool for warnings.
        
        Returns:
            BudgetAlert if a threshold is exceeded and cooldown allows,
            None otherwise.
        """
        # Skip if no budgets configured
        if self.config.daily_budget_usd <= 0 and self.config.monthly_budget_usd <= 0:
            return None
        
        # Check daily budget
        if self.config.daily_budget_usd > 0:
            today = self.tracker.get_today()
            daily_pct = (today.total_cost_usd / self.config.daily_budget_usd) * 100
            
            if daily_pct >= 100:
                alert_type = BudgetAlert.DAILY_EXCEEDED
                if self._can_alert(alert_type):
                    self._mark_alerted(alert_type)
                    return BudgetAlert(
                        alert_type=alert_type,
                        current=today.total_cost_usd,
                        budget=self.config.daily_budget_usd,
                        percent=daily_pct,
                    )
            elif not exceeded_only and daily_pct >= self.config.warn_at_percent:
                alert_type = BudgetAlert.DAILY_WARNING
                if self._can_alert(alert_type):
                    self._mark_alerted(alert_type)
                    return BudgetAlert(
                        alert_type=alert_type,
                        current=today.total_cost_usd,
                        budget=self.config.daily_budget_usd,
                        percent=daily_pct,
                    )
        
        # Check monthly budget
        if self.config.monthly_budget_usd > 0:
            monthly_cost = self.tracker.get_monthly_cost()
            monthly_pct = (monthly_cost / self.config.monthly_budget_usd) * 100
            
            if monthly_pct >= 100:
                alert_type = BudgetAlert.MONTHLY_EXCEEDED
                if self._can_alert(alert_type):
                    self._mark_alerted(alert_type)
                    return BudgetAlert(
                        alert_type=alert_type,
                        current=monthly_cost,
                        budget=self.config.monthly_budget_usd,
                        percent=monthly_pct,
                    )
            elif not exceeded_only and monthly_pct >= self.config.warn_at_percent:
                alert_type = BudgetAlert.MONTHLY_WARNING
                if self._can_alert(alert_type):
                    self._mark_alerted(alert_type)
                    return BudgetAlert(
                        alert_type=alert_type,
                        current=monthly_cost,
                        budget=self.config.monthly_budget_usd,
                        percent=monthly_pct,
                    )
        
        return None
    
    async def check_and_alert(
        self,
        send_callback: Callable[[str, str, str], Awaitable[None]],
        channel: str,
        chat_id: str,
    ) -> bool:
        """
        Check budgets and send alert if needed.
        
        Args:
            send_callback: Async function(channel, chat_id, message) to send alert
            channel: Target channel (telegram, whatsapp, etc.)
            chat_id: Target chat/user ID
        
        Returns:
            True if an alert was sent, False otherwise.
        """
        alert = self.check_budgets()
        
        if alert:
            message = alert.format_message()
            try:
                await send_callback(channel, chat_id, message)
                logger.info(f"Budget alert sent: {alert.alert_type} to {channel}:{chat_id}")
                return True
            except Exception as e:
                logger.error(f"Failed to send budget alert: {e}")
        
        return False
