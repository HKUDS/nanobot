-- QuantBot SQLite 数据库表结构
-- 文件: scripts/create_tables.sql

-- 表一：个股每日行情
CREATE TABLE IF NOT EXISTS daily_quotes (
    date TEXT NOT NULL,
    symbol TEXT NOT NULL,
    name TEXT,
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    volume REAL,
    amount REAL,
    pct_chg REAL,
    turnover REAL,
    PRIMARY KEY (date, symbol)
);

-- 表二：指数行情
CREATE TABLE IF NOT EXISTS index_quotes (
    date TEXT NOT NULL,
    symbol TEXT NOT NULL,
    name TEXT,
    close REAL,
    pct_chg REAL,
    volume REAL,
    amount REAL,
    PRIMARY KEY (date, symbol)
);

-- 表三：北向资金（陆股通净流入）
CREATE TABLE IF NOT EXISTS north_fund_flow (
    date TEXT PRIMARY KEY,
    sh_net_buy REAL,
    sz_net_buy REAL,
    total_net_buy REAL,
    sh_buy REAL,
    sh_sell REAL,
    sz_buy REAL,
    sz_sell REAL
);

-- 表四：融资融券
CREATE TABLE IF NOT EXISTS margin_trading (
    date TEXT PRIMARY KEY,
    rz_balance REAL,
    rq_balance REAL,
    rz_buy REAL,
    rq_sell REAL
);

-- 表五：行业板块日行情
CREATE TABLE IF NOT EXISTS industry_quotes (
    date TEXT NOT NULL,
    industry TEXT NOT NULL,
    pct_chg REAL,
    net_inflow REAL,
    PRIMARY KEY (date, industry)
);

-- 表六：数据更新日志
CREATE TABLE IF NOT EXISTS update_log (
    date TEXT NOT NULL,
    table_name TEXT NOT NULL,
    rows_upserted INTEGER,
    duration_sec REAL,
    status TEXT,
    error_msg TEXT,
    updated_at TEXT,
    PRIMARY KEY (date, table_name)
);
