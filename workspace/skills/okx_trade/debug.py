#!/usr/bin/env python3
"""Debug OKX API signature generation."""

import asyncio
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from workspace.skills.okx_trade import OKXTradeSkill


async def main():
    """Debug signature generation."""
    try:
        print("=" * 60)
        print("OKX API Signature Debug")
        print("=" * 60)
        print()

        skill = OKXTradeSkill()

        # Test signature generation
        method = "GET"
        request_path = "/api/v5/account/balance"
        body = ""

        # Generate headers
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        timestamp = now.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'

        print(f"Config loaded from: {Path.home() / '.nanobot' / 'workspace' / 'skills' / 'okx_trade' / 'config.json'}")
        print(f"API Key: {skill.api_key[:8]}...{skill.api_key[-4:]}")
        print(f"Secret Key: {skill.secret_key[:8]}...{skill.secret_key[-4:]}")
        print(f"Passphrase: {skill.passphrase[:4]}...")
        print(f"Demo Mode: {skill.is_demo}")
        print(f"Base URL: {skill.base_url}")
        print()

        print(f"Timestamp: {timestamp}")
        print(f"Method: {method}")
        print(f"Request Path: {request_path}")
        print(f"Body: '{body}'")
        print()

        # Build prehash string
        prehash_string = timestamp + method + request_path + body
        print(f"Prehash String: {prehash_string}")
        print(f"Prehash Length: {len(prehash_string)}")
        print()

        # Generate signature
        signature = skill._sign(timestamp, method, request_path, body)
        print(f"Signature: {signature}")
        print()

        # Show headers
        headers = skill._get_headers(method, request_path, body)
        print("Request Headers:")
        for key, value in headers.items():
            if key == "OK-ACCESS-SIGN":
                print(f"  {key}: {value[:20]}...")
            else:
                print(f"  {key}: {value}")
        print()

        # Test actual API call
        print("=" * 60)
        print("Testing API Call: Get Account Balance")
        print("=" * 60)
        result = await skill.get_account_balance()

        print(f"Response Code: {result.get('code')}")
        print(f"Response Message: {result.get('msg')}")
        print()

        if result.get("code") == "0":
            print("✓ Success!")
            print(json.dumps(result, indent=2))
        else:
            print(f"✗ Failed!")
            print(f"Full Response: {json.dumps(result, indent=2)}")

        print()
        print("=" * 60)
        print("Testing API Call: Get Positions")
        print("=" * 60)
        result = await skill.get_positions()

        print(f"Response Code: {result.get('code')}")
        print(f"Response Message: {result.get('msg')}")

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
            print(f"✗ Failed!")
            print(f"Full Response: {json.dumps(result, indent=2)}")

    except Exception as e:
        print(f"✗ Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
