"""模拟交易 (Paper Trading) Tool"""
import os
import json
from typing import Dict, List, Optional
from datetime import datetime, date
from pathlib import Path
from dataclasses import dataclass, asdict

from nanobot.agent.tools.base import Tool


@dataclass
class Position:
    """持仓"""
    symbol: str
    name: str
    quantity: int      # 持股数量
    cost: float        # 成本价
    current: float     # 当前价
    pnl: float         # 浮动盈亏
    pnl_pct: float     # 盈亏比例


class PaperTradingTool(Tool):
    """
    模拟交易跟踪器
    基于每日收盘数据更新虚拟持仓，记录每日盈亏
    """

    name = "paper_trading"
    description = (
        "模拟交易跟踪，支持创建策略模拟、查询持仓、查看绩效报告。"
        "模拟交易基于每日收盘数据，不涉及真实资金。"
    )

    BASE_DIR = os.path.expanduser("~/.nanobot/paper_trading")

    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["create", "status", "positions", "trades", "performance", "close_position"],
                "description": "操作类型"
            },
            "strategy_id": {"type": "string", "description": "策略ID"},
            "symbol": {"type": "string", "description": "股票代码"},
            "name": {"type": "string", "description": "股票名称"},
            "quantity": {"type": "integer", "description": "数量"},
            "price": {"type": "number", "description": "价格"},
            "action_type": {"type": "string", "description": "买入/卖出: buy/sell"},
            "initial_capital": {"type": "number", "description": "初始资金，默认100万"},
            "days": {"type": "integer", "description": "查询天数"},
        },
        "required": ["action"],
    }

    def _get_strategy_dir(self, strategy_id: str) -> Path:
        """获取策略目录"""
        path = Path(self.BASE_DIR) / strategy_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _load_config(self, strategy_id: str) -> Dict:
        """加载策略配置"""
        config_file = self._get_strategy_dir(strategy_id) / "config.json"
        if not config_file.exists():
            return {}
        with open(config_file) as f:
            return json.load(f)

    def _save_config(self, strategy_id: str, config: Dict):
        """保存策略配置"""
        config_file = self._get_strategy_dir(strategy_id) / "config.json"
        with open(config_file, "w") as f:
            json.dump(config, f, indent=2)

    def _load_positions(self, strategy_id: str) -> List[Position]:
        """加载持仓"""
        pos_file = self._get_strategy_dir(strategy_id) / "positions.json"
        if not pos_file.exists():
            return []

        with open(pos_file) as f:
            data = json.load(f)
            return [Position(**p) for p in data]

    def _save_positions(self, strategy_id: str, positions: List[Position]):
        """保存持仓"""
        pos_file = self._get_strategy_dir(strategy_id) / "positions.json"
        with open(pos_file, "w") as f:
            json.dump([asdict(p) for p in positions], f, indent=2)

    def _load_nav(self, strategy_id: str) -> List[Dict]:
        """加载净值"""
        nav_file = self._get_strategy_dir(strategy_id) / "nav.json"
        if not nav_file.exists():
            return []

        with open(nav_file) as f:
            return json.load(f)

    def _save_nav(self, strategy_id: str, nav: List[Dict]):
        """保存净值"""
        nav_file = self._get_strategy_dir(strategy_id) / "nav.json"
        with open(nav_file, "w") as f:
            json.dump(nav, f, indent=2)

    def _load_trades(self, strategy_id: str) -> List[Dict]:
        """加载交易记录"""
        trade_file = self._get_strategy_dir(strategy_id) / "trades.json"
        if not trade_file.exists():
            return []

        with open(trade_file) as f:
            return json.load(f)

    def _save_trades(self, strategy_id: str, trades: List[Dict]):
        """保存交易记录"""
        trade_file = self._get_strategy_dir(strategy_id) / "trades.json"
        with open(trade_file, "w") as f:
            json.dump(trades, f, indent=2)

    async def execute(
        self,
        action: str,
        strategy_id: Optional[str] = None,
        symbol: Optional[str] = None,
        name: Optional[str] = None,
        quantity: int = 0,
        price: float = 0.0,
        action_type: str = "buy",
        initial_capital: float = 1_000_000,
        days: int = 20,
        **kwargs
    ) -> str:
        """执行操作"""

        if action == "create":
            return await self._create_strategy(strategy_id, initial_capital)

        if not strategy_id:
            return "Error: 需要提供 strategy_id 参数"

        if action == "status":
            return await self._status(strategy_id)

        if action == "positions":
            return await self._positions(strategy_id)

        if action == "trades":
            return await self._trades(strategy_id, days)

        if action == "performance":
            return await self._performance(strategy_id, days)

        if action == "close_position":
            return await self._close_position(strategy_id, symbol, quantity, price)

        return f"Error: 未知操作 {action}"

    async def _create_strategy(self, strategy_id: str, initial_capital: float) -> str:
        """创建模拟策略"""
        path = self._get_strategy_dir(strategy_id)

        config = {
            "strategy_id": strategy_id,
            "initial_capital": initial_capital,
            "created_at": datetime.now().isoformat(),
            "status": "active"
        }

        self._save_config(strategy_id, config)

        # 初始化空持仓和净值
        self._save_positions(strategy_id, [])
        self._save_nav(strategy_id, [{
            "date": date.today().strftime("%Y-%m-%d"),
            "nav": 1.0,
            "capital": initial_capital
        }])
        self._save_trades(strategy_id, [])

        return (
            f"✅ 创建模拟策略成功: {strategy_id}\n"
            f"初始资金: {initial_capital:,.0f}元\n\n"
            f"下一步: 使用 action=trade 买入股票开始模拟交易"
        )

    async def _status(self, strategy_id: str) -> str:
        """查询策略状态"""
        config = self._load_config(strategy_id)

        if not config:
            return f"Error: 策略 {strategy_id} 不存在，请先使用 action=create 创建"

        positions = self._load_positions(strategy_id)
        nav = self._load_nav(strategy_id)

        if nav:
            latest_nav = nav[-1]
            total_value = latest_nav.get("capital", 0)
            return (
                f"策略: {strategy_id}\n"
                f"- 状态: {config.get('status', 'unknown')}\n"
                f"- 初始资金: {config.get('initial_capital', 0):,.0f}元\n"
                f"- 当前净值: {latest_nav.get('nav', 1.0):.4f}\n"
                f"- 当前资金: {total_value:,.0f}元\n"
                f"- 持仓数量: {len(positions)}只"
            )

        return f"策略: {strategy_id}, 状态: {config.get('status', 'unknown')}"

    async def _positions(self, strategy_id: str) -> str:
        """查询当前持仓"""
        positions = self._load_positions(strategy_id)

        if not positions:
            return f"策略 {strategy_id} 当前无持仓"

        total_pnl = sum(p.pnl for p in positions)

        lines = [f"策略 {strategy_id} 当前持仓 ({len(positions)}只):\n"]
        lines.append(f"{'代码':<10} {'名称':<8} {'数量':>6} {'成本':>8} {'现价':>8} {'盈亏':>10} {'盈亏%':>8}")
        lines.append("-" * 70)

        for p in positions:
            lines.append(
                f"{p.symbol:<10} {p.name:<8} {p.quantity:>6} "
                f"{p.cost:>8.2f} {p.current:>8.2f} "
                f"{p.pnl:>+10.2f} {p.pnl_pct:>+8.2f}%"
            )

        lines.append("-" * 70)
        lines.append(f"总计浮动盈亏: {total_pnl:+.2f}元")

        return "\n".join(lines)

    async def _trades(self, strategy_id: str, days: int) -> str:
        """查询交易记录"""
        trades = self._load_trades(strategy_id)

        if not trades:
            return f"策略 {strategy_id} 暂无交易记录"

        # 只显示最近 N 天
        recent_trades = trades[-20:] if len(trades) > 20 else trades

        lines = [f"策略 {strategy_id} 交易记录 (最近{len(recent_trades)}笔):\n"]
        lines.append(f"{'日期':<12} {'代码':<10} {'操作':<4} {'价格':>8} {'数量':>6} {'金额':>12}")
        lines.append("-" * 60)

        for t in recent_trades:
            lines.append(
                f"{t['date']:<12} {t['symbol']:<10} {t['action']:<4} "
                f"{t['price']:>8.2f} {t['quantity']:>6} {t['amount']:>12.2f}"
            )

        return "\n".join(lines)

    async def _performance(self, strategy_id: str, days: int) -> str:
        """绩效报告"""
        nav = self._load_nav(strategy_id)
        config = self._load_config(strategy_id)

        if len(nav) < 2:
            return f"策略 {strategy_id} 运行时间太短，无法生成绩效报告"

        # 计算绩效指标
        nav_values = [n["nav"] for n in nav[-days:]]
        start_nav = nav_values[0]
        end_nav = nav_values[-1]

        total_return = (end_nav / start_nav - 1) * 100

        # 计算最大回撤
        peak = nav_values[0]
        max_dd = 0
        for v in nav_values:
            if v > peak:
                peak = v
            dd = (peak - v) / peak * 100
            if dd > max_dd:
                max_dd = dd

        initial_capital = config.get('initial_capital', 1_000_000)

        return (
            f"策略 {strategy_id} 绩效报告 (近{days}天):\n"
            f"- 收益率: {total_return:+.2f}%\n"
            f"- 最大回撤: -{max_dd:.2f}%\n"
            f"- 初始资金: {initial_capital:,.0f}元\n"
            f"- 当前资金: {initial_capital * end_nav:,.0f}元"
        )

    async def _close_position(self, strategy_id: str, symbol: str, quantity: int, price: float) -> str:
        """平仓"""
        if not symbol:
            return "Error: 需要提供 symbol 参数"

        positions = self._load_positions(strategy_id)

        # 找到持仓
        pos = None
        for p in positions:
            if p.symbol == symbol:
                pos = p
                break

        if not pos:
            return f"Error: 策略 {strategy_id} 中没有 {symbol} 的持仓"

        # 平仓数量
        close_qty = quantity if quantity > 0 else pos.quantity

        # 记录交易
        trades = self._load_trades(strategy_id)
        trades.append({
            "date": date.today().strftime("%Y-%m-%d"),
            "symbol": symbol,
            "name": pos.name,
            "action": "sell",
            "price": price,
            "quantity": close_qty,
            "amount": price * close_qty
        })
        self._save_trades(strategy_id, trades)

        # 更新持仓
        if close_qty >= pos.quantity:
            positions = [p for p in positions if p.symbol != symbol]
        else:
            pos.quantity -= close_qty

        self._save_positions(strategy_id, positions)

        return (
            f"✅ 平仓成功\n"
            f"- 股票: {symbol} ({pos.name})\n"
            f"- 数量: {close_qty}\n"
            f"- 价格: {price:.2f}\n"
            f"- 金额: {price * close_qty:.2f}元"
        )
