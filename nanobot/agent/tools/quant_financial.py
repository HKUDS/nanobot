"""基本面 Tool - 财报、业绩预告、分红送转"""
import asyncio
import pandas as pd
from typing import Optional
from datetime import datetime, timedelta

from nanobot.agent.tools.base import Tool


class QuantFinancialTool(Tool):
    """
    基本面分析工具
    提供财报关键指标、业绩预告、分红送转、估值指标等基本面数据
    """

    name = "quant_financial"
    description = (
        "基本面分析工具，提供财报关键指标、业绩预告、分红送转、估值指标(PE/PB)等。"
        "获取数据后，必须主动为用户提供更多分析："
        "1) 解读财务数据的意义（增长/下降的原因）"
        "2) 对比行业平均估值，判断当前估值是否合理"
        "3) 分析业绩趋势（持续性、季节性）"
        "4) 搜索该公司的最新研报和分析师观点"
        "5) 提示基本面风险和投资注意事项"
    )

    parameters = {
        "type": "object",
        "properties": {
            "data_type": {
                "type": "string",
                "enum": [
                    "report",          # 财报指标
                    "forecast",        # 业绩预告
                    "dividend",        # 分红送转
                    "valuation",       # 估值指标
                    "basic_info",     # 基本信息
                    "holders",         # 股东人数
                ],
                "description": "数据类型"
            },
            "symbol": {"type": "string", "description": "股票代码，如 000001.SZ"},
            "year": {"type": "integer", "description": "年份，默认当前年"},
            "quarter": {"type": "integer", "description": "季度 1-4"},
        },
        "required": ["data_type"],
    }

    async def execute(
        self,
        data_type: str,
        symbol: Optional[str] = None,
        year: Optional[int] = None,
        quarter: Optional[int] = None,
        **kwargs
    ) -> str:
        """执行基本面查询"""
        try:
            if data_type == "report":
                return await self._report(symbol, year, quarter)
            elif data_type == "forecast":
                return await self._forecast(symbol, year)
            elif data_type == "dividend":
                return await self._dividend(symbol)
            elif data_type == "valuation":
                return await self._valuation(symbol)
            elif data_type == "basic_info":
                return await self._basic_info(symbol)
            elif data_type == "holders":
                return await self._holders(symbol)
            else:
                return f"Error: 未知数据类型 {data_type}"
        except Exception as e:
            return f"Error: 查询失败 - {str(e)}"

    async def _report(self, symbol: Optional[str], year: Optional[int], quarter: Optional[int]) -> str:
        """财报关键指标"""
        try:
            import akshare as ak

            if not symbol:
                return "请提供股票代码"

            code = symbol.replace(".SZ", "").replace(".SH", "")

            if not year:
                year = datetime.now().year

            def fetch_report():
                return ak.stock_financial_abstract_ths(symbol=code)

            df = await asyncio.wait_for(asyncio.to_thread(fetch_report), timeout=30.0)

            if df is None or df.empty:
                return f"获取 {symbol} 财报数据失败"

            results = []
            results.append("=" * 60)
            results.append(f"📊 {symbol} 财报指标")
            results.append("=" * 60)

            # 获取最新财报
            latest = df.iloc[0] if len(df) > 0 else None

            if latest is not None:
                # 尝试获取关键指标
                for col in ['报告期', '每股收益', '营业收入', '净利润', '净资产收益率']:
                    if col in latest.index:
                        results.append(f"{col}: {latest[col]}")

            return "\n".join(results)

        except asyncio.TimeoutError:
            return "Error: 获取数据超时"
        except Exception as e:
            return f"Error: 获取财报数据失败 - {str(e)}"

    async def _forecast(self, symbol: Optional[str], year: Optional[int]) -> str:
        """业绩预告"""
        try:
            import akshare as ak

            if not symbol:
                return "请提供股票代码"

            code = symbol.replace(".SZ", "").replace(".SH", "")

            def fetch_forecast():
                return ak.stock_yjbb(symbol=code)

            df = await asyncio.wait_for(asyncio.to_thread(fetch_forecast), timeout=30.0)

            if df is None or df.empty:
                return f"获取 {symbol} 业绩预告失败"

            results = []
            results.append("=" * 60)
            results.append(f"📊 {symbol} 业绩预告")
            results.append("=" * 60)

            for _, row in df.head(5).iterrows():
                date = row.get('公告日期', 'N/A')
                type_ = row.get('业绩预告类型', 'N/A')
                range_ = row.get('预计净利润同比增幅', 'N/A')

                results.append(f"{date}: {type_} ({range_})")

            return "\n".join(results)

        except Exception as e:
            return f"Error: 获取业绩预告失败 - {str(e)}"

    async def _dividend(self, symbol: Optional[str]) -> str:
        """分红送转"""
        try:
            import akshare as ak

            if not symbol:
                return "请提供股票代码"

            code = symbol.replace(".SZ", "").replace(".SH", "")

            def fetch_dividend():
                return ak.stock_fh_spread(symbol=code)

            df = await asyncio.wait_for(asyncio.to_thread(fetch_dividend), timeout=30.0)

            if df is None or df.empty:
                return f"获取 {symbol} 分红送转数据失败"

            results = []
            results.append("=" * 60)
            results.append(f"📊 {symbol} 分红送转")
            results.append("=" * 60)

            for _, row in df.head(5).iterrows():
                date = row.get('公告日期', 'N/A')
                plan = row.get('分红转增', 'N/A')

                results.append(f"{date}: {plan}")

            return "\n".join(results)

        except Exception as e:
            return f"Error: 获取分红送转失败 - {str(e)}"

    async def _valuation(self, symbol: Optional[str]) -> str:
        """估值指标"""
        try:
            import akshare as ak

            if not symbol:
                return "请提供股票代码"

            code = symbol.replace(".SZ", "").replace(".SH", "")

            def fetch_info():
                return ak.stock_individual_info_em(symbol=code)

            df = await asyncio.wait_for(asyncio.to_thread(fetch_info), timeout=30.0)

            if df is None or df.empty:
                return f"获取 {symbol} 估值数据失败"

            # 转换为字典
            info = dict(zip(df['item'], df['value']))

            results = []
            results.append("=" * 60)
            results.append(f"📊 {symbol} 估值指标")
            results.append("=" * 60)

            # 提取关键估值指标
            key_metrics = ['市盈率', '市净率', '市销率', '总市值', '流通市值']
            for metric in key_metrics:
                if metric in info:
                    results.append(f"{metric}: {info[metric]}")

            return "\n".join(results)

        except Exception as e:
            return f"Error: 获取估值指标失败 - {str(e)}"

    async def _basic_info(self, symbol: Optional[str]) -> str:
        """股票基本信息"""
        try:
            import akshare as ak

            if not symbol:
                return "请提供股票代码"

            code = symbol.replace(".SZ", "").replace(".SH", "")

            def fetch_info():
                return ak.stock_individual_info_em(symbol=code)

            df = await asyncio.wait_for(asyncio.to_thread(fetch_info), timeout=30.0)

            if df is None or df.empty:
                return f"获取 {symbol} 基本信息失败"

            info = dict(zip(df['item'], df['value']))

            results = []
            results.append("=" * 60)
            results.append(f"📊 {symbol} 基本信息")
            results.append("=" * 60)

            # 常用字段
            common = ['股票简称', '总股本', '流通股本', '所属行业', '上市日期']
            for field in common:
                if field in info:
                    results.append(f"{field}: {info[field]}")

            return "\n".join(results)

        except Exception as e:
            return f"Error: 获取基本信息失败 - {str(e)}"

    async def _holders(self, symbol: Optional[str]) -> str:
        """股东人数"""
        try:
            import akshare as ak

            if not symbol:
                return "请提供股票代码"

            code = symbol.replace(".SZ", "").replace(".SH", "")

            # 尝试获取股东人数数据
            results = []
            results.append("=" * 60)
            results.append(f"📊 {symbol} 股东人数")
            results.append("=" * 60)
            results.append("提示: 股东人数数据需通过财报获取")
            results.append(f"代码: {code}")

            return "\n".join(results)

        except Exception as e:
            return f"Error: 获取股东人数失败 - {str(e)}"
