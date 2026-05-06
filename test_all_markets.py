"""Test market tools for different markets."""
import asyncio
from nanobot.agent.tools.market import StockPriceTool, CryptoPriceTool


async def test_cn_stock():
    """Test A-share stock."""
    print("=" * 60)
    print("测试1: A股实时行情")
    print("=" * 60)
    tool = StockPriceTool()
    result = await tool.execute(symbol="bj920000", market="cn", period="realtime")
    print(result)


async def test_hk_stock():
    """Test Hong Kong stock."""
    print("=" * 60)
    print("测试2: 港股实时行情")
    print("=" * 60)
    tool = StockPriceTool()
    # 使用腾讯控股作为示例
    result = await tool.execute(symbol="00700", market="hk", period="realtime")
    print(result)


async def test_us_stock():
    """Test US stock."""
    print("=" * 60)
    print("测试3: 美股实时行情")
    print("=" * 60)
    tool = StockPriceTool()
    # 使用苹果股票作为示例
    result = await tool.execute(symbol="AAPL", market="us", period="realtime")
    print(result)


async def test_crypto():
    """Test cryptocurrency."""
    print("=" * 60)
    print("测试4: 加密货币价格")
    print("=" * 60)
    tool = CryptoPriceTool()
    # 测试比特币
    result = await tool.execute(symbol="BTC", currency="USD")
    print(result)
    
    print("\n" + "-" * 60)
    # 测试以太坊
    result = await tool.execute(symbol="ETH", currency="USD")
    print(result)


async def main():
    """Run all tests."""
    try:
        await test_cn_stock()
        print("\n")
        
        await test_hk_stock()
        print("\n")
        
        await test_us_stock()
        print("\n")
        
        await test_crypto()
        
    except Exception as e:
        print(f"\n❌ 测试过程中出现错误: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
