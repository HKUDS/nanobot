import uuid
from datetime import datetime
from typing import List
from bff.db import get_db

class NodeRelationManager:
    def __init__(self):
        pass
    
    async def add_relation(self, source_node_id: str, target_node_id: str, weight: int = 1):
        """添加节点关系（双向：如果A→B，则B→A也存在）"""
        with get_db() as conn:
            # 创建 source → target 关系
            existing = conn.execute("""
                SELECT id FROM node_relations
                WHERE source_node_id = ? AND target_node_id = ?
            """, (source_node_id, target_node_id)).fetchone()

            if existing:
                conn.execute("""
                    UPDATE node_relations SET weight = ?, updated_at = ?
                    WHERE id = ?
                """, (weight, datetime.now(), existing["id"]))
                print(f"[NodeRelation] 更新关系：{source_node_id} -> {target_node_id}, weight={weight}")
            else:
                relation_id = str(uuid.uuid4())
                conn.execute("""
                    INSERT INTO node_relations (id, source_node_id, target_node_id, weight, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (relation_id, source_node_id, target_node_id, weight, datetime.now(), datetime.now()))
                print(f"[NodeRelation] 创建关系：{source_node_id} -> {target_node_id}, weight={weight}")

            # 创建反向 target → source 关系（双向）
            existing_rev = conn.execute("""
                SELECT id FROM node_relations
                WHERE source_node_id = ? AND target_node_id = ?
            """, (target_node_id, source_node_id)).fetchone()

            if existing_rev:
                conn.execute("""
                    UPDATE node_relations SET weight = ?, updated_at = ?
                    WHERE id = ?
                """, (weight, datetime.now(), existing_rev["id"]))
                print(f"[NodeRelation] 更新反向关系：{target_node_id} -> {source_node_id}, weight={weight}")
            else:
                relation_id_rev = str(uuid.uuid4())
                conn.execute("""
                    INSERT INTO node_relations (id, source_node_id, target_node_id, weight, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (relation_id_rev, target_node_id, source_node_id, weight, datetime.now(), datetime.now()))
                print(f"[NodeRelation] 创建反向关系：{target_node_id} -> {source_node_id}, weight={weight}")
    
    async def get_neighbors(self, node_id: str) -> List[dict]:
        """获取节点的邻居"""
        with get_db() as conn:
            rows = conn.execute("""
                SELECT target_node_id as node_id, weight
                FROM node_relations
                WHERE source_node_id = ?
                UNION
                SELECT source_node_id as node_id, weight
                FROM node_relations
                WHERE target_node_id = ?
            """, (node_id, node_id)).fetchall()
        return [dict(row) for row in rows]
    
    async def update_weight(self, source_node_id: str, target_node_id: str, weight: int):
        """更新节点关系的权重"""
        with get_db() as conn:
            conn.execute("""
                UPDATE node_relations
                SET weight = ?, updated_at = ?
                WHERE (source_node_id = ? AND target_node_id = ?) OR (source_node_id = ? AND target_node_id = ?)
            """, (weight, datetime.now(), source_node_id, target_node_id, target_node_id, source_node_id))
    
    async def get_relation(self, source_node_id: str, target_node_id: str) -> dict:
        """获取节点间的关系"""
        with get_db() as conn:
            row = conn.execute("""
                SELECT * FROM node_relations
                WHERE (source_node_id = ? AND target_node_id = ?) OR (source_node_id = ? AND target_node_id = ?)
            """, (source_node_id, target_node_id, target_node_id, source_node_id)).fetchone()
        if row:
            return dict(row)
        return None
    
    async def delete_relation(self, source_node_id: str, target_node_id: str):
        """删除节点关系"""
        with get_db() as conn:
            conn.execute("""
                DELETE FROM node_relations
                WHERE (source_node_id = ? AND target_node_id = ?) OR (source_node_id = ? AND target_node_id = ?)
            """, (source_node_id, target_node_id, target_node_id, source_node_id))