#!/usr/bin/env python3
"""
Test script for API audit logging feature.

This script tests:
1. API call logging
2. Statistics aggregation
3. Log file generation

Usage:
    source /tmp/nanobot-venv/bin/activate
    export HOME=/tmp/nanobot-test-config
    python test_audit_logging.py
"""

import asyncio
import json
import os
import sys
from pathlib import Path

# Add project to path
sys.path.insert(0, str(Path(__file__).parent))

from nanobot.providers.custom_provider import CustomProvider
from nanobot.providers.audit_logger import get_stats, get_recent_entries, APILogger


# Test configuration
API_KEY = "tingly-box-eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJjbGllbnRfaWQiOiJ0aW5nbHktYm94IiwiZXhwIjoxNzcxODMwOTMzLCJpYXQiOjE3NzE3NDQ1MzN9.1SwwAWVCE2biwo0lTg5yRKZhqaB4lXaSNcK7Z1712K4"
API_BASE = "http://127.0.0.1:12580/tingly/openai"
MODEL = "tingly-gpt"


def print_header(title: str) -> None:
    """Print a formatted header."""
    print("\n" + "=" * 60)
    print(f"  {title}")
    print("=" * 60 + "\n")


def print_section(title: str) -> None:
    """Print a section header."""
    print(f"\n>>> {title}")
    print("-" * 40)


async def test_api_calls() -> None:
    """Test 1: Make several API calls."""
    print_header("TEST 1: Making API Calls")

    provider = CustomProvider(
        api_key=API_KEY,
        api_base=API_BASE,
        default_model=MODEL
    )

    test_messages = [
        [{"role": "user", "content": "Hello! Say 'Test 1 OK'"}],
        [{"role": "user", "content": "What is 2+2? Answer with just the number."}],
        [{"role": "user", "content": "Say 'Test 3 complete'"}],
    ]

    for i, messages in enumerate(test_messages, 1):
        print(f"  Call {i}: {messages[0]['content'][:50]}...")
        try:
            response = await provider.chat(messages)
            print(f"  Response: {response.content}")
            print(f"  Tokens: {response.usage}\n")
        except Exception as e:
            print(f"  Error: {e}\n")


def test_statistics() -> None:
    """Test 2: Check statistics."""
    print_header("TEST 2: API Statistics")

    stats = get_stats(days=1)

    print_section("Summary")
    print(f"  Total Requests:      {stats.total_requests}")
    print(f"  Successful:          {stats.successful_requests}")
    print(f"  Failed:              {stats.failed_requests}")
    print(f"  Total Tokens:        {stats.total_tokens:,}")
    print(f"  Prompt Tokens:       {stats.total_prompt_tokens:,}")
    print(f"  Completion Tokens:   {stats.total_completion_tokens:,}")
    if stats.avg_duration_ms:
        print(f"  Avg Duration:        {stats.avg_duration_ms:.2f} ms")

    print_section("Usage by Model")
    if stats.model_counts:
        for model, count in sorted(stats.model_counts.items()):
            print(f"  {model}: {count} requests")
    else:
        print("  No data")

    print_section("Usage by Provider")
    if stats.provider_counts:
        for provider, count in sorted(stats.provider_counts.items()):
            print(f"  {provider}: {count} requests")
    else:
        print("  No data")


def test_log_entries() -> None:
    """Test 3: View recent log entries."""
    print_header("TEST 3: Recent Log Entries")

    entries = get_recent_entries(limit=10)

    if not entries:
        print("  No entries found!")
        return

    print(f"  Showing last {len(entries)} entries:\n")

    for i, entry in enumerate(entries, 1):
        status = "✓" if entry.success else "✗"
        print(f"  [{i}] {status} {entry.timestamp}")
        print(f"      Model: {entry.model}")
        print(f"      Provider: {entry.provider}")
        print(f"      Tokens: {entry.total_tokens} (P:{entry.prompt_tokens}, C:{entry.completion_tokens})")
        print(f"      Duration: {entry.duration_ms:.2f} ms" if entry.duration_ms else "      Duration: N/A")

        if entry.tool_calls:
            print(f"      Tools: {', '.join(entry.tool_calls)}")

        if entry.error:
            print(f"      Error: {entry.error}")

        if entry.response_content:
            preview = entry.response_content[:80] + "..." if len(entry.response_content) > 80 else entry.response_content
            print(f"      Response: {preview}")

        print()


def test_log_files() -> None:
    """Test 4: Check log file location and content."""
    print_header("TEST 4: Log File Inspection")

    log_dir = APILogger._get_default_log_dir()
    print_section("Log Directory")
    print(f"  Path: {log_dir}")
    print(f"  Exists: {log_dir.exists()}")

    if log_dir.exists():
        files = list(log_dir.glob("*.jsonl"))
        print(f"  Log files: {len(files)}")

        for f in sorted(files):
            size = f.stat().st_size
            size_str = f"{size / 1024:.2f} KB" if size > 1024 else f"{size} B"
            print(f"    - {f.name} ({size_str})")

            # Show first few lines
            print_section(f"Sample from {f.name}")
            try:
                with open(f, "r") as fp:
                    lines = fp.readlines()[:3]
                    for line in lines:
                        data = json.loads(line)
                        print(f"  Timestamp: {data.get('timestamp')}")
                        print(f"  Model: {data.get('model')}")
                        print(f"  Tokens: {data.get('total_tokens')}")
                        print(f"  Success: {data.get('success')}")
                        print()
            except Exception as e:
                print(f"  Error reading file: {e}")


def main() -> None:
    """Run all tests."""
    print("\n" + "=" * 60)
    print("  API Audit Logging Test Suite")
    print("=" * 60)

    # Check environment
    home = os.path.expanduser("~")
    print(f"\n  HOME: {home}")
    print(f"  Log dir: {APILogger._get_default_log_dir()}")

    # Run async tests
    asyncio.run(test_api_calls())

    # Run sync tests
    test_statistics()
    test_log_entries()
    test_log_files()

    print_header("All Tests Complete!")
    print("  Check the logs above to verify everything is working.")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
