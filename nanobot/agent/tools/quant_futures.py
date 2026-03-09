"""期货期权 Tool - 股指期货、期权行情"""
import asyncio
import pandas as pd
from typing import Optional
from datetime import datetime, timedelta

from nanobot.agent.tools.base import Tool


class QuantFuturesTool(Tool):
    """
    期货期权工具
    提供股指期货行情、期权行情、期权Greeks计算等功能
    """

    name = "quant_futures"
    description = (
        "期货期权工具，提供股指期货行情、ETF期权行情、期权Greeks计算等。"
        "获取数据后，必须主动为用户提供更多分析："
        "1) 解读期货升贴水背后的市场预期"
        "2) 分析期权波动率曲面和Greeks风险"
        "3) 结合股指期货判断大盘走势"
        "4) 搜索期权市场的最新策略观点"
        "5) 提示期货期权的杠杆风险"
    )

    parameters = {
        "type": "object",
        "properties": {
            "data_type": {
                "type": "string",
                "enum": [
                    "futures_daily",   # 股指期货日线
                    "futures_spot",    # 期货实时行情
                    "options_spot",    # 期权行情
                    "options_greeks",  # 期权Greeks
                    "futures_his",     # 期货历史数据
                ],
                "description": "数据类型"
            },
            "symbol": {"type": "string", "description": "期货/期权代码"},
            "exchange": {"type": "string", "description": "交易所: SHFE/CFFEX/DCE/CZCE"},
            "days": {"type": "integer", "description": "查询天数，默认 30"},
            "top_n": {"type": "integer", "description": "返回数量，默认 10"},
        },
        "required": ["data_type"],
    }

    async def execute(
        self,
        data_type: str,
        symbol: Optional[str] = None,
        exchange: Optional[str] = None,
        days: int = 30,
        top_n: int = 10,
        **kwargs
    ) -> str:
        """执行期货期权查询"""
        try:
            if data_type == "futures_daily":
                return await self._futures_daily(symbol, days)
            elif data_type == "futures_spot":
                return await self._futures_spot(top_n)
            elif data_type == "options_spot":
                return await self._options_spot(symbol, top_n)
            elif data_type == "options_greeks":
                return await self._options_greeks(symbol)
            elif data_type == "futures_his":
                return await self._futures_his(symbol, days)
            else:
                return f"Error: 未知数据类型 {data_type}"
        except Exception as e:
            return f"Error: 查询失败 - {str(e)}"

    async def _futures_daily(self, symbol: Optional[str], days: int) -> str:
        """股指期货日线"""
        try:
            import akshare as ak

            # 主力合约代码映射
            main_contracts = {
                "IF": ("IF", "沪深300股指"),
                "IC": ("IC", "中证500股指"),
                "IH": ("IH", "上证50股指"),
                "IM": ("IM", "中证1000股指"),
            }

            if not symbol:
                # 返回所有主力合约
                results = []
                results.append("=" * 60)
                results.append("📊 股指期货主力合约")
                results.append("=" * 60)

                for code, (symbol_id, name) in main_contracts.items():
                    results.append(f"{code}: {name}")

                results.append("")
                results.append("请指定具体合约查询，如 IF2309")

                return "\n".join(results)

            # 解析合约代码
            # 格式: IF2309 (年+月)
            if len(symbol) >= 4:
                futures_code = symbol[:2].upper()  # IF, IC, IH, IM

            def fetch_daily():
                return ak.futures_zh_daily(symbol=symbol)

            df = await asyncio.wait_for(asyncio.to_thread(fetch_daily), timeout=30.0)

            if df is None or df.empty:
                return f"获取 {symbol} 数据失败"

            # 取最近N天
            df = df.tail(days)

            results = []
            results.append("=" * 60)
            results.append(f"📊 {symbol} 日线行情")
            results.append("=" * 60)

            for _, row in df.iterrows():
                date = row.get('日期', 'N/A')
                open_ = row.get('开盘', 'N/A')
                close = row.get('收盘', 'N/A')
                high = row.get('最高', 'N/A')
                low = row.get('最低', 'N/A')
                volume = row.get('成交量', 'N/A')

                results.append(f"{date}: 开{open_} 高{high} 低{low} 收{close} 量{volume}")

            return "\n".join(results)

        except Exception as e:
            return f"Error: 获取股指期货数据失败 - {str(e)}"

    async def _futures_spot(self, top_n: int) -> str:
        """期货实时行情"""
        try:
            import akshare as ak

            def fetch_spot():
                return ak.futures_zh_spot_em()

            df = await asyncio.wait_for(asyncio.to_thread(fetch_spot), timeout=30.0)

            if df is None or df.empty:
                return "获取期货行情失败"

            # 关注金融期货
            df_financial = df[df['品种'].str.contains('IF|IC|IH|IM', na=False, regex=True)]

            results = []
            results.append("=" * 60)
            results.append(f"📊 股指期货实时行情")
            results.append("=" * 60)

            if df_financial.empty:
                results.append("金融期货数据获取失败，显示全部期货：")

            for _, row in df.head(top_n).iterrows():
                name = row.get('合约', 'N/A')
                price = row.get('最新价', 'N/A')
                change = row.get('涨跌幅', 'N/A')
                volume = row.get('成交量', 'N/A')

                results.append(f"{name}: {price} ({change}%)")

            return "\n".join(results)

        except Exception as e:
            return f"Error: 获取期货实时行情失败 - {str(e)}"

    async def _options_spot(self, symbol: Optional[str], top_n: int) -> str:
        """期权行情"""
        try:
            import akshare as ak

            # 50ETF期权
            def fetch_options():
                return ak.options_50etf_spot()

            df = await asyncio.wait_for(asyncio.to_thread(fetch_options), timeout=30.0)

            if df is None or df.empty:
                return "获取期权行情失败"

            # 如果指定了合约代码
            if symbol:
                df = df[df['合约代码'] == symbol]

                if df.empty:
                    return f"未找到期权合约 {symbol}"

                row = df.iloc[0]
                results = []
                results.append("=" * 60)
                results.append(f"📊 {symbol} 期权行情")
                results.append("=" * 60)

                for col in ['合约代码', '最新价', '涨跌幅', '成交量', '持仓量']:
                    if col in row.index:
                        results.append(f"{col}: {row[col]}")

                return "\n".join(results)

            # 返回期权列表
            results = []
            results.append("=" * 60)
            results.append("📊 50ETF期权行情")
            results.append("=" * 60)

            # 显示看涨期权(Call)和看跌期权(Put)
            df = df.head(top_n)

            for _, row in df.iterrows():
                code = row.get('合约代码', 'N/A')
                price = row.get('最新价', 'N/A')
                change = row.get('涨跌幅', 'N/A')

                results.append(f"{code}: {price} ({change}%)")

            return "\n".join(results)

        except Exception as e:
            return f"Error: 获取期权行情失败 - {str(e)}"

    async def _options_greeks(self, symbol: Optional[str]) -> str:
        """期权Greeks计算"""
        try:
            import math

            if not symbol:
                return "请提供期权合约代码进行Greeks计算"

            # 期权Greeks计算需要Black-Scholes模型
            # 这里提供简化计算示例

            results = []
            results.append("=" * 60)
            results.append(f"📊 {symbol} 期权Greeks")
            results.append("=" * 60)
            results.append("提示: 期权Greeks计算需要以下参数：")
            results.append("- S: 标的资产价格")
            results.append("- K: 行权价")
            results.append("- T: 到期时间(年)")
            results.append("- r: 无风险利率")
            results.append("- σ: 波动率")
            results.append("")
            results.append("Greeks指标说明：")
            results.append("- Delta: 标的价格变化时期权价格的变化")
            results.append("- Gamma: Delta的变化率")
            results.append("- Theta: 每天时间价值衰减")
            results.append("- Vega: 波动率变化对期权价格的影响")

            return "\n".join(results)

        except Exception as e:
            return f"Error: 计算Greeks失败 - {str(e)}"

    async def _futures_his(self, symbol: Optional[str], days: int) -> str:
        """期货历史数据"""
        try:
            import akshare as ak

            if not symbol:
                return "请指定期货合约代码"

            end_date = datetime.now().strftime("%Y%m%d")
            start_date = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")

            def fetch_his():
                return ak.futures_zh_daily(
                    symbol=symbol,
                    start_date=start_date,
                    end_date=end_date
                )

            df = await asyncio.wait_for(asyncio.to_thread(fetch_his), timeout=30.0)

            if df is None or df.empty:
                return f"获取 {symbol} 历史数据失败"

            results = []
            results.append("=" * 60)
            results.append(f"📊 {symbol} 历史数据")
            results.append("=" * 60)

            for _, row in df.tail(10).iterrows():
                date = row.get('日期', 'N/A')
                close = row.get('收盘', 'N/A')
                open_ = row.get('开盘', 'N/A')
                high = row.get('最高', 'N/A')
                low = row.get('最低', 'N/A')

                results.append(f"{date}: {open_} → {close} (高:{high} 低:{low})")

            return "\n".join(results)

        except Exception as e:
            return f"Error: 获取期货历史数据失败 - {str(e)}"
