import uuid
import json
import numpy as np
from datetime import datetime
from typing import Optional, List
from bff.db import get_db
from bff.deepseek_embedding import DeepSeekEmbedding


class ReflexEngine:
    def __init__(self):
        self.embedder = DeepSeekEmbedding()

    def _extract_feature_text(self, state: dict) -> str:
        goal = state.get("goal", "")
        history = state.get("history_summary", "")
        skills = ", ".join(state.get("available_skills", []))
        env = state.get("environment", {}).get("type", "")
        return f"{goal} {history} {skills} {env}"

    def _cosine_similarity(self, vec1: List[float], vec2: List[float]) -> float:
        v1 = np.array(vec1)
        v2 = np.array(vec2)
        return np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2))

    async def match(self, state: dict, threshold: float = 0.85) -> Optional[dict]:
        feature_text = self._extract_feature_text(state)
        query_vec = await self.embedder.embed_text(feature_text)
        with get_db() as conn:
            rows = conn.execute("SELECT * FROM reflexes WHERE confidence > ?", (0.3,)).fetchall()
        best = None
        best_score = 0
        for row in rows:
            row_dict = dict(row)
            if row_dict.get("embedding"):
                stored_vec = json.loads(row_dict["embedding"])
                sim = self._cosine_similarity(query_vec, stored_vec)
                if sim > threshold and sim > best_score:
                    best_score = sim
                    best = row_dict
        if best:
            return {
                "action_sequence": json.loads(best["action_sequence"]),
                "confidence": best_score
            }
        return None

    async def learn(self, state: dict, action_sequence: List[dict], agent_id: str, success: bool = True):
        feature_text = self._extract_feature_text(state)
        action_json = json.dumps(action_sequence)
        embedding = await self.embedder.embed_text(feature_text)
        embedding_json = json.dumps(embedding)
        with get_db() as conn:
            cur = conn.execute("SELECT id, confidence, usage_count, success_count FROM reflexes WHERE feature_text = ?", (feature_text,))
            row = cur.fetchone()
            if row:
                new_usage = row["usage_count"] + 1
                new_success = row["success_count"] + (1 if success else 0)
                new_conf = row["confidence"] + (0.05 if success else -0.05)
                new_conf = max(0.1, min(1.0, new_conf))
                conn.execute("""
                    UPDATE reflexes SET confidence = ?, usage_count = ?, success_count = ? WHERE id = ?
                """, (new_conf, new_usage, new_success, row["id"]))
            else:
                rid = str(uuid.uuid4())
                conn.execute("""
                    INSERT INTO reflexes (id, feature_text, embedding, action_sequence, confidence, source_agent_id, usage_count, success_count, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (rid, feature_text, embedding_json, action_json, 0.5, agent_id, 1, 1 if success else 0, datetime.now()))

    async def get_all_reflexes(self) -> List[dict]:
        with get_db() as conn:
            rows = conn.execute("SELECT * FROM reflexes ORDER BY confidence DESC").fetchall()
            return [dict(row) for row in rows]
