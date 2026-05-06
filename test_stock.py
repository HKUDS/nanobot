"""Test stock price tool using Sina API."""
import asyncio
from nanobot.agent.tools.market import StockPriceTool


async def main():
    tool = StockPriceTool()

    # Test real-time price with a valid stock code
    print("=== Real-time Price ===")
    result = await tool.execute(symbol="bj920000", market="cn", period="realtime")
    print(result)

    # Test with another stock
    print("\n=== Another Stock ===")
    result = await tool.execute(symbol="bj920001", market="cn", period="realtime")
    print(result)


if __name__ == "__main__":
    asyncio.run(main())
