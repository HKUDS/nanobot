"""ETF/REITs Tool - ETF行情、溢价率、LOF套利"""
import asyncio
import pandas as pd
from typing import Optional
from datetime import datetime, timedelta

from nanobot.agent.tools.base import Tool


class QuantEtfTool(Tool):
    """
    ETF/REITs 工具
    提供ETF实时行情、溢价率监控、LOF套利机会、REITs行情等功能
    """

    name = "quant_etf"
    description = (
        "ETF/REITs投资工具，提供ETF实时行情、溢价率监控、LOF套利机会、REITs行情查询。"
        "获取数据后，必须主动为用户提供更多分析："
        "1) 分析ETF的热度变化（资金流入/流出）"
        "2) 解读溢价率背后的原因（是否有套利机会）"
        "3) 对比ETF与对应指数的跟踪误差"
        "4) 结合行业趋势判断ETF的投资价值"
        "5) 搜索相关板块/行业的最新消息和研报"
    )

    parameters = {
        "type": "object",
        "properties": {
            "data_type": {
                "type": "string",
                "enum": [
                    "etf_spot",        # ETF实时行情
                    "etf_hot",         # ETF热度排行
                    "etf_change",      # ETF涨跌幅排行
                    "lof_spot",        # LOF实时行情
                    "lof_premium",     # LOF溢价率
                    "etf_fund",        # ETF联接基金
                    "reits_spot",      # REITs行情
                    "sector_etf",      # 行业ETF
                ],
                "description": "数据类型"
            },
            "symbol": {"type": "string", "description": "ETF代码，如 510300.SH"},
            "top_n": {"type": "integer", "description": "返回数量，默认10"},
        },
        "required": ["data_type"],
    }

    async def execute(
        self,
        data_type: str,
        symbol: Optional[str] = None,
        top_n: int = 10,
        **kwargs
    ) -> str:
        """执行ETF查询"""
        try:
            if data_type == "etf_spot":
                return await self._etf_spot(symbol)
            elif data_type == "etf_hot":
                return await self._etf_hot(top_n)
            elif data_type == "etf_change":
                return await self._etf_change(top_n)
            elif data_type == "lof_spot":
                return await self._lof_spot(top_n)
            elif data_type == "lof_premium":
                return await self._lof_premium(top_n)
            elif data_type == "etf_fund":
                return await self._etf_fund(symbol)
            elif data_type == "reits_spot":
                return await self._reits_spot(top_n)
            elif data_type == "sector_etf":
                return await self._sector_etf(top_n)
            else:
                return f"Error: 未知数据类型 {data_type}"
        except Exception as e:
            return f"Error: 查询失败 - {str(e)}"

    async def _etf_spot(self, symbol: Optional[str]) -> str:
        """ETF实时行情"""
        try:
            import akshare as ak

            def fetch_etf():
                return ak.fund_etf_spot_em()

            df = await asyncio.wait_for(asyncio.to_thread(fetch_etf), timeout=30.0)

            if df is None or df.empty:
                return "获取ETF数据失败"

            if symbol:
                # 查询特定ETF
                code = symbol.replace(".SH", "").replace(".SZ", "")
                df = df[df['代码'] == code]

                if df.empty:
                    return f"未找到ETF {symbol}"

                row = df.iloc[0]
                return (
                    f"📊 {symbol} ETF实时行情\n"
                    f"───────────────\n"
                    f"当前价: {row.get('最新价', 'N/A')}\n"
                    f"涨跌幅: {row.get('涨跌幅', 'N/A')}%\n"
                    f"涨跌额: {row.get('涨跌额', 'N/A')}\n"
                    f"成交量: {row.get('成交量', 'N/A')}\n"
                    f"成交额: {row.get('成交额', 'N/A')}\n"
                    f"振幅:   {row.get('振幅', 'N/A')}%\n"
                    f"最高:   {row.get('最高', 'N/A')}\n"
                    f"最低:   {row.get('最低', 'N/A')}\n"
                    f"昨收:   {row.get('昨收', 'N/A')}"
                )
            else:
                # 返回全部ETF数量
                return f"当前共有 {len(df)} 只ETF可直接交易"

        except asyncio.TimeoutError:
            return "Error: 获取数据超时"
        except Exception as e:
            return f"Error: 获取ETF行情失败 - {str(e)}"

    async def _etf_hot(self, top_n: int) -> str:
        """ETF热度排行"""
        try:
            import akshare as ak

            def fetch_hot():
                return ak.fund_etf_spot_em()

            df = await asyncio.wait_for(asyncio.to_thread(fetch_hot), timeout=30.0)

            if df is None or df.empty:
                return "获取ETF数据失败"

            # 按成交额排序
            df = df.sort_values('成交额', ascending=False).head(top_n)

            results = []
            results.append("=" * 60)
            results.append(f"🔥 ETF热度排行 (成交额 TOP{top_n})")
            results.append("=" * 60)

            for idx, row in df.iterrows():
                code = row.get('代码', 'N/A')
                name = row.get('名称', 'N/A')
                price = row.get('最新价', 'N/A')
                change = row.get('涨跌幅', 'N/A')
                amount = row.get('成交额', 'N/A')

                results.append(f"{name} ({code})")
                results.append(f"   价格: {price} | 涨跌: {change}% | 成交: {amount}")

            return "\n".join(results)

        except Exception as e:
            return f"Error: 获取ETF热度失败 - {str(e)}"

    async def _etf_change(self, top_n: int) -> str:
        """ETF涨跌幅排行"""
        try:
            import akshare as ak

            def fetch_etf():
                return ak.fund_etf_spot_em()

            df = await asyncio.wait_for(asyncio.to_thread(fetch_etf), timeout=30.0)

            if df is None or df.empty:
                return "获取ETF数据失败"

            # 涨幅前10
            df_up = df.sort_values('涨跌幅', ascending=False).head(top_n)
            # 跌幅前10
            df_down = df.sort_values('涨跌幅', ascending=True).head(top_n)

            results = []
            results.append("=" * 60)
            results.append(f"📈 ETF涨幅排行 TOP{top_n}")
            results.append("=" * 60)

            for _, row in df_up.iterrows():
                code = row.get('代码', 'N/A')
                name = row.get('名称', 'N/A')
                change = row.get('涨跌幅', 'N/A')
                results.append(f"  {name}: {change}%")

            results.append("")
            results.append("=" * 60)
            results.append(f"📉 ETF跌幅排行 TOP{top_n}")
            results.append("=" * 60)

            for _, row in df_down.iterrows():
                code = row.get('代码', 'N/A')
                name = row.get('名称', 'N/A')
                change = row.get('涨跌幅', 'N/A')
                results.append(f"  {name}: {change}%")

            return "\n".join(results)

        except Exception as e:
            return f"Error: 获取ETF排行失败 - {str(e)}"

    async def _lof_spot(self, top_n: int) -> str:
        """LOF实时行情"""
        try:
            import akshare as ak

            def fetch_lof():
                return ak.fund_lof_spot_em()

            df = await asyncio.wait_for(asyncio.to_thread(fetch_lof), timeout=30.0)

            if df is None or df.empty:
                return "获取LOF数据失败"

            # 按成交额排序
            df = df.sort_values('成交额', ascending=False).head(top_n)

            results = []
            results.append("=" * 60)
            results.append(f"📊 LOF基金行情 (成交额 TOP{top_n})")
            results.append("=" * 60)

            for _, row in df.iterrows():
                code = row.get('代码', 'N/A')
                name = row.get('名称', 'N/A')
                price = row.get('最新价', 'N/A')
                change = row.get('涨跌幅', 'N/A')

                results.append(f"{name} ({code})")
                results.append(f"   价格: {price} | 涨跌: {change}%")

            return "\n".join(results)

        except Exception as e:
            return f"Error: 获取LOF行情失败 - {str(e)}"

    async def _lof_premium(self, top_n: int) -> str:
        """LOF溢价率排行"""
        try:
            import akshare as ak

            def fetch_lof():
                return ak.fund_lof_spot_em()

            df = await asyncio.wait_for(asyncio.to_thread(fetch_lof), timeout=30.0)

            if df is None or df.empty:
                return "获取LOF数据失败"

            # 溢价率排行（需要溢价率字段）
            # 尝试多种可能的列名
            premium_col = None
            for col in ['溢价率', 'premium', 'Premium', '溢价']:
                if col in df.columns:
                    premium_col = col
                    break

            if premium_col:
                df_premium = df.sort_values(premium_col, ascending=False).head(top_n)

                results = []
                results.append("=" * 60)
                results.append(f"📈 LOF溢价率排行 TOP{top_n}")
                results.append("=" * 60)

                for _, row in df_premium.iterrows():
                    code = row.get('代码', 'N/A')
                    name = row.get('名称', 'N/A')
                    premium = row.get(premium_col, 'N/A')
                    results.append(f"{name}: {premium}%")
            else:
                results = []
                results.append("=" * 60)
                results.append("📊 LOF基金列表")
                results.append("=" * 60)
                results.append(f"共 {len(df)} 只LOF基金")

            return "\n".join(results)

        except Exception as e:
            return f"Error: 获取LOF溢价率失败 - {str(e)}"

    async def _etf_fund(self, symbol: Optional[str]) -> str:
        """ETF联接基金"""
        try:
            import akshare as ak

            if symbol:
                code = symbol.replace(".SH", "").replace(".SZ", "")
                name = f"ETF {code}"
            else:
                return "请指定ETF代码"

            results = []
            results.append("=" * 60)
            results.append(f"📊 {symbol} ETF联接基金")
            results.append("=" * 60)
            results.append(f"提示: 联接基金是投资ETF的场外基金")
            results.append(f"代码: {symbol}")

            return "\n".join(results)

        except Exception as e:
            return f"Error: 获取ETF联接失败 - {str(e)}"

    async def _reits_spot(self, top_n: int) -> str:
        """REITs行情"""
        try:
            import akshare as ak

            def fetch_reits():
                # 尝试获取REITs数据
                return ak.reITs_spot()

            df = await asyncio.wait_for(asyncio.to_thread(fetch_reits), timeout=30.0)

            if df is None or df.empty:
                # 尝试其他方式
                return "REITs数据暂时无法获取，可关注A股REITs板块"

            df = df.head(top_n)

            results = []
            results.append("=" * 60)
            results.append(f"📊 REITs行情 (前{top_n})")
            results.append("=" * 60)

            for _, row in df.iterrows():
                code = row.get('代码', 'N/A')
                name = row.get('名称', 'N/A')
                price = row.get('最新价', 'N/A')
                change = row.get('涨跌幅', 'N/A')

                results.append(f"{name} ({code})")
                results.append(f"   价格: {price} | 涨跌: {change}%")

            return "\n".join(results)

        except Exception as e:
            # REITs数据可能不是所有API都能获取
            return "当前暂无REITs行情数据，REITs投资请关注相关基金公告"

    async def _sector_etf(self, top_n: int) -> str:
        """行业ETF"""
        try:
            import akshare as ak

            def fetch_etf():
                return ak.fund_etf_spot_em()

            df = await asyncio.wait_for(asyncio.to_thread(fetch_etf), timeout=30.0)

            if df is None or df.empty:
                return "获取ETF数据失败"

            # 常见行业ETF关键词
            sectors = ['证券', '银行', '医药', '消费', '科技', '新能源', '军工', '芯片', '光伏', '互联网']

            results = []
            results.append("=" * 60)
            results.append("📊 主要行业ETF")
            results.append("=" * 60)

            for sector in sectors:
                sector_etfs = df[df['名称'].str.contains(sector, na=False)]
                if not sector_etfs.empty:
                    # 取该行业成交额最大的
                    best = sector_etfs.sort_values('成交额', ascending=False).iloc[0]
                    name = best.get('名称', 'N/A')
                    code = best.get('代码', 'N/A')
                    change = best.get('涨跌幅', 'N/A')
                    results.append(f"{sector}: {name} ({code}) {change}%")

            return "\n".join(results)

        except Exception as e:
            return f"Error: 获取行业ETF失败 - {str(e)}"
