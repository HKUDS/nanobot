"""AkShare 量化数据获取 Tool"""
import akshare as ak
from typing import Optional
from datetime import datetime, timedelta

from nanobot.agent.tools.base import Tool


class QuantDataTool(Tool):
    """
    AkShare 量化数据获取工具
    提供行情、资金流向、融资融券、行业板块等数据获取
    """

    name = "quant_data"
    description = (
        "获取 A 股市场数据，包括个股行情、北向资金、融资融券、行业板块等。"
        "用于实时数据查询，回测数据建议使用本地数据库。"
    )

    parameters = {
        "type": "object",
        "properties": {
            "data_type": {
                "type": "string",
                "enum": [
                    "stock_realtime",      # 个股实时行情
                    "index_realtime",      # 指数实时行情
                    "north_fund",          # 北向资金流向
                    "margin",              # 融资融券
                    "industry",            # 行业板块
                    "sector_flow",         # 板块资金流向
                    "stock_info",          # 股票基本信息
                ],
                "description": "数据类型"
            },
            "symbol": {"type": "string", "description": "股票代码，如 000001.SZ"},
            "days": {"type": "integer", "description": "查询天数，默认 5"},
            "date": {"type": "string", "description": "指定日期 YYYY-MM-DD"},
        },
        "required": ["data_type"],
    }

    async def execute(
        self,
        data_type: str,
        symbol: Optional[str] = None,
        days: int = 5,
        date: Optional[str] = None,
        **kwargs
    ) -> str:
        """执行数据获取"""
        try:
            if data_type == "stock_realtime":
                return await self._stock_realtime(symbol)
            elif data_type == "index_realtime":
                return await self._index_realtime(symbol)
            elif data_type == "north_fund":
                return await self._north_fund(days)
            elif data_type == "margin":
                return await self._margin()
            elif data_type == "industry":
                return await self._industry()
            elif data_type == "sector_flow":
                return await self._sector_flow(days)
            elif data_type == "stock_info":
                return await self._stock_info(symbol)
            else:
                return f"Error: 未知数据类型 {data_type}"
        except Exception as e:
            return f"Error: 获取数据失败 - {str(e)}"

    async def _stock_realtime(self, symbol: str) -> str:
        """个股实时行情"""
        if not symbol:
            return "Error: 查询个股行情需要提供 symbol 参数"

        try:
            df = ak.stock_zh_a_spot_em()
            code = symbol.replace(".SZ", "").replace(".SH", "")
            df = df[df["代码"] == code]

            if df.empty:
                return f"未找到股票 {symbol} 的行情数据"

            row = df.iloc[0]
            return (
                f"{symbol} 实时行情:\n"
                f"- 当前价: {row.get('最新价', 'N/A')}\n"
                f"- 涨跌幅: {row.get('涨跌幅', 'N/A')}%\n"
                f"- 涨跌额: {row.get('涨跌额', 'N/A')}\n"
                f"- 成交量: {row.get('成交量', 'N/A')}\n"
                f"- 成交额: {row.get('成交额', 'N/A')}\n"
                f"- 振幅: {row.get('振幅', 'N/A')}%\n"
                f"- 最高: {row.get('最高', 'N/A')}\n"
                f"- 最低: {row.get('最低', 'N/A')}\n"
                f"- 昨收: {row.get('昨收', 'N/A')}"
            )
        except Exception as e:
            return f"Error: 获取行情失败 - {str(e)}"

    async def _index_realtime(self, symbol: str) -> str:
        """指数实时行情"""
        index_map = {
            "000300.SH": ("sh000300", "沪深300"),
            "000905.SH": ("sh000905", "中证500"),
            "000001.SH": ("sh000001", "上证指数"),
            "399001.SZ": ("sz399001", "深证成指"),
        }

        if symbol not in index_map:
            return f"Error: 不支持的指数代码 {symbol}，支持: {list(index_map.keys())}"

        try:
            ak_symbol, name = index_map[symbol]
            df = ak.stock_zh_index_spot_em()
            df = df[df["代码"] == ak_symbol]

            if df.empty:
                return f"未找到指数 {symbol} 的行情数据"

            row = df.iloc[0]
            return (
                f"{name} ({symbol}) 实时行情:\n"
                f"- 当前点位: {row.get('最新价', 'N/A')}\n"
                f"- 涨跌幅: {row.get('涨跌幅', 'N/A')}%\n"
                f"- 涨跌额: {row.get('涨跌额', 'N/A')}\n"
                f"- 成交量: {row.get('成交量', 'N/A')}\n"
                f"- 成交额: {row.get('成交额', 'N/A')}"
            )
        except Exception as e:
            return f"Error: 获取指数行情失败 - {str(e)}"

    async def _north_fund(self, days: int) -> str:
        """北向资金流向"""
        try:
            df = ak.stock_hsgt_fund_flow_summary_em()
            df = df.head(days)

            results = []
            for _, row in df.iterrows():
                results.append(
                    f"{row.get('日期', 'N/A')}: "
                    f"沪股通 {row.get('沪股通', 'N/A')}亿, "
                    f"深股通 {row.get('深股通', 'N/A')}亿, "
                    f"合计 {row.get('合计', 'N/A')}亿"
                )

            return "北向资金流向 (近 {} 天):\n{}".format(
                days, "\n".join(results)
            )
        except Exception as e:
            return f"Error: 获取北向资金数据失败 - {str(e)}"

    async def _margin(self) -> str:
        """融资融券数据"""
        try:
            df = ak.stock_margin_sse_szse()
            row = df.iloc[0]

            # 尝试多个可能的列名
            rz_balance = row.get('rz_balance') or row.get('融资余额') or row.get('rzye')
            rq_balance = row.get('rq_balance') or row.get('融券余额') or row.get('rqye')
            rz_buy = row.get('rz_buy') or row.get('融资买入额') or row.get('rqmre')
            rq_sell = row.get('rq_sell') or row.get('融券卖出额') or row.get('rqchl')

            return (
                "融资融券数据 (最新):\n"
                f"- 融资余额: {rz_balance}亿\n"
                f"- 融券余额: {rq_balance}亿\n"
                f"- 融资买入额: {rz_buy}亿\n"
                f"- 融券卖出额: {rq_sell}亿"
            )
        except Exception as e:
            return f"Error: 获取融资融券数据失败 - {str(e)}"

    async def _industry(self) -> str:
        """行业板块涨跌"""
        try:
            df = ak.stock_board_industry_summary_ths()
            df = df.sort_values("涨跌幅", ascending=False)
            df = df.head(10)

            results = []
            for _, row in df.iterrows():
                net_inflow = row.get('主力净流入', 0)
                results.append(
                    f"{row['名称']}: {row['涨跌幅']:.2f}% "
                    f"(主力净流入 {net_inflow:.2f}亿)"
                )

            return "行业板块涨幅前 10:\n" + "\n".join(results)
        except Exception as e:
            return f"Error: 获取行业板块数据失败 - {str(e)}"

    async def _sector_flow(self, days: int) -> str:
        """板块资金流向"""
        try:
            df = ak.stock_sector_fund_flow_rank(indicator="今日", sector_type="北向资金")
            df = df.head(10)

            results = []
            for _, row in df.iterrows():
                net_inflow = row.get('主力净流入', 0)
                results.append(
                    f"{row['名称']}: {row['涨跌幅']:.2f}% "
                    f"净流入 {net_inflow:.2f}亿"
                )

            return "板块资金流向 (北向资金):\n" + "\n".join(results)
        except Exception as e:
            return f"Error: 获取板块资金流向失败 - {str(e)}"

    async def _stock_info(self, symbol: str) -> str:
        """股票基本信息"""
        if not symbol:
            return "Error: 查询股票信息需要提供 symbol 参数"

        try:
            code = symbol.replace(".SZ", "").replace(".SH", "")
            df = ak.stock_individual_info_em(symbol=code)

            if df.empty:
                return f"未找到股票 {symbol} 的信息"

            info = dict(zip(df["item"], df["value"]))
            return (
                f"{symbol} 基本信息:\n" +
                "\n".join([f"- {k}: {v}" for k, v in info.items()])
            )
        except Exception as e:
            return f"Error: 获取股票信息失败 - {str(e)}"
