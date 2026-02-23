#!/usr/bin/env python3
"""Debug OKX API signature generation."""

import asyncio
import sys
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

        print(f"API Key: {skill.api_key[:8]}...{skill.api_key[-4:]}")
        print(f"Secret Key: {skill.secret_key[:8]}...{skill.secret_key[-4:]}")
        print(f"Passphrase: {skill.passphrase[:4]}...")
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

        # Test actual API call
        print("=" * 60)
        print("Testing API Call")
        print("=" * 60)
        result = await skill.get_account_balance()

        print(f"Response Code: {result.get('code')}")
        print(f"Response Message: {result.get('msg')}")

        if result.get("code") == "0":
            print("✓ Success!")
        else:
            print(f"✗ Failed!")
            print(f"Full Response: {result}")

    except Exception as e:
        print(f"✗ Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
