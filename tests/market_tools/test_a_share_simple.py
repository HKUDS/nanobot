"""Simple A-share test."""
import asyncio
from nanobot.agent.tools.market import StockPriceTool


async def main():
    print("Testing A-share real-time price...")
    tool = StockPriceTool()
    
    # Test 1: Real-time price
    print("\n1. Testing bj920000 (安徽凤凰)...")
    result = await tool.execute(symbol="bj920000", market="cn", period="realtime")
    print(result)
    
    # Test 2: Another stock
    print("\n2. Testing bj920001 (纬达光电)...")
    result = await tool.execute(symbol="bj920001", market="cn", period="realtime")
    print(result)
    
    # Test 3: Historical data
    print("\n3. Testing historical data (5 days)...")
    result = await tool.execute(symbol="bj920000", market="cn", period="daily", days=5)
    print(result[:500])
    
    print("\nAll tests completed!")


if __name__ == "__main__":
    asyncio.run(main())
