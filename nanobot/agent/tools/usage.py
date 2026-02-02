"""Usage tracking tool for agent to query token consumption and costs."""

from typing import Any

from nanobot.agent.tools.base import Tool
from nanobot.usage import UsageTracker
from nanobot.config.schema import UsageConfig


class UsageTool(Tool):
    """
    Tool for querying token usage and cost statistics.
    
    This allows the agent to be aware of its own resource consumption
    and make informed decisions about budget management.
    """
    
    def __init__(
        self,
        tracker: UsageTracker | None = None,
        config: UsageConfig | None = None,
    ):
        self._tracker = tracker or UsageTracker()
        self._config = config or UsageConfig()
    
    @property
    def name(self) -> str:
        return "usage"
    
    @property
    def description(self) -> str:
        return (
            "Check token usage and cost statistics. Use this to monitor your "
            "API consumption, check budget status, and make decisions about "
            "resource usage. Can query today's usage, weekly summary, or "
            "breakdown by model/channel."
        )
    
    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "period": {
                    "type": "string",
                    "enum": ["today", "week", "month"],
                    "description": "Time period to query. Default: today"
                },
                "breakdown": {
                    "type": "string",
                    "enum": ["none", "model", "channel", "both"],
                    "description": "Show breakdown by model, channel, or both. Default: none"
                }
            },
            "required": []
        }
    
    async def execute(
        self,
        period: str = "today",
        breakdown: str = "none",
        **kwargs: Any
    ) -> str:
        """Query usage statistics."""
        
        lines = []
        
        # Get data based on period
        if period == "today":
            summary = self._tracker.get_today()
            period_label = f"Today ({summary.date})"
        elif period == "week":
            summary = self._tracker.get_aggregate(7)
            period_label = "Last 7 Days"
        elif period == "month":
            summary = self._tracker.get_aggregate(30)
            period_label = "Last 30 Days"
        else:
            summary = self._tracker.get_today()
            period_label = "Today"
        
        # Header
        lines.append(f"## Usage Statistics - {period_label}")
        lines.append("")
        
        if summary.total_requests == 0:
            lines.append("No usage recorded for this period.")
            return "\n".join(lines)
        
        # Basic stats
        lines.append(f"- **Requests**: {summary.total_requests}")
        lines.append(f"- **Total Tokens**: {summary.total_tokens:,}")
        lines.append(f"  - Input: {summary.total_prompt_tokens:,}")
        lines.append(f"  - Output: {summary.total_completion_tokens:,}")
        lines.append(f"- **Cost**: ${summary.total_cost_usd:.4f}")
        
        # Budget status
        if self._config.daily_budget_usd > 0 or self._config.monthly_budget_usd > 0:
            lines.append("")
            lines.append("### Budget Status")
            
            if self._config.daily_budget_usd > 0:
                today = self._tracker.get_today()
                daily_pct = (today.total_cost_usd / self._config.daily_budget_usd) * 100
                status = "⚠️ WARNING" if daily_pct >= 80 else "✅ OK"
                if daily_pct >= 100:
                    status = "🚨 EXCEEDED"
                lines.append(
                    f"- **Daily**: ${today.total_cost_usd:.4f} / "
                    f"${self._config.daily_budget_usd:.2f} ({daily_pct:.1f}%) {status}"
                )
            
            if self._config.monthly_budget_usd > 0:
                monthly_cost = self._tracker.get_monthly_cost()
                monthly_pct = (monthly_cost / self._config.monthly_budget_usd) * 100
                status = "⚠️ WARNING" if monthly_pct >= 80 else "✅ OK"
                if monthly_pct >= 100:
                    status = "🚨 EXCEEDED"
                lines.append(
                    f"- **Monthly**: ${monthly_cost:.4f} / "
                    f"${self._config.monthly_budget_usd:.2f} ({monthly_pct:.1f}%) {status}"
                )
        
        # Breakdown by model
        if breakdown in ("model", "both") and summary.by_model:
            lines.append("")
            lines.append("### By Model")
            sorted_models = sorted(
                summary.by_model.values(),
                key=lambda x: x.cost_usd,
                reverse=True
            )
            for stats in sorted_models:
                pct = (stats.cost_usd / summary.total_cost_usd * 100) if summary.total_cost_usd > 0 else 0
                lines.append(
                    f"- **{stats.name}**: {stats.requests} requests, "
                    f"{stats.total_tokens:,} tokens, ${stats.cost_usd:.4f} ({pct:.1f}%)"
                )
        
        # Breakdown by channel
        if breakdown in ("channel", "both") and summary.by_channel:
            lines.append("")
            lines.append("### By Channel")
            sorted_channels = sorted(
                summary.by_channel.values(),
                key=lambda x: x.cost_usd,
                reverse=True
            )
            for stats in sorted_channels:
                pct = (stats.cost_usd / summary.total_cost_usd * 100) if summary.total_cost_usd > 0 else 0
                lines.append(
                    f"- **{stats.name}**: {stats.requests} requests, "
                    f"{stats.total_tokens:,} tokens, ${stats.cost_usd:.4f} ({pct:.1f}%)"
                )
        
        return "\n".join(lines)
