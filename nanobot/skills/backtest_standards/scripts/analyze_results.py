#!/usr/bin/env python3
"""
回测结果分析脚本
分析回测结果，检查过拟合信号
用法: python analyze_results.py --results results.json
"""
import json
import sys
from pathlib import Path


def analyze_drawdown(equity_curve: list) -> dict:
    """分析回撤"""
    if not equity_curve:
        return {"max_drawdown": 0, "max_drawdown_pct": 0}

    peak = equity_curve[0]
    max_dd = 0
    max_dd_pct = 0

    for value in equity_curve:
        if value > peak:
            peak = value
        dd = (peak - value) / peak if peak > 0 else 0
        if dd > max_dd:
            max_dd = dd
            max_dd_pct = dd * 100

    return {
        "max_drawdown": max_dd,
        "ct": max_dd_pct,
    }


def analyze_returns(returns: list) -> dict:
    """分析max_drawdown_p收益"""
    if not returns:
        return {}

    import numpy as np

    returns_array = np.array(returns)

    return {
        "mean": float(np.mean(returns_array)),
        "std": float(np.std(returns_array)),
        "min": float(np.min(returns_array)),
        "max": float(np.max(returns_array)),
        "skewness": float(np.mean(returns_array ** 3) / np.std(returns_array) ** 3) if np.std(returns_array) > 0 else 0,
        "kurtosis": float(np.mean(returns_array ** 4) / np.std(returns_array) ** 4) if np.std(returns_array) > 0 else 0,
    }


def check_overfitting_signals(results: dict) -> list:
    """检查过拟合信号"""
    signals = []
    metrics = results.get("metrics", {})

    # 信号1: 回测收益极高
    annual_return = metrics.get("annual_return", 0)
    if annual_return > 50:
        signals.append({
            "severity": "high",
            "message": f"年化收益率 {annual_return:.1f}% 过高，可能存在过拟合",
        })

    # 信号2: 夏普比率异常
    sharpe = metrics.get("sharpe_ratio", 0)
    if sharpe > 3:
        signals.append({
            "severity": "high",
            "message": f"夏普比率 {sharpe:.2f} 过高，样本外可能失效",
        })

    # 信号3: 样本内外差异大
    is_sharpe = metrics.get("sharpe_ratio", 0)
    oos_sharpe = metrics.get("oos_sharpe", is_sharpe)
    if oos_sharpe and is_sharpe / oos_sharpe > 2:
        signals.append({
            "severity": "medium",
            "message": f"样本内/外夏普比率差异大 ({is_sharpe:.2f} vs {oos_sharpe:.2f})",
        })

    # 信号4: 交易次数过少
    total_trades = len(results.get("trades", []))
    if total_trades < 30:
        signals.append({
            "severity": "medium",
            "message": f"总交易次数 {total_trades} 较少，统计显著性不足",
        })

    return signals


def main():
    if len(sys.argv) < 2:
        print("用法: python analyze_results.py <results.json>")
        sys.exit(1)

    results_file = sys.argv[1]

    with open(results_file, "r", encoding="utf-8") as f:
        results = json.load(f)

    print("=" * 60)
    print("回测结果分析")
    print("=" * 60)

    # 基本信息
    config = results.get("config", {})
    print(f"\n策略: {config.get('name', '未命名')}")
    print(f"回测期: {config.get('start_date', 'N/A')} ~ {config.get('end_date', 'N/A')}")

    # 收益指标
    metrics = results.get("metrics", {})
    print(f"\n收益指标:")
    print(f"  年化收益率: {metrics.get('annual_return', 0):.2f}%")
    print(f"  累计收益率: {metrics.get('total_return', 0):.2f}%")
    print(f"  基准收益率: {metrics.get('benchmark_return', 0):.2f}%")

    # 风险指标
    print(f"\n风险指标:")
    print(f"  夏普比率: {metrics.get('sharpe_ratio', 0):.2f}")
    print(f"  卡玛比率: {metrics.get('calmar_ratio', 0):.2f}")
    print(f"  最大回撤: {metrics.get('max_drawdown', 0):.2f}%")

    # 过拟合检查
    signals = check_overfitting_signals(results)
    if signals:
        print(f"\n⚠️ 过拟合信号:")
        for signal in signals:
            emoji = "🔴" if signal["severity"] == "high" else "🟡"
            print(f"  {emoji} {signal['message']}")
    else:
        print(f"\n✅ 未检测到明显过拟合信号")

    print("\n" + "=" * 60)


if __name__ == "__main__":
    main()
