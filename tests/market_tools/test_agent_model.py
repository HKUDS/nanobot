"""Test nanobot agent with minimax-m2.5:cloud model."""
import asyncio
from nanobot.config.loader import load_config
from nanobot.providers.factory import make_provider


async def main():
    # Load config
    config = load_config()
    
    print(f"Model: {config.agents.defaults.model}")
    print(f"Provider: {config.agents.defaults.provider}")
    
    # Create provider
    provider = make_provider(config)
    print(f"Provider created: {type(provider).__name__}")
    
    # Test chat
    print("\nSending test message...")
    response = await provider.chat(
        messages=[{"role": "user", "content": "hello"}],
        model=config.agents.defaults.model
    )
    
    print(f"\nResponse: {response.content}")
    print(f"Finish reason: {response.finish_reason}")


if __name__ == "__main__":
    asyncio.run(main())
