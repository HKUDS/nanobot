#!/usr/bin/env python3
"""
Example showing how to use the allow_internal_urls feature in nanobot.

This example demonstrates how to configure the exec tool to allow internal URLs
in shell commands, which are normally blocked for security reasons.
"""

import asyncio
from nanobot import Nanobot
from nanobot.config import Config


async def main():
    # Example 1: Default behavior (internal URLs blocked)
    print("=== Example 1: Default behavior (internal URLs blocked) ===")
    config1 = Config()
    bot1 = Nanobot.from_config(config1)
    
    # Try to run a command with an internal URL
    result1 = await bot1.run('Run this shell command: curl http://localhost:8080/api/status')
    print(f"Result: {result1.content}")
    
    # Example 2: With allow_internal_urls enabled
    print("\n=== Example 2: With allow_internal_urls enabled ===")
    config2 = Config()
    # Enable internal URLs in the exec tool configuration
    config2.tools.exec.allow_internal_urls = True
    bot2 = Nanobot.from_config(config2)
    
    # Try to run the same command
    result2 = await bot2.run('Run this shell command: curl http://localhost:8080/api/status')
    print(f"Result: {result2.content}")
    
    # Note: The actual command might still fail because there's no server running
    # at localhost:8080, but it won't be blocked by the internal URL filter anymore.


if __name__ == "__main__":
    asyncio.run(main())