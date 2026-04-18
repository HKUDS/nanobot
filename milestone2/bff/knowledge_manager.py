"""
KnowledgeManager - 负责PublicMemory管理和CWW异步合并

职责：
1. 预置0号Skill到PublicMemory
2. 接收协作者提交的page_content
3. 异步合并（CWW机制）- 不阻塞协作者
4. PublicMemory的读写管理
"""

import asyncio
import threading
import time
import uuid
import json
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Callable
from dataclasses import dataclass, field
from collections import deque


@dataclass
class PageSubmission:
    """协作者提交的Page"""
    page_id: str
    agent_id: str
    content: str
    page_title: str
    submitted_at: datetime = field(default_factory=datetime.now)
    round_num: Optional[int] = None


class KnowledgeManager:
    """KnowledgeManager核心类"""
    
    def __init__(
        self,
        public_memory_path: Path,
        merge_interval: float = 2.0,
        merge_threshold: int = 3
    ):
        self.public_memory_path = Path(public_memory_path)
        self.public_memory_path.parent.mkdir(parents=True, exist_ok=True)
        
        # CWW配置
        self.merge_interval = merge_interval  # 异步合并间隔(秒)
        self.merge_threshold = merge_threshold  # 达到N条就合并
        
        # 合并队列
        self._queue: deque[PageSubmission] = deque()
        self._queue_lock = threading.Lock()
        
        # 运行状态
        self._running = False
        self._merge_thread: threading.Thread = None
        
        # 统计
        self._page_counter = 0
        self._merged_count = 0
        
        # 初始化PublicMemory文件
        self._init_public_memory()
    
    def _init_public_memory(self):
        """初始化PublicMemory文件"""
        if not self.public_memory_path.exists():
            self.public_memory_path.write_text("", encoding="utf-8")
    
    def preset_skill_0(self, content: str, skill_version: str = "1.0") -> str:
        """预置0号Skill到PublicMemory"""
        entry = {
            "id": f"mem_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}",
            "agent_id": "system",
            "timestamp": datetime.now().isoformat(),
            "type": "data",
            "content": content,
            "metadata": {
                "page_id": "page_0_skill",
                "skill_version": skill_version,
                "preset": True
            }
        }
        self._append_to_public_memory(entry)
        return "page_0_skill"
    
    def submit_page(
        self,
        agent_id: str,
        page_content: str,
        page_title: str,
        round_num: Optional[int] = None
    ) -> str:
        """接收协作者提交的page_content（立即返回，不阻塞）"""
        page_id = f"page_{agent_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}_{self._page_counter}"
        self._page_counter += 1
        
        submission = PageSubmission(
            page_id=page_id,
            agent_id=agent_id,
            content=page_content,
            page_title=page_title,
            round_num=round_num
        )
        
        # 立即入队，不等待合并
        with self._queue_lock:
            self._queue.append(submission)
        
        return page_id
    
    def get_queue_size(self) -> int:
        """获取当前队列大小"""
        with self._queue_lock:
            return len(self._queue)
    
    def start_async_merge(self):
        """启动异步合并线程（CWW机制）"""
        if self._running:
            return
        
        self._running = True
        self._merge_thread = threading.Thread(target=self._merge_loop, daemon=True)
        self._merge_thread.start()
    
    def stop_async_merge(self):
        """停止异步合并线程"""
        self._running = False
        if self._merge_thread:
            self._merge_thread.join(timeout=5)
    
    def _merge_loop(self):
        """异步合并循环"""
        while self._running:
            time.sleep(self.merge_interval)
            self._process_merge()
    
    def _process_merge(self):
        """处理合并（达到阈值或间隔到了）"""
        with self._queue_lock:
            if not self._queue:
                return
            
            # 取出所有待合并的Page
            pages_to_merge = list(self._queue)
            self._queue.clear()
        
        # 批量写入PublicMemory
        for page in pages_to_merge:
            self._write_page_to_public_memory(page)
            self._merged_count += 1
    
    def _append_to_public_memory(self, entry: dict):
        """追加单条记录到PublicMemory"""
        with open(self.public_memory_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    
    def _write_page_to_public_memory(self, page: PageSubmission):
        """将Page写入PublicMemory"""
        entry = {
            "id": f"mem_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}",
            "agent_id": page.agent_id,
            "timestamp": datetime.now().isoformat(),
            "type": "data",
            "content": page.content,
            "metadata": {
                "page_id": page.page_id,
                "page_title": page.page_title,
                "merged_at": datetime.now().isoformat(),
                "submitted_at": page.submitted_at.isoformat(),
                "round": page.round_num
            }
        }
        self._append_to_public_memory(entry)
    
    def force_merge(self):
        """强制立即合并（用于测试或清理）"""
        self._process_merge()
    
    def read_public_memory(self) -> List[dict]:
        """读取PublicMemory所有内容"""
        if not self.public_memory_path.exists():
            return []
        
        entries = []
        with open(self.public_memory_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        return entries
    
    def get_skill_0(self) -> Optional[dict]:
        """获取0号Skill"""
        entries = self.read_public_memory()
        for entry in entries:
            if entry.get("metadata", {}).get("page_id") == "page_0_skill":
                return entry
        return None
    
    def search(self, query: str, top_k: int = 3) -> List[dict]:
        """搜索PublicMemory内容"""
        entries = self.read_public_memory()
        
        # 简单关键词匹配
        query_lower = query.lower()
        query_words = set(query_lower.split())
        
        scored = []
        for entry in entries:
            content = entry.get("content", "").lower()
            title = entry.get("metadata", {}).get("page_title", "").lower()
            text = f"{title} {content}"
            
            matches = sum(1 for word in query_words if word in text)
            if matches > 0:
                scored.append((matches / len(query_words), entry))
        
        scored.sort(key=lambda x: x[0], reverse=True)
        return [entry for _, entry in scored[:top_k]]
    
    def get_stats(self) -> dict:
        """获取统计信息"""
        entries = self.read_public_memory()
        return {
            "total_entries": len(entries),
            "queue_size": self.get_queue_size(),
            "merged_count": self._merged_count,
            "has_skill_0": self.get_skill_0() is not None
        }


# 全局KnowledgeManager实例（BFF进程级别）
_knowledge_manager: Optional[KnowledgeManager] = None
_km_lock = threading.Lock()


def get_knowledge_manager(
    public_memory_path: str = None,
    merge_interval: float = 2.0,
    merge_threshold: int = 3
) -> KnowledgeManager:
    """获取全局KnowledgeManager实例"""
    global _knowledge_manager
    
    with _km_lock:
        if _knowledge_manager is None:
            if public_memory_path is None:
                import os
                data_dir = Path(__file__).parent.parent / "data" / "public_memory"
                public_memory_path = data_dir / "public_memory.jsonl"
            
            _knowledge_manager = KnowledgeManager(
                public_memory_path=Path(public_memory_path),
                merge_interval=merge_interval,
                merge_threshold=merge_threshold
            )
            _knowledge_manager.start_async_merge()
        
        return _knowledge_manager
