from datetime import datetime
from typing import List
from bff.db import get_db

class SocialGraph:
    async def add_friend(self, agent_a: str, agent_b: str):
        with get_db() as conn:
            conn.execute("INSERT OR IGNORE INTO friendships (agent_a, agent_b, trust_score, created_at) VALUES (?, ?, 0.5, ?)",
                         (agent_a, agent_b, datetime.now()))
            conn.execute("INSERT OR IGNORE INTO friendships (agent_a, agent_b, trust_score, created_at) VALUES (?, ?, 0.5, ?)",
                         (agent_b, agent_a, datetime.now()))

    async def update_trust(self, agent_a: str, agent_b: str, delta: float):
        with get_db() as conn:
            conn.execute("UPDATE friendships SET trust_score = MIN(1.0, MAX(0.0, trust_score + ?)) WHERE agent_a = ? AND agent_b = ?",
                         (delta, agent_a, agent_b))

    async def get_friends(self, agent_id: str, min_trust: float = 0.3) -> List[str]:
        with get_db() as conn:
            rows = conn.execute("SELECT agent_b FROM friendships WHERE agent_a = ? AND trust_score > ?", (agent_id, min_trust)).fetchall()
            return [row["agent_b"] for row in rows]

    async def recommend_friends(self, agent_id: str, task_description: str = "", top_k: int = 3) -> List[dict]:
        with get_db() as conn:
            rows = conn.execute("""
                SELECT agent_b, trust_score FROM friendships 
                WHERE agent_a = ? 
                ORDER BY trust_score DESC LIMIT ?
            """, (agent_id, top_k)).fetchall()
            return [{"agent_id": row["agent_b"], "trust_score": row["trust_score"]} for row in rows]

    async def get_friends_with_trust(self, agent_id: str) -> List[dict]:
        with get_db() as conn:
            rows = conn.execute("SELECT agent_b, trust_score FROM friendships WHERE agent_a = ? ORDER BY trust_score DESC", (agent_id,)).fetchall()
            return [dict(row) for row in rows]