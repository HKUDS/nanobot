"""Quick test for key akshare APIs."""
import akshare as ak
import os


def disable_proxy():
    """Disable proxy for better connectivity."""
    for key in ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy']:
        os.environ.pop(key, None)


def quick_test(name, func, *args, **kwargs):
    """Quick test a single API."""
    try:
        print(f"Testing {name}...", end=" ")
        result = func(*args, **kwargs)
        if hasattr(result, 'shape'):
            print(f"✅ OK ({result.shape[0]} rows)")
        else:
            print(f"✅ OK")
        return True
    except Exception as e:
        print(f"❌ FAIL: {str(e)[:50]}")
        return False


def main():
    disable_proxy()
    
    print("="*60)
    print("Akshare API 快速测试")
    print("="*60 + "\n")
    
    results = {}
    
    # 核心API测试
    print("股票市场:")
    results['A股实时'] = quick_test("A股实时", ak.stock_zh_a_spot)
    results['港股实时'] = quick_test("港股实时", ak.stock_hk_spot)
    results['美股实时'] = quick_test("美股实时", ak.stock_us_spot)
    
    print("\n指数:")
    results['上证指数'] = quick_test("上证指数", ak.stock_zh_index_spot_sina)
    
    print("\n基金:")
    results['ETF'] = quick_test("ETF基金", ak.fund_etf_spot_em)
    
    print("\n期货:")
    results['期货'] = quick_test("国内期货", ak.futures_zh_spot)
    
    print("\n外汇:")
    results['外汇'] = quick_test("外汇牌价", ak.currency_boc_sina)
    
    print("\n加密货币:")
    results['加密货币'] = quick_test("加密货币", ak.crypto_js_spot)
    
    print("\n债券:")
    results['可转债'] = quick_test("可转债", ak.bond_cb_spot_jsl)
    
    print("\n宏观数据:")
    results['GDP'] = quick_test("GDP数据", ak.macro_china_gdp_yearly)
    results['CPI'] = quick_test("CPI数据", ak.macro_china_cpi)
    
    # 总结
    print("\n" + "="*60)
    total = len(results)
    success = sum(results.values())
    print(f"测试结果: {success}/{total} 可用 ({success/total*100:.0f}%)")
    print("="*60)
    
    print("\n✅ 可用的API:")
    for name, status in results.items():
        if status:
            print(f"  • {name}")
    
    print("\n❌ 不可用的API:")
    for name, status in results.items():
        if not status:
            print(f"  • {name}")


if __name__ == "__main__":
    main()
