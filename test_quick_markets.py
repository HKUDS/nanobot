"""Quick test for US stock and crypto."""
import asyncio
from nanobot.agent.tools.market import StockPriceTool, CryptoPriceTool


async def test_us_stock_single():
    """Test single US stock - faster approach."""
    print("=" * 60)
    print("测试: 美股实时行情 (AAPL)")
    print("=" * 60)
    
    import akshare as ak
    import os
    
    # Disable proxy
    for key in ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy']:
        os.environ.pop(key, None)
    
    try:
        df = ak.stock_us_spot()
        stock = df[df['代码'] == 'AAPL']
        
        if not stock.empty:
            row = stock.iloc[0]
            print(f"✅ 找到股票: {row.get('名称', 'N/A')} ({row.get('代码', 'N/A')})")
            print(f"💰 当前价格: ${row.get('最新价', 0):.2f}")
            print(f"📊 涨跌幅: {row.get('涨跌幅', 0):.2f}%")
        else:
            print("❌ 未找到 AAPL 股票")
            print(f"可用股票代码示例: {df['代码'].head(5).tolist()}")
    except Exception as e:
        print(f"❌ 错误: {e}")
        import traceback
        traceback.print_exc()


async def test_crypto_quick():
    """Test cryptocurrency prices."""
    print("\n" + "=" * 60)
    print("测试: 加密货币价格")
    print("=" * 60)
    
    tool = CryptoPriceTool()
    
    # Test Bitcoin
    print("\n🔸 比特币 (BTC)")
    result = await tool.execute(symbol="BTC", currency="USD")
    print(result)
    
    # Test Ethereum
    print("\n🔸 以太坊 (ETH)")
    result = await tool.execute(symbol="ETH", currency="USD")
    print(result)


async def main():
    """Run quick tests."""
    await test_us_stock_single()
    await test_crypto_quick()
    
    print("\n" + "=" * 60)
    print("✅ 测试完成！")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
