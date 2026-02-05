"""
ConceptNode - memory node

Each memory is a ConceptNode, containing:
- content (natural language description)
- timestamp
- importance score
- vector representation (for retrieval)
- access history (for calculating time decay)
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Dict, Any
import time


@dataclass
class ConceptNode:
    """A single memory node (one memory)"""
    
    # unique identifier
    node_id: str
    
    # memory content
    content: str                    # complete description
    
    # time information
    created: float                  # creation time (timestamp, seconds)
    last_accessed: float           # last access time (timestamp, seconds)
    expiration: Optional[float] = None  # expiration time (optional)
    
    # importance score (1-10)
    importance: int = 5
    
    # vector representation (for similarity retrieval)
    embedding: Optional[List[float]] = None
    
    # memory type
    memory_type: str = "observation"  # observation, reflection, plan
    
    # role information (optional)
    role: str = "user"  # user, assistant
    
    # access history (for calculating)
    access_history: List[float] = field(default_factory=list)
    
    # related information (optional)
    related_nodes: List[str] = field(default_factory=list)  # related memory IDs
    emotion: Optional[str] = None  # emotion label
    location: Optional[str] = None  # location information (for spatial memory)
    
    # metadata
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        """Validation and processing after initialization"""
        # ensure importance is within 1-10 range
        if self.importance < 1:
            self.importance = 1
        elif self.importance > 10:
            self.importance = 10
        
        # record first access
        if not self.access_history:
            self.access_history.append(self.created)
    
    def record_access(self):
        """record one access"""
        current_time = time.time()
        self.last_accessed = current_time
        self.access_history.append(current_time)
        
        # limit access history length (keep only last 100 accesses)
        if len(self.access_history) > 100:
            self.access_history = self.access_history[-100:]
    
    def get_age_hours(self, current_time: Optional[float] = None) -> float:
        """get memory age (hours)"""
        if current_time is None:
            current_time = time.time()
        return (current_time - self.created) / 3600
    
    def get_recency_score(self, current_time: Optional[float] = None, decay_rate: float = 0.99) -> float:
        """
        calculate recency score (time decay)
        
        Args:
            current_time: current timestamp, default is current time
            decay_rate: decay rate, default is 0.99 (1% decay per hour)
        
        Returns:
            recency score (0-1)
        """
        hours_ago = self.get_age_hours(current_time)
        return decay_rate ** hours_ago
    
    def is_expired(self, current_time: Optional[float] = None) -> bool:
        """check if memory is expired"""
        if self.expiration is None:
            return False
        if current_time is None:
            current_time = time.time()
        return current_time > self.expiration
    
    def to_dict(self) -> Dict[str, Any]:
        """convert to dictionary (for serialization)"""
        return {
            'node_id': self.node_id,
            'content': self.content,
            'created': self.created,
            'last_accessed': self.last_accessed,
            'expiration': self.expiration,
            'importance': self.importance,
            'embedding': self.embedding,
            'memory_type': self.memory_type,
            'role': self.role,
            'access_history': self.access_history[-10:],  # only keep last 10 accesses
            'related_nodes': self.related_nodes,
            'emotion': self.emotion,
            'location': self.location,
            'metadata': self.metadata
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ConceptNode':
        """create from dictionary (for deserialization)"""
        return cls(**data)
    
    def __str__(self) -> str:
        """string representation"""
        age_hours = self.get_age_hours()
        return f"[{self.memory_type}] {self.content[:50]}... (importance={self.importance}, age={age_hours:.1f}h)"
    
    def __repr__(self) -> str:
        return f"ConceptNode(id={self.node_id}, type={self.memory_type}, importance={self.importance})"
