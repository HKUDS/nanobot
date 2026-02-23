#!/usr/bin/env python3
"""Test OKX API connection and signature."""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from workspace.skills.okx_trade import OKXTradeSkill


async def main():
    """Test OKX API connection."""
    try:
        print("Initializing OKX Trading Skill...")
        skill = OKXTradeSkill()

        print(f"API Key: {skill.api_key[:8]}...")
        print(f"Demo Mode: {skill.is_demo}")
        print(f"Base URL: {skill.base_url}")
        print()

        # Test 1: Get account balance
        print("=" * 60)
        print("Test 1: Get Account Balance")
        print("=" * 60)
        result = await skill.get_account_balance()

        if result.get("code") == "0":
            print("✓ Success!")
            print(f"Response: {result}")
        else:
            print(f"✗ Failed: {result}")
        print()

        # Test 2: Get positions
        print("=" * 60)
        print("Test 2: Get Positions")
        print("=" * 60)
        result = await skill.get_positions()

        if result.get("code") == "0":
            print("✓ Success!")
            positions = result.get("data", [])
            if positions:
                print(f"Found {len(positions)} positions:")
                for pos in positions:
                    print(f"  - {pos.get('instId')}: {pos.get('pos')} @ {pos.get('avgPx')}")
            else:
                print("No open positions")
        else:
            print(f"✗ Failed: {result}")
        print()

        # Test 3: Get ticker
        print("=" * 60)
        print("Test 3: Get BTC-USDT-SWAP Ticker")
        print("=" * 60)
        result = await skill.get_ticker("BTC-USDT-SWAP")

        if result.get("code") == "0":
            print("✓ Success!")
            data = result.get("data", [{}])[0]
            print(f"Last Price: {data.get('last')}")
            print(f"24h High: {data.get('high24h')}")
            print(f"24h Low: {data.get('low24h')}")
        else:
            print(f"✗ Failed: {result}")

    except FileNotFoundError as e:
        print(f"✗ Config file not found: {e}")
        print()
        print("Please run setup first:")
        print("  python3 workspace/skills/okx_trade/setup.py")
    except Exception as e:
        print(f"✗ Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
