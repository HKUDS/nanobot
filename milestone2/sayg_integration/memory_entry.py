from dataclasses import dataclass, asdict, field
from datetime import datetime
from typing import Optional, Dict, Any
import uuid
import json

@dataclass
class MemoryEntry:
    id: str
    agent_id: str
    timestamp: str
    type: str
    content: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def create(
        agent_id: str,
        type: str,
        content: str,
        task_id: str = None,
        round: int = None,
        version: int = 1,
        quality_score: float = None,
        page_id: str = None,
        **kwargs
    ) -> "MemoryEntry":
        entry_id = f"mem_{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:6]}"
        return MemoryEntry(
            id=entry_id,
            agent_id=agent_id,
            timestamp=datetime.now().isoformat() + "Z",
            type=type,
            content=content,
            metadata={
                "task_id": task_id,
                "round": round,
                "version": version,
                "quality_score": quality_score,
                "page_id": page_id,
                **{k: v for k, v in kwargs.items() if v is not None}
            }
        )

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    @staticmethod
    def from_json(json_str: str) -> "MemoryEntry":
        data = json.loads(json_str)
        return MemoryEntry(**data)

    def get_content_hash(self) -> str:
        content_str = f"{self.agent_id}:{self.content}"
        return str(hash(content_str))
