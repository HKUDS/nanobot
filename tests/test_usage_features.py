"""
Test script for usage tracking features.

This script creates mock usage data and tests:
1. Model-level grouping
2. Channel-level grouping  
3. Budget warnings
4. CLI output

Run with: python tests/test_usage_features.py
"""

import json
import shutil
from datetime import datetime, timedelta
from pathlib import Path


def create_mock_data():
    """Create mock usage data for testing."""
    
    # Use a test directory
    test_dir = Path.home() / ".nanobot" / "usage"
    test_dir.mkdir(parents=True, exist_ok=True)
    
    # Create data for today and yesterday
    today = datetime.now()
    yesterday = today - timedelta(days=1)
    
    days_data = [
        (today, "today"),
        (yesterday, "yesterday"),
    ]
    
    models = [
        ("anthropic/claude-opus-4", 0.015, 0.075),   # $15/M input, $75/M output
        ("deepseek/deepseek-chat", 0.00014, 0.00028),  # Much cheaper
        ("openai/gpt-4o", 0.0025, 0.01),  # $2.5/M input, $10/M output
    ]
    
    channels = ["cli", "telegram", "whatsapp"]
    
    for date_obj, label in days_data:
        date_str = date_obj.strftime("%Y-%m-%d")
        records = []
        
        # Generate various records
        record_templates = [
            # (model_idx, channel, prompt_tokens, completion_tokens)
            (0, "cli", 1500, 800),
            (0, "telegram", 2000, 1200),
            (1, "cli", 5000, 2000),
            (1, "whatsapp", 3000, 1500),
            (2, "telegram", 1000, 500),
            (0, "cli", 800, 400),
            (1, "telegram", 4000, 1800),
            (2, "whatsapp", 1200, 600),
        ]
        
        by_model = {}
        by_channel = {}
        total_requests = 0
        total_prompt_tokens = 0
        total_completion_tokens = 0
        total_tokens = 0
        total_cost_usd = 0.0
        
        for i, (model_idx, channel, pt, ct) in enumerate(record_templates):
            model_name, input_price, output_price = models[model_idx]
            total = pt + ct
            cost = (pt * input_price / 1_000_000) + (ct * output_price / 1_000_000)
            
            timestamp = (date_obj.replace(hour=9) + timedelta(minutes=i*30)).isoformat(timespec="seconds")
            
            record = {
                "timestamp": timestamp,
                "model": model_name,
                "prompt_tokens": pt,
                "completion_tokens": ct,
                "total_tokens": total,
                "cost_usd": cost,
                "channel": channel,
                "session_key": f"session_{i}",
            }
            records.append(record)
            
            # Update totals
            total_requests += 1
            total_prompt_tokens += pt
            total_completion_tokens += ct
            total_tokens += total
            total_cost_usd += cost
            
            # Update by_model
            if model_name not in by_model:
                by_model[model_name] = {
                    "name": model_name,
                    "requests": 0,
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                    "cost_usd": 0.0,
                }
            by_model[model_name]["requests"] += 1
            by_model[model_name]["prompt_tokens"] += pt
            by_model[model_name]["completion_tokens"] += ct
            by_model[model_name]["total_tokens"] += total
            by_model[model_name]["cost_usd"] += cost
            
            # Update by_channel
            if channel not in by_channel:
                by_channel[channel] = {
                    "name": channel,
                    "requests": 0,
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                    "cost_usd": 0.0,
                }
            by_channel[channel]["requests"] += 1
            by_channel[channel]["prompt_tokens"] += pt
            by_channel[channel]["completion_tokens"] += ct
            by_channel[channel]["total_tokens"] += total
            by_channel[channel]["cost_usd"] += cost
        
        # Create daily summary
        daily_summary = {
            "date": date_str,
            "total_requests": total_requests,
            "total_prompt_tokens": total_prompt_tokens,
            "total_completion_tokens": total_completion_tokens,
            "total_tokens": total_tokens,
            "total_cost_usd": total_cost_usd,
            "records": records,
            "by_model": by_model,
            "by_channel": by_channel,
        }
        
        # Write to file
        file_path = test_dir / f"{date_str}.json"
        file_path.write_text(json.dumps(daily_summary, indent=2, ensure_ascii=False), encoding="utf-8")
        
        print(f"Created {label} data: {file_path}")
        print(f"  - {total_requests} requests")
        print(f"  - {total_tokens} tokens")
        print(f"  - ${total_cost_usd:.4f} cost")
        print(f"  - Models: {list(by_model.keys())}")
        print(f"  - Channels: {list(by_channel.keys())}")
        print()


def update_config_with_budget():
    """Update config to include budget settings for testing."""
    config_path = Path.home() / ".nanobot" / "config.json"
    
    if config_path.exists():
        config = json.loads(config_path.read_text(encoding="utf-8"))
    else:
        config = {}
    
    # Add usage config with budget
    config["usage"] = {
        "daily_budget_usd": 0.50,  # $0.50 daily limit (will trigger warning)
        "monthly_budget_usd": 10.0,  # $10 monthly limit
        "warn_at_percent": 80,
    }
    
    config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    print(f"Updated config with budget settings: {config_path}")
    print(f"  - daily_budget_usd: $0.50")
    print(f"  - monthly_budget_usd: $10.00")
    print(f"  - warn_at_percent: 80%")
    print()


def main():
    print("=" * 60)
    print("Usage Tracking Feature Test")
    print("=" * 60)
    print()
    
    # Step 1: Create mock data
    print("[Step 1] Creating mock usage data...")
    print("-" * 40)
    create_mock_data()
    
    # Step 2: Update config with budget
    print("[Step 2] Configuring budget settings...")
    print("-" * 40)
    update_config_with_budget()
    
    # Step 3: Test instructions
    print("[Step 3] Test the CLI commands:")
    print("-" * 40)
    print()
    print("  # Basic usage (should show budget warning)")
    print("  nanobot usage")
    print()
    print("  # Today only")
    print("  nanobot usage --today")
    print()
    print("  # With model breakdown")
    print("  nanobot usage --by-model")
    print()
    print("  # With channel breakdown")  
    print("  nanobot usage --by-channel")
    print()
    print("  # Full breakdown (model + channel)")
    print("  nanobot usage --by-model --by-channel")
    print()
    print("=" * 60)


if __name__ == "__main__":
    main()
