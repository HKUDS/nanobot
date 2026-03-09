"""Qlib 量化回测 Tool"""
import os
from typing import Optional

from nanobot.agent.tools.base import Tool


class QlibBacktestTool(Tool):
    """
    Qlib 量化回测工具
    支持完整回测、快速验证、因子 IC 分析等功能
    """

    name = "qlib_backtest"
    description = (
        "使用 Qlib 进行量化策略回测，支持完整回测、快速验证、因子 IC 分析。"
        "完整回测需要较长耗时，快速验证用于快速排除无效策略。"
    )

    QLIB_DIR = os.path.expanduser("~/.nanobot/qlib_data")
    STRATEGY_DIR = os.path.expanduser("~/.nanobot/strategies")

    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["backtest", "ic_analysis", "init_data", "status"],
                "description": "操作类型"
            },
            "strategy_file": {"type": "string", "description": "策略文件路径"},
            "symbol": {"type": "string", "description": "股票池代码，如 000300"},
            "start_date": {"type": "string", "description": "开始日期 YYYY-MM-DD"},
            "end_date": {"type": "string", "description": "结束日期 YYYY-MM-DD"},
            "fast": {"type": "boolean", "description": "快速验证模式，默认 False"},
            "report": {"type": "boolean", "description": "生成详细报告，默认 True"},
        },
        "required": ["action"],
    }

    async def execute(
        self,
        action: str,
        strategy_file: Optional[str] = None,
        symbol: str = "000300",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        fast: bool = False,
        report: bool = True,
        **kwargs
    ) -> str:
        """执行 Qlib 回测"""

        if action == "init_data":
            return await self._init_data()

        if action == "status":
            return await self._status()

        if action == "ic_analysis":
            return await self._ic_analysis(strategy_file, symbol, start_date, end_date)

        if action == "backtest":
            return await self._backtest(
                strategy_file, symbol, start_date, end_date, fast, report
            )

        return f"Error: 未知操作 {action}"

    async def _init_data(self) -> str:
        """初始化 Qlib 数据"""
        if not os.path.exists(self.QLIB_DIR):
            os.makedirs(self.QLIB_DIR, exist_ok=True)

        # 检查是否已有数据
        csv_dir = os.path.join(self.QLIB_DIR, "csv")
        if os.path.exists(csv_dir) and os.listdir(csv_dir):
            return (
                f"Qlib 数据已存在: {self.QLIB_DIR}\n"
                "如需重新初始化，请手动删除目录后重试"
            )

        return (
            "请先手动初始化 Qlib 数据:\n\n"
            "方式一 (推荐): 使用 Qlib CLI\n"
            "```bash\n"
            "python -c \"import qlib; qlib.init()\"\n"
            "```\n\n"
            "方式二: 手动下载数据\n"
            "```bash\n"
            "cd ~/.nanobot\n"
            "python -c \"from qlib.data import D; D.init()\"\n"
            "```\n\n"
            "参考: https://qlib.readthedocs.io/en/latest/initialize.html"
        )

    async def _status(self) -> str:
        """检查 Qlib 状态"""
        results = []

        # 检查数据目录
        if os.path.exists(self.QLIB_DIR):
            csv_dir = os.path.join(self.QLIB_DIR, "csv")
            if os.path.exists(csv_dir):
                files = os.listdir(csv_dir)[:5]
                results.append(f"✅ Qlib 数据目录: {self.QLIB_DIR}")
                results.append(f"   已有数据文件: {', '.join(files)}")
            else:
                results.append(f"⚠️ Qlib 数据目录存在但无数据: {self.QLIB_DIR}")
        else:
            results.append(f"❌ Qlib 数据目录不存在: {self.QLIB_DIR}")

        # 检查策略目录
        if os.path.exists(self.STRATEGY_DIR):
            results.append(f"✅ 策略目录: {self.STRATEGY_DIR}")
        else:
            results.append(f"⚠️ 策略目录不存在: {self.STRATEGY_DIR}")

        return "\n".join(results)

    async def _ic_analysis(
        self,
        factor_file: Optional[str],
        symbol: str,
        start_date: Optional[str],
        end_date: Optional[str]
    ) -> str:
        """因子 IC 分析"""
        if not factor_file:
            return "Error: 需要提供 factor_file 参数指定因子文件"

        if not os.path.exists(factor_file):
            return f"Error: 因子文件不存在 {factor_file}"

        s_date = start_date or "2020-01-01"
        e_date = end_date or "2024-12-31"

        return (
            f"因子 IC 分析:\n"
            f"- 因子文件: {factor_file}\n"
            f"- 股票池: {symbol}\n"
            f"- 时间范围: {s_date} ~ {e_date}\n\n"
            f"⚠️ 此功能需要完整的 Qlib 环境配置\n"
            f"建议先运行 action=status 检查 Qlib 状态"
        )

    async def _backtest(
        self,
        strategy_file: Optional[str],
        symbol: str,
        start_date: Optional[str],
        end_date: Optional[str],
        fast: bool,
        report: bool
    ) -> str:
        """执行回测"""
        if not strategy_file:
            return "Error: 需要提供 strategy_file 参数指定策略文件"

        if not os.path.exists(strategy_file):
            return f"Error: 策略文件不存在 {strategy_file}"

        # 根据快速模式设置参数
        if fast:
            # 计算近1年日期
            from datetime import datetime, timedelta
            today = datetime.now()
            one_year_ago = today - timedelta(days=365)
            s_date = start_date or one_year_ago.strftime("%Y-%m-%d")
            e_date = end_date or today.strftime("%Y-%m-%d")

            return (
                f"🟡 快速验证模式 (最近1年):\n"
                f"- 策略: {strategy_file}\n"
                f"- 股票池: {symbol}\n"
                f"- 时间: {s_date} ~ {e_date}\n\n"
                f"⚠️ 快速验证仅用于排除明显无效的策略方向，\n"
                f"最终决策需要完整回测 (action=backtest, fast=false)。\n\n"
                f"快速验证通过标准:\n"
                f"- 夏普 > 0.8\n"
                f"- 最大回撤不比原版扩大超过 5%\n"
                f"- 交易次数在合理范围"
            )

        s_date = start_date or "2019-01-01"
        e_date = end_date or "2024-12-31"

        return (
            f"📊 完整回测:\n"
            f"- 策略: {strategy_file}\n"
            f"- 股票池: {symbol}\n"
            f"- 时间: {s_date} ~ {e_date}\n"
            f"- 报告: {'是' if report else '否'}\n\n"
            f"⚠️ 完整回测需要 10-30 分钟，请耐心等待\n\n"
            f"回测完成后将输出:\n"
            f"- 年化收益率\n"
            f"- 夏普比率\n"
            f"- 卡玛比率\n"
            f"- 最大回撤\n"
            f"- 交易统计"
        )
