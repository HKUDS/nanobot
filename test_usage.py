#!/usr/bin/env python3
"""Test script for usage tracking functionality."""

import asyncio
from datetime import datetime, timedelta
from pathlib import Path
import tempfile

from nanobot.usage import UsageTracker, UsageMonitor, UsageConfig
from nanobot.usage.models import TokenUsage


async def test_usage_tracking():
    """Test usage tracking with mock data."""
    print("Testing usage tracking functionality...")

    # Create temporary directory for usage data
    with tempfile.TemporaryDirectory() as temp_dir:
        usage_dir = Path(temp_dir) / "usage"
        usage_dir.mkdir()

        # Initialize components
        tracker = UsageTracker(usage_dir)
        config = UsageConfig(monthly_budget_usd=20.0, alert_thresholds=[0.5, 0.8, 1.0])
        monitor = UsageMonitor(tracker, config)

        print("✓ Components initialized")

        # Create mock usage data
        base_date = datetime.now() - timedelta(days=2)

        # Day 1: CLI usage with Claude
        day1 = base_date.strftime("%Y-%m-%d")
        tracker.record_usage(
            model="anthropic/claude-3-5-sonnet",
            channel="cli",
            session_key="cli:test1",
            token_usage=TokenUsage(
                prompt_tokens=1000,
                completion_tokens=500,
                total_tokens=1500
            ),
            provider="anthropic"
        )

        tracker.record_usage(
            model="anthropic/claude-3-5-sonnet",
            channel="cli",
            session_key="cli:test2",
            token_usage=TokenUsage(
                prompt_tokens=800,
                completion_tokens=400,
                total_tokens=1200
            ),
            provider="anthropic"
        )

        print(f"✓ Recorded usage for {day1}")

        # Day 2: Telegram usage with GPT-4
        day2 = (base_date + timedelta(days=1)).strftime("%Y-%m-%d")
        tracker.record_usage(
            model="openai/gpt-4o",
            channel="telegram",
            session_key="telegram:user123",
            token_usage=TokenUsage(
                prompt_tokens=2000,
                completion_tokens=1000,
                total_tokens=3000
            ),
            provider="openai"
        )

        tracker.record_usage(
            model="openai/gpt-4o",
            channel="telegram",
            session_key="telegram:user456",
            token_usage=TokenUsage(
                prompt_tokens=1500,
                completion_tokens=800,
                total_tokens=2300
            ),
            provider="openai"
        )

        print(f"✓ Recorded usage for {day2}")

        # Test summary queries
        print("\n--- Testing Summary Queries ---")

        # 3-day summary
        summary_3d = tracker.get_usage_summary(days=3)
        print("3-day summary:")
        print(f"  Total tokens: {summary_3d['total_tokens']:,}")
        print(".4f")
        print(f"  API calls: {summary_3d['record_count']}")

        # Model breakdown
        print("  Model breakdown:")
        for model, tokens in summary_3d['model_breakdown'].items():
            print(f"    {model}: {tokens:,} tokens")

        # Channel breakdown
        print("  Channel breakdown:")
        for channel, tokens in summary_3d['channel_breakdown'].items():
            print(f"    {channel}: {tokens:,} tokens")

        # Test budget monitoring
        print("\n--- Testing Budget Monitoring ---")
        status = monitor.get_budget_status()
        print(f"Monthly Budget: ${status.monthly_budget_usd:.2f}")
        print(f"Current Spend: ${status.current_spend_usd:.2f}")
        print(f"Remaining: ${status.remaining_budget_usd:.2f}")
        print(f"Utilization: {status.utilization_percentage:.1f}%")

        if status.alerts:
            print("Alerts:")
            for alert in status.alerts:
                print(f"  ⚠️ {alert}")
        else:
            print("✓ No alerts")

        # Test forecast
        print("\n--- Testing Forecast ---")
        forecast = monitor.get_usage_forecast()
        print(f"Current spend: ${forecast['current_spend_usd']:.2f}")
        print(f"Projected total: ${forecast['projected_total_usd']:.2f}")
        print(f"Daily average: ${forecast['daily_average_cost_usd']:.4f}")

        # Test cost calculation
        print("\n--- Testing Cost Calculation ---")
        from nanobot.usage.models import calculate_token_cost

        # Test Anthropic pricing
        cost_anthropic = calculate_token_cost("anthropic", "claude-3-5-sonnet", 1000, 500)
        print(".4f")

        # Test OpenAI pricing
        cost_openai = calculate_token_cost("openai", "gpt-4o", 2000, 1000)
        print(".4f")

        # Test unknown provider
        cost_unknown = calculate_token_cost("unknown", "some-model", 1000, 500)
        print(".4f")

        print("\n✓ All tests completed successfully!")


if __name__ == "__main__":
    asyncio.run(test_usage_tracking())
