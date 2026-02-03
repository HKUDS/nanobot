"""Usage tool for agent self-awareness and cost monitoring."""

from typing import Any, Dict

from nanobot.agent.tools.base import Tool

from .models import BudgetStatus
from .monitor import UsageMonitor
from .tracker import UsageTracker


class UsageTool(Tool):
    """
    Tool that allows the agent to query its own resource consumption and costs.

    This enables the agent to be aware of its usage patterns and make informed
    decisions based on remaining budget or cost constraints.
    """

    name = "usage"
    description = "Query token usage, costs, and budget information for self-awareness"

    def __init__(self, tracker: UsageTracker, monitor: UsageMonitor):
        """
        Initialize the usage tool.

        Args:
            tracker: UsageTracker instance
            monitor: UsageMonitor instance
        """
        self.tracker = tracker
        self.monitor = monitor

    def get_schema(self) -> Dict[str, Any]:
        """Get the tool schema for LLM consumption."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "enum": [
                                "current_budget",
                                "usage_today",
                                "usage_week",
                                "usage_month",
                                "forecast",
                                "alerts",
                                "model_breakdown",
                                "channel_breakdown"
                            ],
                            "description": "Type of usage information to retrieve"
                        },
                        "model_filter": {
                            "type": "string",
                            "description": "Optional filter by specific model (e.g., 'claude-3-5-sonnet')"
                        },
                        "channel_filter": {
                            "type": "string",
                            "description": "Optional filter by specific channel (cli, telegram, whatsapp)"
                        }
                    },
                    "required": ["query"]
                }
            }
        }

    async def execute(self, **kwargs: Any) -> str:
        """
        Execute the usage query.

        Args:
            query: Type of query to execute
            model_filter: Optional model filter
            channel_filter: Optional channel filter

        Returns:
            Human-readable response with usage information
        """
        query = kwargs.get("query", "current_budget")
        model_filter = kwargs.get("model_filter")
        channel_filter = kwargs.get("channel_filter")

        try:
            if query == "current_budget":
                return self._get_budget_status()
            elif query == "usage_today":
                return self._get_daily_usage(days=1, model_filter=model_filter, channel_filter=channel_filter)
            elif query == "usage_week":
                return self._get_daily_usage(days=7, model_filter=model_filter, channel_filter=channel_filter)
            elif query == "usage_month":
                return self._get_daily_usage(days=30, model_filter=model_filter, channel_filter=channel_filter)
            elif query == "forecast":
                return self._get_forecast()
            elif query == "alerts":
                return self._get_alerts()
            elif query == "model_breakdown":
                return self._get_breakdown("model", days=30, channel_filter=channel_filter)
            elif query == "channel_breakdown":
                return self._get_breakdown("channel", days=30, model_filter=model_filter)
            else:
                return f"Unknown query type: {query}. Available: current_budget, usage_today, usage_week, usage_month, forecast, alerts, model_breakdown, channel_breakdown"

        except Exception as e:
            return f"Error retrieving usage information: {str(e)}"

    def _get_budget_status(self) -> str:
        """Get current budget status."""
        status = self.monitor.get_budget_status()

        response = f"""Current Budget Status:
• Monthly Budget: ${status.monthly_budget_usd:.2f}
• Current Spend: ${status.current_spend_usd:.2f}
• Remaining: ${status.remaining_budget_usd:.2f}
• Utilization: {status.utilization_percentage:.1f}%

Alert Thresholds: {', '.join(f'${t:.2f}' for t in status.alert_thresholds)}"""

        if status.alerts:
            response += "\n\nAlerts:\n" + "\n".join(f"⚠️ {alert}" for alert in status.alerts)

        return response

    def _get_daily_usage(self, days: int, model_filter: str = None, channel_filter: str = None) -> str:
        """Get usage summary for the last N days."""
        summary = self.tracker.get_usage_summary(
            days=days,
            model_filter=model_filter,
            channel_filter=channel_filter
        )

        period_name = "day" if days == 1 else f"{days} days"

        response = f"""Usage Summary (Last {period_name}):
• Total Tokens: {summary['total_tokens']:,}
• Total Cost: ${summary['total_cost_usd']:.4f}
• API Calls: {summary['record_count']}

Model Breakdown:"""

        for model, tokens in sorted(summary['model_breakdown'].items(), key=lambda x: x[1], reverse=True):
            response += f"\n  • {model}: {tokens:,} tokens"

        response += "\n\nChannel Breakdown:"
        for channel, tokens in sorted(summary['channel_breakdown'].items(), key=lambda x: x[1], reverse=True):
            response += f"\n  • {channel}: {tokens:,} tokens"

        return response

    def _get_forecast(self) -> str:
        """Get usage forecast for the month."""
        forecast = self.monitor.get_usage_forecast()

        response = f"""Usage Forecast:
• Current Spend: ${forecast['current_spend_usd']:.2f}
• Projected Total: ${forecast['projected_total_usd']:.2f}
• Monthly Budget: ${forecast['budget_usd']:.2f}
• Days Remaining: {forecast['days_remaining']}
• Daily Average Cost: ${forecast['daily_average_cost_usd']:.4f}
• Daily Average Tokens: {forecast['daily_average_tokens']:.0f}

Projected Remaining Spend: ${forecast['projected_remaining_spend_usd']:.2f}"""

        if forecast['will_exceed_budget']:
            response += "\n\n⚠️ Warning: Projected spending will exceed monthly budget!"
        else:
            remaining_budget = forecast['budget_usd'] - forecast['projected_total_usd']
            response += f"\n\n✓ Projected to stay within budget (remaining: ${remaining_budget:.2f})"

        return response

    def _get_alerts(self) -> str:
        """Get current budget alerts."""
        alerts = self.monitor.get_budget_alerts()

        if not alerts:
            return "✓ No budget alerts at this time."

        response = "Current Budget Alerts:\n"
        for alert in alerts:
            response += f"⚠️ {alert}\n"

        return response

    def _get_breakdown(self, breakdown_type: str, days: int, model_filter: str = None, channel_filter: str = None) -> str:
        """Get breakdown by model or channel."""
        summary = self.tracker.get_usage_summary(
            days=days,
            model_filter=model_filter,
            channel_filter=channel_filter
        )

        if breakdown_type == "model":
            breakdown = summary['model_breakdown']
            title = "Model Breakdown"
        else:
            breakdown = summary['channel_breakdown']
            title = "Channel Breakdown"

        if not breakdown:
            return f"No {breakdown_type} usage data found for the last {days} days."

        response = f"{title} (Last {days} days):\n"

        # Sort by token usage descending
        sorted_items = sorted(breakdown.items(), key=lambda x: x[1], reverse=True)

        for item, tokens in sorted_items:
            percentage = (tokens / summary['total_tokens'] * 100) if summary['total_tokens'] > 0 else 0
            response += ".1f"

        return response
