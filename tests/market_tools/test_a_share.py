"""Test A-share stock functionality in market.py"""
import asyncio
from nanobot.agent.tools.market import StockPriceTool


async def test_cn_realtime():
    """Test A-share real-time prices."""
    print("="*70)
    print("测试1: A股实时行情")
    print("="*70)
    
    tool = StockPriceTool()
    
    # Test multiple A-share stocks
    test_stocks = [
        ("bj920000", "安徽凤凰"),
        ("bj920001", "纬达光电"),
    ]
    
    for symbol, name in test_stocks:
        print(f"\n📊 测试股票: {name} ({symbol})")
        print("-" * 70)
        try:
            result = await tool.execute(symbol=symbol, market="cn", period="realtime")
            print(result)
        except Exception as e:
            print(f"❌ 错误: {e}")
        
        # Small delay between requests
        await asyncio.sleep(1)


async def test_cn_historical():
    """Test A-share historical data."""
    print("\n" + "="*70)
    print("测试2: A股历史数据")
    print("="*70)
    
    tool = StockPriceTool()
    
    # Test historical data for one stock
    symbol = "bj920000"
    name = "安徽凤凰"
    
    print(f"\n📈 测试股票: {name} ({symbol})")
    print("-" * 70)
    
    # Test different periods
    for days in [5, 10, 30]:
        print(f"\n📅 获取最近 {days} 天的数据...")
        try:
            result = await tool.execute(
                symbol=symbol, 
                market="cn", 
                period="daily", 
                days=days
            )
            print(result[:500] + "..." if len(result) > 500 else result)
        except Exception as e:
            print(f"❌ 错误: {e}")
        
        await asyncio.sleep(1)


async def test_cn_edge_cases():
    """Test edge cases."""
    print("\n" + "="*70)
    print("测试3: 边界情况测试")
    print("="*70)
    
    tool = StockPriceTool()
    
    # Test invalid stock code
    print("\n🔍 测试无效股票代码:")
    print("-" * 70)
    result = await tool.execute(symbol="INVALID", market="cn", period="realtime")
    print(result)
    
    # Test with very short history
    print("\n🔍 测试极短历史数据 (1天):")
    print("-" * 70)
    result = await tool.execute(symbol="bj920000", market="cn", period="daily", days=1)
    print(result[:300] + "..." if len(result) > 300 else result)


async def test_cn_cache():
    """Test caching mechanism."""
    print("\n" + "="*70)
    print("测试4: 缓存机制测试")
    print("="*70)
    
    tool = StockPriceTool()
    symbol = "bj920000"
    
    print(f"\n⚡ 第一次请求 {symbol}...")
    start_time = asyncio.get_event_loop().time()
    result1 = await tool.execute(symbol=symbol, market="cn", period="realtime")
    time1 = asyncio.get_event_loop().time() - start_time
    print(f"耗时: {time1:.2f}秒")
    
    print(f"\n⚡ 第二次请求 {symbol} (应该使用缓存)...")
    start_time = asyncio.get_event_loop().time()
    result2 = await tool.execute(symbol=symbol, market="cn", period="realtime")
    time2 = asyncio.get_event_loop().time() - start_time
    print(f"耗时: {time2:.2f}秒")
    
    if time2 < time1:
        print(f"✅ 缓存生效! 速度提升: {(time1-time2)/time1*100:.1f}%")
    else:
        print("⚠️ 缓存可能未生效或首次请求较快")


async def main():
    """Run all A-share tests."""
    print("\n" + "🐈"*35)
    print(" "*20 + "A股功能全面测试")
    print("🐈"*35 + "\n")
    
    try:
        # Run tests in sequence
        await test_cn_realtime()
        await test_cn_historical()
        await test_cn_edge_cases()
        await test_cn_cache()
        
        print("\n" + "="*70)
        print("✅ 所有A股测试完成!")
        print("="*70)
        
    except Exception as e:
        print(f"\n❌ 测试过程中出现错误: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
