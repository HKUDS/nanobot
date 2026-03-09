"""本地数据库读取 Tool - 替代直接调用 AkShare"""
import os
import sqlite3
from pathlib import Path
from typing import Any, Optional

from nanobot.agent.tools.base import Tool


class DatabaseReadTool(Tool):
    """
    从本地 SQLite 数据库读取 A 股历史数据
    LLM 调用此工具替代直接调用 AkShare——更快、无网络依赖
    """

    name = "db_read"
    description = (
        "从本地数据库读取 A 股行情、北向资金、融资融券、行业涨跌等数据。"
        "数据每日 20:00 自动更新，适合查询近期历史数据。"
        "查询实时当日数据仍需调用 AkShare。"
    )

    DB_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "data" / "market_data.db"

    QUERY_TEMPLATES = {
        "stock_history": """
            SELECT date, close, pct_chg, volume, turnover
            FROM daily_quotes
            WHERE symbol = ? AND date >= ?
            ORDER BY date ASC
        """,
        "north_fund": """
            SELECT date, total_net_buy, sh_net_buy, sz_net_buy
            FROM north_fund_flow
            WHERE date >= ?
            ORDER BY date ASC
        """,
        "index_history": """
            SELECT date, close, pct_chg
            FROM index_quotes
            WHERE symbol = ? AND date >= ?
            ORDER BY date ASC
        """,
        "industry_rank": """
            SELECT industry, pct_chg, net_inflow
            FROM industry_quotes
            WHERE date = ?
            ORDER BY pct_chg DESC
        """,
        "latest_date": """
            SELECT MAX(date) as latest FROM daily_quotes
        """,
    }

    parameters = {
        "type": "object",
        "properties": {
            "query_type": {
                "type": "string",
                "enum": ["stock_history", "north_fund", "index_history",
                        "industry_rank", "latest_date"],
                "description": "查询类型"
            },
            "symbol": {"type": "string", "description": "股票代码，如 000001.SZ"},
            "days": {"type": "integer", "description": "查询天数，默认 30"},
            "date": {"type": "string", "description": "指定日期，格式 YYYY-MM-DD"},
        },
        "required": ["query_type"],
    }

    async def execute(
        self,
        query_type: str,
        symbol: Optional[str] = None,
        days: int = 30,
        date: Optional[str] = None,
        **kwargs
    ) -> str:
        """执行数据库查询"""
        from datetime import datetime, timedelta

        if not self.DB_PATH.exists():
            return f"Error: 数据库文件不存在 {self.DB_PATH}，请先运行数据入库脚本"

        conn = sqlite3.connect(str(self.DB_PATH))
        conn.row_factory = sqlite3.Row

        try:
            sql = self.QUERY_TEMPLATES[query_type]
            params = []

            if query_type == "stock_history":
                from datetime import datetime
                start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
                params = [symbol, start_date]
            elif query_type == "north_fund":
                from datetime import datetime
                start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
                params = [start_date]
            elif query_type == "index_history":
                from datetime import datetime
                start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
                params = [symbol, start_date]
            elif query_type == "industry_rank":
                params = [date] if date else [datetime.now().strftime("%Y-%m-%d")]
            elif query_type == "latest_date":
                params = []

            cursor = conn.execute(sql, params)
            rows = cursor.fetchall()

            if not rows:
                return f"查询 {query_type} 无数据"

            # 转换为列表格式
            results = [dict(row) for row in rows]
            return f"查询成功，共 {len(results)} 条记录:\n{results[:10]}"

        except Exception as e:
            return f"Error: 查询失败 - {str(e)}"
        finally:
            conn.close()
