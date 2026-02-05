#!/usr/bin/env python3
"""Simple connection test for NVIDIA model via project's LiteLLMProvider.

Usage: python3 scripts/test_nvidia_connection.py

This script loads ~/.nanobot/config.json via project loader and attempts
to call the configured provider (preferring `providers.nvidia`).
"""
import asyncio
import json
from pathlib import Path

from nanobot.config.loader import load_config
from nanobot.providers.litellm_provider import LiteLLMProvider


async def main():
    config = load_config()

    # Prefer explicit nvidia provider, fall back to get_api_key()
    api_key = config.providers.nvidia.api_key or config.get_api_key()
    api_base = config.providers.nvidia.api_base or config.get_api_base()
    model = config.agents.defaults.model

    print(f"Using model: {model}")
    print(f"API base: {api_base}")
    print(f"API key configured: {'yes' if api_key else 'no'}")

    if not api_key:
        print("No API key found in ~/.nanobot/config.json. Please set providers.nvidia.apiKey and try again.")
        return

    provider = LiteLLMProvider(api_key=api_key, api_base=api_base, default_model=model)

    messages = [{"role": "user", "content": "Please reply with 'pong' so we can test connectivity."}]

    try:
        resp = await provider.chat(messages=messages, model=model, max_tokens=64, temperature=0.0)
    except Exception as e:
        print("Exception while calling provider:", str(e))
        return

    # Print structured output
    out = {
        "finish_reason": resp.finish_reason,
        "content": resp.content,
        "usage": resp.usage,
        "tool_calls": [tc.__dict__ for tc in resp.tool_calls] if resp.tool_calls else [],
    }

    print(json.dumps(out, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
