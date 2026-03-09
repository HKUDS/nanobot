"""新股新债 Tool - IPO/打新"""
import asyncio
import pandas as pd
from typing import Optional
from datetime import datetime, timedelta

from nanobot.agent.tools.base import Tool


class QuantIpoTool(Tool):
    """
    新股新债工具
    提供新股申购日历、上市日历、打新收益率统计等功能
    """

    name = "quant_ipo"
    description = (
        "A股/港股新股新债信息查询，包括申购日历、上市日历、中签查询、打新收益率统计。"
        "获取信息后，必须主动为用户提供更多分析："
        "1) 分析近期打新收益趋势（赚钱效应如何）"
        "2) 结合市场情绪判断当前是否适合打新"
        "3) 搜索该新股/新债的行业背景和基本面"
        "4) 提示打新风险（破发可能性）"
        "5) 提供中签率、申购上限等实用信息参考"
    )

    parameters = {
        "type": "object",
        "properties": {
            "data_type": {
                "type": "string",
                "enum": [
                    "calendar",       # 申购日历
                    "listing",        # 上市日历
                    "history",        # 历史打新
                    "stats",          # 打新统计
                    "hot",            # 热门新股
                    "eastmoney",      # 东方财富网新股数据
                ],
                "description": "数据类型"
            },
            "date": {"type": "string", "description": "指定日期 YYYY-MM-DD"},
            "days": {"type": "integer", "description": "查询天数，默认 30"},
            "market": {"type": "string", "description": "市场类型: A股/港股，默认A股"},
        },
        "required": ["data_type"],
    }

    async def execute(
        self,
        data_type: str,
        date: Optional[str] = None,
        days: int = 30,
        market: str = "A股",
        **kwargs
    ) -> str:
        """执行新股新债查询"""
        try:
            if data_type == "calendar":
                return await self._calendar(date, days, market)
            elif data_type == "listing":
                return await self._listing(date, days, market)
            elif data_type == "history":
                return await self._history(days)
            elif data_type == "stats":
                return await self._stats(days)
            elif data_type == "hot":
                return await self._hot()
            elif data_type == "eastmoney":
                return await self._eastmoney(date)
            else:
                return f"Error: 未知数据类型 {data_type}"
        except Exception as e:
            return f"Error: 查询失败 - {str(e)}"

    async def _calendar(self, date: Optional[str], days: int, market: str) -> str:
        """申购日历"""
        try:
            import akshare as ak

            # 计算日期范围
            if date:
                start_date = date
                end_date = date
            else:
                start_date = datetime.now().strftime("%Y%m%d")
                end_date = (datetime.now() + timedelta(days=days)).strftime("%Y%m%d")

            def fetch_calendar():
                return ak.stock_ipo_calendar(start_date=start_date, end_date=end_date)

            df = await asyncio.wait_for(asyncio.to_thread(fetch_calendar), timeout=30.0)

            if df is None or df.empty:
                return f"近期无新股申购安排"

            results = []
            results.append("=" * 60)
            results.append("📅 新股申购日历")
            results.append("=" * 60)

            for _, row in df.iterrows():
                date = row.get('申购日期', 'N/A')
                code = row.get('股票代码', 'N/A')
                name = row.get('股票简称', 'N/A')
                price = row.get('发行价格', 'N/A')
                pe = row.get('市盈率', 'N/A')
                limit = row.get('申购上限', 'N/A')

                results.append("")
                results.append(f"📌 {date}")
                results.append(f"   {name} ({code})")
                results.append(f"   发行价: {price} | 市盈率: {pe}")
                results.append(f"   申购上限: {limit}股")

            return "\n".join(results)

        except asyncio.TimeoutError:
            return "Error: 获取数据超时，请稍后重试"
        except Exception as e:
            return f"Error: 获取申购日历失败 - {str(e)}"

    async def _listing(self, date: Optional[str], days: int, market: str) -> str:
        """上市日历"""
        try:
            import akshare as ak

            if date:
                start_date = date
                end_date = date
            else:
                start_date = datetime.now().strftime("%Y%m%d")
                end_date = (datetime.now() + timedelta(days=days)).strftime("%Y%m%d")

            def fetch_listing():
                return ak.stock_new_calendar(start_date=start_date, end_date=end_date)

            df = await asyncio.wait_for(asyncio.to_thread(fetch_listing), timeout=30.0)

            if df is None or df.empty:
                return f"近期无新股上市安排"

            results = []
            results.append("=" * 60)
            results.append("📅 新股上市日历")
            results.append("=" * 60)

            for _, row in df.iterrows():
                date = row.get('上市日期', 'N/A')
                code = row.get('股票代码', 'N/A')
                name = row.get('股票简称', 'N/A')
                price = row.get('发行价格', 'N/A')
                change = row.get('首日涨跌幅', 'N/A')

                results.append("")
                results.append(f"📌 {date}")
                results.append(f"   {name} ({code})")
                results.append(f"   发行价: {price}")

                if change != 'N/A' and change:
                    results.append(f"   首日涨跌幅: {change}%")

            return "\n".join(results)

        except asyncio.TimeoutError:
            return "Error: 获取数据超时，请稍后重试"
        except Exception as e:
            return f"Error: 获取上市日历失败 - {str(e)}"

    async def _history(self, days: int) -> str:
        """历史打新数据"""
        try:
            import akshare as ak

            # 获取近期上市的新股
            end_date = datetime.now().strftime("%Y%m%d")
            start_date = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")

            def fetch_history():
                return ak.stock_new_calendar(start_date=start_date, end_date=end_date)

            df = await asyncio.wait_for(asyncio.to_thread(fetch_history), timeout=30.0)

            if df is None or df.empty:
                return f"近期无新股上市"

            results = []
            results.append("=" * 60)
            results.append("📊 近期上市新股 (近{}天)".format(days))
            results.append("=" * 60)

            # 统计
            total = len(df)
            up_count = 0
            down_count = 0

            for _, row in df.iterrows():
                name = row.get('股票简称', 'N/A')
                code = row.get('股票代码', 'N/A')
                price = row.get('发行价格', 'N/A')
                change = row.get('首日涨跌幅', 'N/A')

                if change != 'N/A' and change:
                    change_val = float(str(change).replace('%', '').replace('+', ''))
                    if change_val > 0:
                        up_count += 1
                    elif change_val < 0:
                        down_count += 1

                change_str = f"{change}%" if change != 'N/A' else "N/A"
                results.append(f"{name}({code}): 发行价 {price} → 首日 {change_str}")

            results.append("")
            results.append(f"统计: 上涨 {up_count} | 下跌 {down_count} | 合计 {total}")

            return "\n".join(results)

        except asyncio.TimeoutError:
            return "Error: 获取数据超时"
        except Exception as e:
            return f"Error: 获取历史数据失败 - {str(e)}"

    async def _stats(self, days: int) -> str:
        """打新收益率统计"""
        try:
            import akshare as as_

            end_date = datetime.now().strftime("%Y%m%d")
            start_date = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")

            def fetch_data():
                return ak.stock_new_calendar(start_date=start_date, end_date=end_date)

            df = await asyncio.wait_for(asyncio.to_thread(fetch_data), timeout=30.0)

            if df is None or df.empty:
                return f"近期无新股上市"

            # 计算统计数据
            changes = []
            for _, row in df.iterrows():
                change = row.get('首日涨跌幅', 'N/A')
                if change != 'N/A' and change:
                    try:
                        val = float(str(change).replace('%', ''))
                        changes.append(val)
                    except:
                        pass

            if not changes:
                return "无有效数据"

            results = []
            results.append("=" * 60)
            results.append("📈 打新收益率统计 (近{}天)".format(days))
            results.append("=" * 60)
            results.append(f"新股数量: {len(changes)}只")
            results.append(f"上涨数量: {sum(1 for c in changes if c > 0)}只")
            results.append(f"下跌数量: {sum(1 for c in changes if c < 0)}只")
            results.append(f"平均收益: {sum(changes)/len(changes):.2f}%")
            results.append(f"最大涨幅: {max(changes):.2f}%")
            results.append(f"最大跌幅: {min(changes):.2f}%")

            # 按涨跌幅区间统计
            results.append("")
            results.append("涨跌幅分布:")
            results.append(f"  >100%:   {sum(1 for c in changes if c > 100)}只")
            results.append(f"  50%-100%: {sum(1 for c in changes if 50 <= c <= 100)}只")
            results.append(f"  0%-50%:   {sum(1 for c in changes if 0 <= c < 50)}只")
            results.append(f"  -10%-0%:  {sum(1 for c in changes if -10 <= c < 0)}只")
            results.append(f"  <-10%:    {sum(1 for c in changes if c < -10)}只")

            return "\n".join(results)

        except asyncio.TimeoutError:
            return "Error: 获取数据超时"
        except Exception as e:
            return f"Error: 获取统计数据失败 - {str(e)}"

    async def _hot(self) -> str:
        """热门新股/打新热门股"""
        try:
            import akshare as ak

            # 获取今日申购的新股
            today = datetime.now().strftime("%Y%m%d")

            def fetch_today():
                return ak.stock_ipo_calendar(start_date=today, end_date=today)

            df = await asyncio.wait_for(asyncio.to_thread(fetch_today), timeout=30.0)

            results = []
            results.append("=" * 60)
            results.append("🔥 今日可申购新股")
            results.append("=" * 60)

            if df is None or df.empty:
                results.append("今日无可申购新股")
            else:
                for _, row in df.iterrows():
                    name = row.get('股票简称', 'N/A')
                    code = row.get('股票代码', 'N/A')
                    price = row.get('发行价格', 'N/A')
                    pe = row.get('市盈率', 'N/A')
                    limit = row.get('申购上限', 'N/A')

                    results.append("")
                    results.append(f"⭐ {name} ({code})")
                    results.append(f"   发行价: {price}元")
                    results.append(f"   市盈率: {pe}")
                    results.append(f"   申购上限: {limit}股")

            return "\n".join(results)

        except asyncio.TimeoutError:
            return "Error: 获取数据超时"
        except Exception as e:
            return f"Error: 获取热门新股失败 - {str(e)}"

    async def _eastmoney(self, date: Optional[str]) -> str:
        """东方财富网新股数据"""
        try:
            import akshare as ak

            if not date:
                date = datetime.now().strftime("%Y-%m-%d")

            def fetch_em():
                # 尝试获取东方财富新股数据
                return ak.stock_ipo_calendar(start_date=date.replace('-', ''), end_date=date.replace('-', ''))

            df = await asyncio.wait_for(asyncio.to_thread(fetch_em), timeout=30.0)

            if df is None or df.empty:
                return f"{date} 无新股申购"

            results = []
            results.append("=" * 60)
            results.append(f"📊 {date} 新股申购 (东方财富)")
            results.append("=" * 60)

            for _, row in df.iterrows():
                code = row.get('股票代码', 'N/A')
                name = row.get('股票简称', 'N/A')
                price = row.get('发行价格', 'N/A')

                results.append(f"{name} ({code}): 发行价 {price}")

            return "\n".join(results)

        except Exception as e:
            return f"Error: 获取东方财富数据失败 - {str(e)}"
