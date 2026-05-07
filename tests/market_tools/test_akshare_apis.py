"""Test which akshare APIs are available and working."""
import akshare as ak
import os
from datetime import datetime


def disable_proxy():
    """Disable proxy for better connectivity."""
    for key in ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy', 
                'ALL_PROXY', 'all_proxy']:
        os.environ.pop(key, None)
    os.environ['NO_PROXY'] = '*'


def test_api(name, func, *args, **kwargs):
    """Test a single API endpoint."""
    try:
        print(f"\n{'='*60}")
        print(f"Testing: {name}")
        print(f"{'='*60}")
        
        result = func(*args, **kwargs)
        
        if hasattr(result, 'shape'):
            # DataFrame
            print(f"✅ SUCCESS - Shape: {result.shape}")
            print(f"Columns: {result.columns.tolist()[:5]}...")
            print(f"Sample:\n{result.head(2)}")
            return True
        elif isinstance(result, dict):
            print(f"✅ SUCCESS - Dict with keys: {list(result.keys())[:5]}")
            return True
        else:
            print(f"✅ SUCCESS - Type: {type(result).__name__}")
            return True
            
    except Exception as e:
        print(f"❌ FAILED - {type(e).__name__}: {str(e)[:100]}")
        return False


def main():
    disable_proxy()
    
    results = {}
    
    # ========== 股票实时行情 ==========
    print("\n" + "="*60)
    print("📊 股票实时行情测试")
    print("="*60)
    
    results['A股实时-新浪'] = test_api(
        "A股实时行情 (新浪财经)",
        ak.stock_zh_a_spot
    )
    
    results['港股实时-新浪'] = test_api(
        "港股实时行情 (新浪财经)",
        ak.stock_hk_spot
    )
    
    results['美股实时-新浪'] = test_api(
        "美股实时行情 (新浪财经)",
        ak.stock_us_spot
    )
    
    # ========== 股票历史数据 ==========
    print("\n" + "="*60)
    print("📈 股票历史数据测试")
    print("="*60)
    
    results['A股历史-新浪'] = test_api(
        "A股历史数据 (新浪财经)",
        ak.stock_zh_a_daily,
        symbol="bj920000",
        start_date="20260401",
        end_date="20260506"
    )
    
    # ========== 指数数据 ==========
    print("\n" + "="*60)
    print("📉 指数数据测试")
    print("="*60)
    
    results['上证指数'] = test_api(
        "上证指數实时行情",
        ak.stock_zh_index_spot_sina
    )
    
    results['深证成指'] = test_api(
        "深证成指实时行情",
        lambda: ak.stock_zh_index_spot_sina()[ak.stock_zh_index_spot_sina()['代码'] == '399001']
    )
    
    # ========== 基金数据 ==========
    print("\n" + "="*60)
    print("💰 基金数据测试")
    print("="*60)
    
    results['ETF基金'] = test_api(
        "ETF基金实时行情",
        ak.fund_etf_spot_em
    )
    
    # ========== 期货数据 ==========
    print("\n" + "="*60)
    print("📦 期货数据测试")
    print("="*60)
    
    results['国内期货'] = test_api(
        "国内期货实时行情",
        ak.futures_zh_spot
    )
    
    # ========== 外汇数据 ==========
    print("\n" + "="*60)
    print("💱 外汇数据测试")
    print("="*60)
    
    results['外汇牌价'] = test_api(
        "外汇实时牌价",
        ak.currency_boc_sina
    )
    
    # ========== 债券数据 ==========
    print("\n" + "="*60)
    print("📜 债券数据测试")
    print("="*60)
    
    results['可转债'] = test_api(
        "可转债实时行情",
        ak.bond_cb_spot_jsl
    )
    
    # ========== 加密货币 ==========
    print("\n" + "="*60)
    print("₿ 加密货币测试")
    print("="*60)
    
    results['加密货币'] = test_api(
        "加密货币实时价格",
        ak.crypto_js_spot
    )
    
    # ========== 宏观数据 ==========
    print("\n" + "="*60)
    print("🌍 宏观经济数据测试")
    print("="*60)
    
    results['GDP数据'] = test_api(
        "中国GDP数据",
        ak.macro_china_gdp_yearly
    )
    
    results['CPI数据'] = test_api(
        "中国CPI数据",
        ak.macro_china_cpi
    )
    
    # ========== 新闻数据 ==========
    print("\n" + "="*60)
    print("📰 新闻数据测试")
    print("="*60)
    
    results['财经新闻'] = test_api(
        "新浪财经新闻",
        ak.news_economic_baidu
    )
    
    # ========== 期权数据 ==========
    print("\n" + "="*60)
    print("🎯 期权数据测试")
    print("="*60)
    
    results['期权行情'] = test_api(
        "期权实时行情",
        ak.option_cffex_sz50_list_sina
    )
    
    # ========== 总结 ==========
    print("\n" + "="*60)
    print("📊 测试结果汇总")
    print("="*60)
    
    total = len(results)
    success = sum(1 for v in results.values() if v)
    failed = total - success
    
    print(f"\n总计: {total} 个接口")
    print(f"✅ 成功: {success}")
    print(f"❌ 失败: {failed}")
    print(f"成功率: {success/total*100:.1f}%")
    
    print("\n可用的接口:")
    for name, status in results.items():
        if status:
            print(f"  ✅ {name}")
    
    print("\n不可用的接口:")
    for name, status in results.items():
        if not status:
            print(f"  ❌ {name}")
    
    # 保存结果
    with open('akshare_api_test_results.txt', 'w', encoding='utf-8') as f:
        f.write(f"Akshare API 测试结果 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write("="*60 + "\n\n")
        for name, status in results.items():
            status_str = "✅ 可用" if status else "❌ 不可用"
            f.write(f"{status_str} - {name}\n")
    
    print(f"\n详细结果已保存到: akshare_api_test_results.txt")


if __name__ == "__main__":
    main()
