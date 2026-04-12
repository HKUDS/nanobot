import asyncio
from datetime import datetime
from bff.db import get_db

class TokenWallet:
    def __init__(self):
        self._lock = asyncio.Lock()

    async def get_balance(self, conv_id: str) -> int:
        with get_db() as conn:
            cur = conn.execute("SELECT balance FROM wallets WHERE conversation_id = ?", (conv_id,))
            row = cur.fetchone()
            if not row:
                conn.execute("INSERT INTO wallets (conversation_id, balance, updated_at) VALUES (?, 1000000, ?)",
                             (conv_id, datetime.now()))
                return 1000000
            return row["balance"]

    async def transfer(self, from_id: str, to_id: str, amount: int, reason: str, bounty_id: str = None):
        if amount <= 0:
            raise ValueError("Amount must be positive")
        async with self._lock:
            with get_db() as conn:
                # 检查发送方余额
                cur = conn.execute("SELECT balance FROM wallets WHERE conversation_id = ?", (from_id,))
                row = cur.fetchone()
                if not row or row["balance"] < amount:
                    raise ValueError("Insufficient balance")
                # 确保接收方钱包存在（包括 system）
                conn.execute("INSERT OR IGNORE INTO wallets (conversation_id, balance, updated_at) VALUES (?, 0, ?)",
                             (to_id, datetime.now()))
                # 扣款
                conn.execute("UPDATE wallets SET balance = balance - ?, updated_at = ? WHERE conversation_id = ?",
                             (amount, datetime.now(), from_id))
                # 加款
                conn.execute("UPDATE wallets SET balance = balance + ?, updated_at = ? WHERE conversation_id = ?",
                             (amount, datetime.now(), to_id))
                # 记录交易
                conn.execute("""
                    INSERT INTO transactions (from_id, to_id, amount, reason, bounty_id, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (from_id, to_id, amount, reason, bounty_id, datetime.now()))

    async def ensure_wallet(self, conv_id: str):
        with get_db() as conn:
            conn.execute("INSERT OR IGNORE INTO wallets (conversation_id, balance, updated_at) VALUES (?, 1000000, ?)",
                         (conv_id, datetime.now()))