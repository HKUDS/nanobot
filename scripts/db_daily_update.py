#!/usr/bin/env python3
"""
每日 20:00 数据入库脚本
从 AkShare 拉取当日数据并写入本地 SQLite 数据库
Cron: 0 20 * * 1-5 cd /path/to/QuantBot && python3 scripts/db_daily_update.py
"""
import os
import sys
import logging
from datetime import date
from pathlib import Path

# 配置路径 - 项目目录内的 config/data/
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
DB_PATH = PROJECT_ROOT / "config" / "data" / "market_data.db"
TODAY = date.today().strftime("%Y-%m-%d")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("db_update")


def get_connection():
    """获取数据库连接"""
    import sqlite3
    os.makedirs(DB_PATH.parent, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn):
    """初始化数据库表结构"""
    sql_file = Path(__file__).parent / "create_tables.sql"
    if sql_file.exists():
        with open(sql_file) as f:
            conn.executescript(f.read())
        conn.commit()
        logger.info("数据库表结构初始化完成")


def update_daily_quotes(conn):
    """更新全市场个股日行情"""
    import akshare as ak
    try:
        df = ak.stock_zh_a_hist(symbol="all", period="daily",
                                start_date=TODAY, end_date=TODAY)
        if df.empty:
            logger.warning(f"今日 {TODAY} 无行情数据")
            return 0

        df["date"] = TODAY
        df.to_sql("daily_quotes", conn, if_exists="append", index=False)
        logger.info(f"更新个股行情 {len(df)} 条")
        return len(df)
    except Exception as e:
        logger.error(f"更新个股行情失败: {e}")
        return 0


def update_index_quotes(conn):
    """更新主要指数日行情"""
    import akshare as ak
    indices = {
        "000300": "沪深300",
        "000905": "中证500",
        "000001": "上证指数",
        "399001": "深证成指",
    }
    rows = 0
    for code, name in indices.items():
        try:
            symbol = f"sh{code}" if code.startswith("0") else f"sz{code}"
            df = ak.stock_zh_index_daily(symbol=symbol)
            df = df[df["date"] == TODAY]
            if not df.empty:
                df["symbol"] = f"{code}.{'SH' if code.startswith('0') else 'SZ'}"
                df["name"] = name
                df.to_sql("index_quotes", conn, if_exists="append", index=False)
                rows += len(df)
        except Exception as e:
            logger.warning(f"更新指数 {code} 失败: {e}")
    logger.info(f"更新指数行情 {rows} 条")
    return rows


def update_north_fund(conn):
    """更新北向资金数据"""
    import akshare as ak
    try:
        df = ak.stock_hsgt_fund_flow_summary_em()
        df = df[df["日期"] == TODAY]
        if df.empty:
            logger.warning("北向资金数据今日暂未发布")
            return 0
        df.to_sql("north_fund_flow", conn, if_exists="append", index=False)
        logger.info(f"更新北向资金 {len(df)} 条")
        return len(df)
    except Exception as e:
        logger.error(f"更新北向资金失败: {e}")
        return 0


def update_margin(conn):
    """更新融资融券数据"""
    import akshare as ak
    try:
        df = ak.stock_margin_sse_szse()
        df = df[df["date"] == TODAY]
        if df.empty:
            logger.warning("融资融券数据今日暂未发布")
            return 0
        df.to_sql("margin_trading", conn, if_exists="append", index=False)
        logger.info(f"更新融资融券 {len(df)} 条")
        return len(df)
    except Exception as e:
        logger.error(f"更新融资融券失败: {e}")
        return 0


def update_industry(conn):
    """更新申万一级行业涨跌幅"""
    import akshare as ak
    try:
        df = ak.stock_board_industry_summary_ths()
        df["date"] = TODAY
        df.to_sql("industry_quotes", conn, if_exists="append", index=False)
        logger.info(f"更新行业板块 {len(df)} 条")
        return len(df)
    except Exception as e:
        logger.error(f"更新行业板块失败: {e}")
        return 0


def log_update(conn, table: str, rows: int, status: str, error: str = None):
    """记录更新日志"""
    from datetime import datetime
    conn.execute(
        """INSERT OR REPLACE INTO update_log
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (TODAY, table, rows, 0.0, status, error, datetime.now().isoformat())
    )


def main():
    """主函数"""
    logger.info(f"开始更新 {TODAY} 数据")

    conn = get_connection()
    init_db(conn)

    tasks = [
        ("daily_quotes", update_daily_quotes),
        ("index_quotes", update_index_quotes),
        ("north_fund_flow", update_north_fund),
        ("margin_trading", update_margin),
        ("industry_quotes", update_industry),
    ]

    total_rows = 0
    for table_name, func in tasks:
        try:
            rows = func(conn)
            log_update(conn, table_name, rows, "success")
            total_rows += rows
        except Exception as e:
            log_update(conn, table_name, 0, "failed", str(e))
            logger.error(f"{table_name} 更新失败: {e}")

    conn.commit()
    conn.close()
    logger.info(f"数据更新完成，共 {total_rows} 条记录")


if __name__ == "__main__":
    main()
