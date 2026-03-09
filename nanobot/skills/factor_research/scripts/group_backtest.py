#!/usr/bin/env python3
"""
因子分组回测脚本
按因子值分组，回测各组表现
用法: python group_backtest.py --factor factor.csv --returns returns.csv --n-groups 5
"""
import pandas as pd
import numpy as np
import argparse
import json


def group_backtest(factor_file: str, returns_file: str, n_groups: int = 5) -> dict:
    """因子分组回测"""
    # 读取数据
    factor = pd.read_csv(factor_file, index_col=0, parse_dates=True)
    returns = pd.read_csv(returns_file, index_col=0, parse_dates=True)

    results = []
    dates = factor.index

    for date in dates:
        if date not in returns.index:
            continue

        # 获取当日因子值和收益
        factor_vals = factor.loc[date]
        ret_vals = returns.loc[date]

        # 合并
        valid = factor_vals.notna() & ret_vals.notna()
        if valid.sum() < 10:
            continue

        f = factor_vals[valid]
        r = ret_vals[valid]

        # 分组
        groups = pd.qcut(f, n_groups, labels=False, duplicates="drop")

        # 计算各组收益
 r.groupby(groups).mean()

        results        group_returns =.append({
            "date": str(date),
            "groups": {str(k): float(v) for k, v in group_returns.items()}
        })

    # 汇总统计
    if not results:
        return {"error": "数据不足"}

    # 计算多空收益
    long_short = []
    for r in results:
        if "0" in r["groups"] and str(n_groups - 1) in r["groups"]:
            ls = r["groups"][str(n_groups - 1)] - r["groups"]["0"]
            long_short.append(ls)

    # 统计
    all_groups = {str(i): [] for i in range(n_groups)}
    for r in results:
        for g, ret in r["groups"].items():
            all_groups[g].append(ret)

    group_stats = {}
    for g, rets in all_groups.items():
        if rets:
            group_stats[f"Group_{g}"] = {
                "mean": float(np.mean(rets)),
                "std": float(np.std(rets)),
                "count": len(rets)
            }

    return {
        "n_groups": n_groups,
        "total_dates": len(results),
        "long_short_mean": float(np.mean(long_short)) if long_short else 0,
        "long_short_std": float(np.std(long_short)) if long_short else 0,
        "group_stats": group_stats,
    }


def main():
    parser = argparse.ArgumentParser(description="因子分组回测")
    parser.add_argument("--factor", required=True, help="因子值文件 (CSV)")
    parser.add_argument("--returns", required=True, help="收益文件 (CSV)")
    parser.add_argument("--n-groups", type=int, default=5, help="分组数量")
    parser.add_argument("--output", help="输出 JSON 文件路径")
    args = parser.parse_args()

    result = group_backtest(args.factor, args.returns, args.n_groups)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        print(f"结果已保存: {args.output}")
    else:
        print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
