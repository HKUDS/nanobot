#!/usr/bin/env python3
"""
回测报告生成脚本
基于回测结果生成标准格式的报告
用法: python generate_report.py --results results.json --output report.md
"""
import json
import argparse
from datetime import datetime
from pathlib import Path


def calculate_metrics(results: dict) -> dict:
    """计算绩效指标"""
    trades = results.get("trades", [])

    if not trades:
        return {
            "total_trades": 0,
            "win_rate": 0,
            "profit_loss_ratio": 0,
        }

    # 统计交易
    wins = sum(1 for t in trades if t.get("pnl", 0) > 0)
    losses = sum(1 for t in trades if t.get("pnl", 0) < 0)

    win_rate = wins / len(trades) * 100 if trades else 0

    # 盈亏比
    avg_win = sum(t.get("pnl", 0) for t in trades if t.get("pnl", 0) > 0) / wins if wins else 0
    avg_loss = abs(sum(t.get("pnl", 0) for t in trades if t.get("pnl", 0) < 0) / losses) if losses else 0
    profit_loss_ratio = avg_win / avg_loss if avg_loss else 0

    return {
        "total_trades": len(trades),
        "wins": wins,
        "losses": losses,
        "win_rate": win_rate,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "profit_loss_ratio": profit_loss_ratio,
    }


def generate_markdown_report(results: dict) -> str:
    """生成 Markdown 格式报告"""
    config = results.get("config", {})
    metrics = results.get("metrics", {})
    trades = results.get("trades", [])

    # 计算交易统计
    trade_stats = calculate_metrics(results)

    # 生成报告
    report = f"""# 策略回测报告

## 基本信息
- 策略名称：{config.get("name", "未命名")}
- 回测期间：{config.get("start_date", "N/A")} ~ {config.get("end_date", "N/A")}
- 初始资金：{config.get("initial_capital", 0):,.0f}元
- 策略参数：{json.dumps(config.get("parameters", {}), ensure_ascii=False)}

## 收益表现
- 年化收益率：{metrics.get("annual_return", 0):.2f}%
- 累计收益率：{metrics.get("total_return", 0):.2f}%
- 基准收益率：{metrics.get("benchmark_return", 0):.2f}%
- 超额收益：{metrics.get("excess_return", 0):.2f}%

## 风险指标
- 夏普比率：{metrics.get("sharpe_ratio", 0):.2f}
- 卡玛比率：{metrics.get("calmar_ratio", 0):.2f}
- 最大回撤：{metrics.get("max_drawdown", 0):.2f}%
- 年化波动率：{metrics.get("volatility", 0):.2f}%

## 交易统计
- 总交易次数：{trade_stats["total_trades"]}
- 胜率：{trade_stats["win_rate"]:.2f}%
- 盈亏比：{trade_stats["profit_loss_ratio"]:.2f}
- 盈利交易：{trade_stats["wins"]}
- 亏损交易：{trade_stats["losses"]}

## 成本假设
- 佣金：{config.get("commission_rate", 0.0003)*100:.4f}%
- 印花税：{config.get("stamp_duty", 0.001)*100:.2f}%
- 滑点：{config.get("slippage", 0.0005)*100:.4f}%

## 样本外表现
- 样本外夏普：{metrics.get("oos_sharpe", "N/A")}
- 样本外回撤：{metrics.get("oos_max_drawdown", "N/A")}%

## 生成时间
{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
"""

    return report


def main():
    parser = argparse.ArgumentParser(description="生成回测报告")
    parser.add_argument("--results", required=True, help="回测结果 JSON 文件路径")
    parser.add_argument("--output", required=True, help="输出报告 Markdown 文件路径")
    args = parser.parse_args()

    # 读取结果
    with open(args.results, "r", encoding="utf-8") as f:
        results = json.load(f)

    # 生成报告
    report = generate_markdown_report(results)

    # 写入文件
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(report)

    print(f"报告已生成: {args.output}")


if __name__ == "__main__":
    main()
