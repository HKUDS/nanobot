"""Test crypto prices."""
import asyncio
from nanobot.agent.tools.market import CryptoPriceTool


async def main():
    tool = CryptoPriceTool()
    
    print("=" * 60)
    print("测试: 比特币 (BTC)")
    print("=" * 60)
    result = await tool.execute(symbol="BTC", currency="USD")
    print(result)
    
    print("\n" + "=" * 60)
    print("测试: 以太坊 (ETH)")
    print("=" * 60)
    result = await tool.execute(symbol="ETH", currency="USD")
    print(result)


if __name__ == "__main__":
    asyncio.run(main())
