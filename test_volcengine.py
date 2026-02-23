#!/usr/bin/env python
"""Test script to verify Custom provider with local API endpoint"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

# Add the project root to path
sys.path.insert(0, str(Path(__file__).parent))

from nanobot.config.loader import load_config
from nanobot.providers.custom_provider import CustomProvider


async def test_local_api():
    """Test local API endpoint directly"""

    # Load our test config
    config = load_config(Path("/tmp/nanobot-test-config/.nanobot/config.json"))

    print("Configuration loaded:")
    print(f"  Model: {config.agents.defaults.model}")
    print(f"  Provider: Custom")
    print(f"  API Base: {config.providers.custom.api_base}")
    print(f"  API Key: {config.providers.custom.api_key[:30]}...")
    print()

    # Create the Custom provider directly
    provider = CustomProvider(
        api_key=config.providers.custom.api_key,
        api_base=config.providers.custom.api_base,
        default_model=config.agents.defaults.model
    )

    print(f"Provider type: {type(provider).__name__}")
    print(f"Default model: {provider.get_default_model()}")
    print()

    # Test a simple chat completion
    print("Testing chat API...")
    messages = [
        {"role": "user", "content": "Hello! Respond with just 'OK'"}
    ]

    try:
        response = await provider.chat(
            messages=messages,
            model=config.agents.defaults.model,
            max_tokens=100,
            temperature=0.7
        )

        print(f"Response received!")
        print(f"  Content: {response.content}")
        print(f"  Has tool calls: {response.has_tool_calls}")
        print(f"  Finish reason: {response.finish_reason}")
        if response.usage:
            print(f"  Usage: {response.usage}")

        print("\n✅ API test successful!")
        return True

    except Exception as e:
        print(f"\n❌ API test failed: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    asyncio.run(test_local_api())
