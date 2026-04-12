import sqlite3
from pathlib import Path
from datetime import datetime

DB_PATH = Path(__file__).parent / "bff.db"

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS wallets (
                conversation_id TEXT PRIMARY KEY,
                balance INTEGER NOT NULL DEFAULT 1000000,
                frozen_balance INTEGER DEFAULT 0,
                updated_at TIMESTAMP
            )
        """)
        # 初始化系统钱包
        conn.execute("INSERT OR IGNORE INTO wallets (conversation_id, balance, updated_at) VALUES ('system', 0, ?)", (datetime.now(),))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS bounties (
                id TEXT PRIMARY KEY,
                issuer_id TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                reward_pool INTEGER NOT NULL,
                docker_reward INTEGER DEFAULT 0,
                deadline TIMESTAMP,
                status TEXT DEFAULT 'open',
                created_at TIMESTAMP,
                winner_ids TEXT,
                FOREIGN KEY (issuer_id) REFERENCES wallets(conversation_id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS submissions (
                id TEXT PRIMARY KEY,
                bounty_id TEXT NOT NULL,
                agent_id TEXT NOT NULL,
                content TEXT NOT NULL,
                skill_code TEXT,
                cost_tokens INTEGER DEFAULT 0,
                evaluation_score REAL,
                score REAL,
                score_reason TEXT,
                created_at TIMESTAMP,
                FOREIGN KEY (bounty_id) REFERENCES bounties(id),
                FOREIGN KEY (agent_id) REFERENCES wallets(conversation_id)
            )
        """)

        conn.execute("CREATE TABLE IF NOT EXISTS submissions_backup (id TEXT PRIMARY KEY)")
        conn.execute("DROP TABLE IF EXISTS submissions_backup")

        try:
            conn.execute("ALTER TABLE submissions ADD COLUMN score REAL")
        except:
            pass
        try:
            conn.execute("ALTER TABLE submissions ADD COLUMN score_reason TEXT")
        except:
            pass

        conn.execute("""
            CREATE TABLE IF NOT EXISTS public_knowledge (
                id TEXT PRIMARY KEY,
                type TEXT CHECK(type IN ('skill', 'doc', 'faq')),
                title TEXT,
                content TEXT,
                skill_code TEXT,
                usage TEXT,
                tags TEXT,
                embedding TEXT,
                author_id TEXT,
                usage_count INTEGER DEFAULT 0,
                token_reward INTEGER DEFAULT 0,
                created_at TIMESTAMP
            )
        """)
        try:
            conn.execute("ALTER TABLE public_knowledge ADD COLUMN usage TEXT")
            print("[DB] 成功添加 usage 字段到 public_knowledge 表")
        except Exception as e:
            if "duplicate column name" in str(e).lower():
                print("[DB] usage 字段已存在，跳过迁移")
            else:
                print(f"[DB] 添加 usage 字段失败: {e}")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS reflexes (
                id TEXT PRIMARY KEY,
                feature_text TEXT,
                embedding TEXT,
                action_sequence TEXT,
                confidence REAL DEFAULT 0.5,
                source_agent_id TEXT,
                usage_count INTEGER DEFAULT 0,
                success_count INTEGER DEFAULT 0,
                created_at TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS friendships (
                agent_a TEXT,
                agent_b TEXT,
                trust_score REAL DEFAULT 0.5,
                created_at TIMESTAMP,
                PRIMARY KEY (agent_a, agent_b)
            )
        """)
        # 创建节点关系表
        conn.execute("""
            CREATE TABLE IF NOT EXISTS node_relations (
                id TEXT PRIMARY KEY,
                source_node_id TEXT,
                target_node_id TEXT,
                weight INTEGER DEFAULT 1,
                created_at TIMESTAMP,
                updated_at TIMESTAMP,
                FOREIGN KEY (source_node_id) REFERENCES wallets(conversation_id),
                FOREIGN KEY (target_node_id) REFERENCES wallets(conversation_id)
            )
        """)
        # 创建通知表
        conn.execute("""
            CREATE TABLE IF NOT EXISTS notifications (
                id TEXT PRIMARY KEY,
                node_id TEXT,
                bounty_id TEXT,
                type TEXT,
                status TEXT,
                created_at TIMESTAMP,
                FOREIGN KEY (node_id) REFERENCES wallets(conversation_id),
                FOREIGN KEY (bounty_id) REFERENCES bounties(id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                from_id TEXT,
                to_id TEXT,
                amount INTEGER,
                reason TEXT,
                bounty_id TEXT,
                created_at TIMESTAMP
            )
        """)
        print("[DB] 数据库初始化完成")