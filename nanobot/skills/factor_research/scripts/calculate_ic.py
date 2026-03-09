#!/usr/bin/env python3
"""
因子 IC 分析脚本
计算因子的 IC (Information Coefficient) 和 ICIR
用法: python calculate_ic.py --factor factor.csv --returns returns.csv --output ic_report.json
"""
import pandas as pd
import numpy as np
import argparse
import json
from datetime import datetime
from scipy.stats import spearmanr


def calculate_ic(factor_values: pd.Series, returns: pd.Series) -> float:
    """计算 IC (Spearman 相关系数)"""
    # 去除 NaN
    valid = factor_values.notna() & returns.notna()
    if valid.sum() < 10:
        return 0.0

    ic, _ = spearmanr(factor_values[valid], returns[valid])
    return ic


def calculate_ic_series(factor_df: pd.DataFrame, returns_df: pd.DataFrame) -> pd.Series:
    """计算 IC 时序序列"""
    dates = factor_df.index
    ic_series = []

    for date in dates:
        if date not in returns_df.index:
            continue

        # 获取当日因子值和下期收益
        factor_vals = factor_df.loc[date]
        next_returns = returns_df.loc[date] if date in returns_df.index else pd.Series()

        if next_returns.empty:
            continue

        ic = calculate_ic(factor_vals, next_returns)
        ic_series.append({"date": str(date), "ic": ic})

    return pd.DataFrame(ic_series).set_index("date")["ic"]


def analyze_factor(factor_file: str, returns_file: str) -> dict:
    """分析因子"""
    # 读取数据
    factor = pd.read_csv(factor_file, index_col=0, parse_dates=True)
    returns = pd.read_csv(returns_file, index_col=0, parse_dates=True)

    # 计算 IC 序列
    ic_series = calculate_ic_series(factor, returns)

    if ic_series.empty:
        return {"error": "数据不足，无法计算 IC"}

    # 计算统计指标
    ic_mean = ic_series.mean()
    ic_std = ic_series.std()
    icir = ic_mean / ic_std if ic_std > 0 else 0

    # IC 分布
    ic_positive = (ic_series > 0).sum() / len(ic_series) * 100

    # 按年度统计
    ic_series.index = pd.to_datetime(ic_series.index)
    yearly_ic = ic_series.groupby(ic_series.index.year).mean()

    return {
        "ic_mean": float(ic_mean),
        "ic_std": float(ic_std),
        "icir": float(icir),
        "ic_positive_rate": float(ic_positive),
        "ic_count": len(ic_series),
        "yearly_ic": {str(k): float(v) for k, v in yearly_ic.items()},
        "rating": "优秀" if abs(ic_mean) > 0.05 else (
            "良好" if abs(ic_mean) > 0.03 else (
            "一般" if abs(ic_mean) > 0.01 else "较差"
        ))
    }


def main():
    parser = argparse.ArgumentParser(description="因子 IC 分析")
    parser.add_argument("--factor", required=True, help="因子值文件 (CSV)")
    parser.add_argument("--returns", required=True, help="收益文件 (CSV)")
    parser.add_argument("--output", help="输出 JSON 文件路径")
    args = parser.parse_args()

    # 分析
    result = analyze_factor(args.factor, args.returns)

    # 输出
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        print(f"结果已保存: {args.output}")
    else:
        print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
