"""资金流向 Tool - 主力资金、龙虎榜、大单监控"""
import asyncio
import pandas as pd
from typing import Optional
from datetime import datetime, timedelta

from nanobot.agent.tools.base import Tool


class QuantFundTool(Tool):
    """
    资金流向工具
    提供主力资金流向、大单监控、龙虎榜、机构买卖等资金相关数据
    """

    name = "quant_fund"
    description = (
        "资金流向分析工具，提供主力资金流向、大单监控、龙虎榜机构买卖、板块资金流向等。"
        "获取数据后，必须主动为用户提供更多解读："
        "1) 分析资金流向背后的逻辑（为什么资金买入/卖出）"
        "2) 解读龙虎榜机构的操作意图（抢筹还是出货）"
        "3) 结合板块轮动分析资金偏好"
        "4) 搜索相关个股/板块的最新消息和研报"
        "5) 判断市场情绪和短期走势倾向"
    )

    parameters = {
        "type": "object",
        "properties": {
            "data_type": {
                "type": "string",
                "enum": [
                    "main_flow",       # 主力资金流向
                    "sector_flow",     # 板块资金流向
                    "stock_flow",      # 个股资金流向
                    "lhb",             # 每日龙虎榜
                    "lhb_detail",      # 龙虎榜详情
                    "large_order",     # 大单监控
                    "north_flow",      # 北向资金
                ],
                "description": "数据类型"
            },
            "symbol": {"type": "string", "description": "股票代码，如 000001.SZ"},
            "days": {"type": "integer", "description": "查询天数，默认 5"},
            "top_n": {"type": "integer", "description": "返回数量，默认 10"},
        },
        "required": ["data_type"],
    }

    async def execute(
        self,
        data_type: str,
        symbol: Optional[str] = None,
        days: int = 5,
        top_n: int = 10,
        **kwargs
    ) -> str:
        """执行资金流向查询"""
        try:
            if data_type == "main_flow":
                return await self._main_flow(days)
            elif data_type == "sector_flow":
                return await self._sector_flow(days, top_n)
            elif data_type == "stock_flow":
                return await self._stock_flow(symbol, days)
            elif data_type == "lhb":
                return await self._lhb(days)
            elif data_type == "lhb_detail":
                return await self._lhb_detail(symbol)
            elif data_type == "large_order":
                return await self._large_order(top_n)
            elif data_type == "north_flow":
                return await self._north_flow(days)
            else:
                return f"Error: 未知数据类型 {data_type}"
        except Exception as e:
            return f"Error: 查询失败 - {str(e)}"

    async def _main_flow(self, days: int) -> str:
        """市场主力资金流向"""
        try:
            import akshare as ak

            def fetch_flow():
                return ak.stock_market_fund_flow()

            df = await asyncio.wait_for(asyncio.to_thread(fetch_flow), timeout=30.0)

            if df is None or df.empty:
                return "获取主力资金数据失败"

            results = []
            results.append("=" * 60)
            results.append("📊 市场主力资金流向")
            results.append("=" * 60)

            # 获取最新数据
            for idx, row in df.head(days).iterrows():
                date = row.get('日期', 'N/A')
                main = row.get('主力净流入', 'N/A')
                small = row.get('小单净流入', 'N/A')
                medium = row.get('中单净流入', 'N/A')
                large = row.get('大单净流入', 'N/A')

                results.append(f"{date}:")
                results.append(f"  主力: {main}亿")
                results.append(f"  大单: {large}亿")

            return "\n".join(results)

        except Exception as e:
            return f"Error: 获取主力资金流向失败 - {str(e)}"

    async def _sector_flow(self, days: int, top_n: int) -> str:
        """板块资金流向"""
        try:
            import akshare as ak

            def fetch_sector():
                return ak.stock_sector_fund_flow_rank(indicator="今日", sector_type="行业资金流")

            df = await asyncio.wait_for(asyncio.to_thread(fetch_sector), timeout=30.0)

            if df is None or df.empty:
                return "获取板块资金流向失败"

            df = df.sort_values('涨跌幅', ascending=False).head(top_n)

            results = []
            results.append("=" * 60)
            results.append(f"📊 板块资金流向 (涨跌幅 TOP{top_n})")
            results.append("=" * 60)

            for _, row in df.iterrows():
                name = row.get('名称', 'N/A')
                change = row.get('涨跌幅', 'N/A')
                main_flow = row.get('主力净流入', 0)

                if isinstance(main_flow, (int, float)):
                    flow_str = f"{main_flow:.2f}亿"
                else:
                    flow_str = str(main_flow)

                results.append(f"{name}: {change}% (主力净流入 {flow_str})")

            return "\n".join(results)

        except Exception as e:
            return f"Error: 获取板块资金流向失败 - {str(e)}"

    async def _stock_flow(self, symbol: Optional[str], days: int) -> str:
        """个股资金流向"""
        try:
            import akshare as ak

            if not symbol:
                return "请提供股票代码"

            code = symbol.replace(".SZ", "").replace(".SH", "")

            def fetch_stock_flow():
                return ak.stock_individual_fund_flow(stock=code, market="sh" if ".SH" in symbol else "sz")

            df = await asyncio.wait_for(asyncio.to_thread(fetch_stock_flow), timeout=30.0)

            if df is None or df.empty:
                return f"获取 {symbol} 资金流向失败"

            results = []
            results.append("=" * 60)
            results.append(f"📊 {symbol} 资金流向")
            results.append("=" * 60)

            for _, row in df.head(days).iterrows():
                date = row.get('日期', 'N/A')
                net = row.get('净流入', 'N/A')

                results.append(f"{date}: {net}")

            return "\n".join(results)

        except Exception as e:
            return f"Error: 获取个股资金流向失败 - {str(e)}"

    async def _lhb(self, days: int) -> str:
        """每日龙虎榜"""
        try:
            import akshare as ak

            def fetch_lhb():
                return ak.stock_lhb_detail_em(start_date=(datetime.now() - timedelta(days=days)).strftime("%Y%m%d"))

            df = await asyncio.wait_for(asyncio.to_thread(fetch_lhb), timeout=30.0)

            if df is None or df.empty:
                return f"近{days}天无龙虎榜数据"

            results = []
            results.append("=" * 60)
            results.append(f"📊 每日龙虎榜 (近{days}天)")
            results.append("=" * 60)

            # 按股票汇总
            stocks = {}
            for _, row in df.iterrows():
                code = row.get('代码', '')
                name = row.get('名称', '')
                if name not in stocks:
                    stocks[name] = {'code': code, 'reason': row.get('上榜原因', '')}

            for name, info in list(stocks.items())[:15]:
                results.append(f"{name} ({info['code']}): {info['reason']}")

            return "\n".join(results)

        except Exception as e:
            return f"Error: 获取龙虎榜失败 - {str(e)}"

    async def _lhb_detail(self, symbol: Optional[str]) -> str:
        """龙虎榜详情"""
        try:
            import akshare as ak

            if not symbol:
                return "请提供股票代码"

            code = symbol.replace(".SZ", "").replace(".SH", "")

            # 获取当日龙虎榜
            def fetch_lhb():
                return ak.stock_lhb_detail_em(start_date=datetime.now().strftime("%Y%m%d"))

            df = await asyncio.wait_for(asyncio.to_thread(fetch_lhb), timeout=30.0)

            if df is None or df.empty:
                return f"{symbol} 今日未上榜"

            # 查找该股票
            stock = df[df['代码'] == code]

            if stock.empty:
                return f"{symbol} 今日未上榜"

            stock = stock.iloc[0]

            results = []
            results.append("=" * 60)
            results.append(f"📊 {symbol} 龙虎榜详情")
            results.append("=" * 60)
            results.append(f"上榜原因: {stock.get('上榜原因', 'N/A')}")
            results.append(f"买入营业部: {stock.get('买入营业部', 'N/A')}")
            results.append(f"买入金额: {stock.get('买入金额', 'N/A')}")
            results.append(f"卖出营业部: {stock.get('卖出营业部', 'N/A')}")
            results.append(f"卖出金额: {stock.get('卖出金额', 'N/A')}")

            return "\n".join(results)

        except Exception as e:
            return f"Error: 获取龙虎榜详情失败 - {str(e)}"

    async def _large_order(self, top_n: int) -> str:
        """大单监控"""
        try:
            import akshare as ak

            def fetch_activity():
                return ak.stock_market_activity()

            df = await asyncio.wait_for(asyncio.to_thread(fetch_activity), timeout=30.0)

            if df is None or df.empty:
                return "获取大单数据失败"

            results = []
            results.append("=" * 60)
            results.append(f"📊 市场大单监控")
            results.append("=" * 60)

            # 尝试获取大单买入/卖出
            for _, row in df.head(top_n).iterrows():
                name = row.get('名称', 'N/A')
                code = row.get('代码', 'N/A')
                change = row.get('涨跌幅', 'N/A')

                results.append(f"{name} ({code}): {change}%")

            return "\n".join(results)

        except Exception as e:
            return f"Error: 获取大单监控失败 - {str(e)}"

    async def _north_flow(self, days: int) -> str:
        """北向资金流向"""
        try:
            import akshare as ak

            def fetch_north():
                return ak.stock_hsgt_fund_flow_summary_em()

            df = await asyncio.wait_for(asyncio.to_thread(fetch_north), timeout=30.0)

            if df is None or df.empty:
                return "获取北向资金数据失败"

            df = df.head(days)

            results = []
            results.append("=" * 60)
            results.append(f"📊 北向资金流向 (近{days}天)")
            results.append("=" * 60)

            for _, row in df.iterrows():
                date = row.get('日期', 'N/A')
                sh = row.get('沪股通', 'N/A')
                sz = row.get('深股通', 'N/A')
                total = row.get('合计', 'N/A')

                results.append(f"{date}:")
                results.append(f"  沪股通: {sh}亿 | 深股通: {sz}亿")
                results.append(f"  合计: {total}亿")

            return "\n".join(results)

        except Exception as e:
            return f"Error: 获取北向资金流向失败 - {str(e)}"
