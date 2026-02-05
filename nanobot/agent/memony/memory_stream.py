"""
MemoryStream 

Manage all memory nodes, store them in chronological order
Provide basic add, delete, query, and modify functions
"""

from typing import List, Optional, Dict, Any
from datetime import datetime
import time
import json
import os
from .concept_node import ConceptNode
from loguru import logger
TAG = __name__

class MemoryStream:
    """memory stream - store and manage all memory nodes"""
    
    def __init__(self, role_id: str, save_to_file: bool = True, memory_file: Optional[str] = None):
        """
        initialize memory stream
        
        Args:
            role_id: user/role ID
            save_to_file: whether to save to file
            memory_file: memory file path (optional)
        """
        self.role_id = role_id
        self.save_to_file = save_to_file
        
        # memory storage
        self.nodes: Dict[str, ConceptNode] = {}  # {node_id: ConceptNode}
        self.event_sequence: List[str] = []  # event sequence (node_id in chronological order)
        self.reflection_sequence: List[str] = []  # reflection sequence
        
        # accumulated importance (for triggering reflection)
        self.accumulated_importance = 0
        
        # file path
        if memory_file:
            self.memory_file = memory_file

        # try to load existing memory
        if self.save_to_file:
            self.load_from_file()
    
    def add_node(self, node: ConceptNode, accumulate_importance: bool = True) -> str:
        """
        add a memory node
        
        Args:
            node: memory node
            accumulate_importance: whether to accumulate importance (default True).
                                    reflection memory is usually set to False to avoid infinite reflection
        
        Returns:
            node ID
        """
        # store node
        self.nodes[node.node_id] = node
        
        # add to corresponding sequence
        if node.memory_type == "reflection":
            self.reflection_sequence.append(node.node_id)
        else:
            self.event_sequence.append(node.node_id)
        
        # accumulate importance (optional)
        if accumulate_importance:
            self.accumulated_importance += node.importance
        
        # save to file
        if self.save_to_file:
            self.save_to_file_async()
        
        logger.bind(tag=TAG).debug(
            f"added memory: [{node.memory_type}] {node.content[:30]}... (importance={node.importance})"
        )
        
        return node.node_id
    
    def get_node(self, node_id: str) -> Optional[ConceptNode]:
        """get specified memory node"""
        node = self.nodes.get(node_id)
        if node:
            node.record_access()  # record access
        return node
    
    def get_all_nodes(self, include_expired: bool = False) -> List[ConceptNode]:
        """
        get all memory nodes
        
        Args:
            include_expired: whether to include expired memory
        
        Returns:
            memory node list
        """
        current_time = time.time()
        
        if include_expired:
            return list(self.nodes.values())
        else:
            return [
                node for node in self.nodes.values()
                if not node.is_expired(current_time)
            ]
    
    def get_recent_nodes(self, n: int = 100, memory_type: Optional[str] = None) -> List[ConceptNode]:
        """
        get recent N memory nodes
        
        Args:
            n: return number
            memory_type: memory type filter (optional)
        
        Returns:
            memory node list
        """
        # select sequence
        if memory_type == "reflection":
            sequence = self.reflection_sequence
        elif memory_type == "observation":
            sequence = self.event_sequence
        else:
            # merge and sort
            all_ids = self.event_sequence + self.reflection_sequence
            sequence = sorted(
                all_ids,
                key=lambda nid: self.nodes[nid].created if nid in self.nodes else 0,
                reverse=True
            )
        
        # get recent N nodes
        recent_ids = sequence[-n:]
        recent_ids.reverse()  # latest first
        
        # return nodes
        nodes = []
        for node_id in recent_ids:
            if node_id in self.nodes:
                nodes.append(self.nodes[node_id])
        
        return nodes
    
    def get_nodes_by_type(self, memory_type: str) -> List[ConceptNode]:
        """get all memory nodes of specified type"""
        return [
            node for node in self.nodes.values()
            if node.memory_type == memory_type
        ]
    
    def get_nodes_since(self, timestamp: float) -> List[ConceptNode]:
        """get all memory nodes since specified time"""
        return [
            node for node in self.nodes.values()
            if node.created >= timestamp
        ]
    
    def delete_node(self, node_id: str) -> bool:
        """delete memory node"""
        if node_id in self.nodes:
            node = self.nodes[node_id]
            
            if node.memory_type == "reflection" and node_id in self.reflection_sequence:
                self.reflection_sequence.remove(node_id)
            elif node_id in self.event_sequence:
                self.event_sequence.remove(node_id)
            
            del self.nodes[node_id]
            
            if self.save_to_file:
                self.save_to_file_async()
            
            logger.bind(tag=TAG).debug(f"deleted memory: {node_id}")
            return True
        
        return False
    
    def clear_expired_nodes(self) -> int:
        """clear expired memory nodes"""
        current_time = time.time()
        expired_ids = [
            node_id for node_id, node in self.nodes.items()
            if node.is_expired(current_time)
        ]
        
        for node_id in expired_ids:
            self.delete_node(node_id)
        
        if expired_ids:
            logger.bind(tag=TAG).info(f"cleared {len(expired_ids)} expired memory nodes")
        
        return len(expired_ids)
    
    def get_statistics(self) -> Dict[str, Any]:
        """get memory statistics"""
        return {
            'total_nodes': len(self.nodes),
            'observations': len(self.event_sequence),
            'reflections': len(self.reflection_sequence),
            'accumulated_importance': self.accumulated_importance,
            'avg_importance': sum(n.importance for n in self.nodes.values()) / len(self.nodes) if self.nodes else 0,
            'oldest_memory_hours': min(n.get_age_hours() for n in self.nodes.values()) if self.nodes else 0,
        }
    
    def reset_accumulated_importance(self):
        """reset accumulated importance (after reflection)"""
        self.accumulated_importance = 0
        logger.bind(tag=TAG).debug("reset accumulated importance counter")
    
    def save_to_file_async(self):
        """async save to file (non-blocking)"""
        if not self.save_to_file:
            return
        
        try:
            # serialize data
            data = {
                'role_id': self.role_id,
                'accumulated_importance': self.accumulated_importance,
                'nodes': {
                    node_id: node.to_dict()
                    for node_id, node in self.nodes.items()
                },
                'event_sequence': self.event_sequence,
                'reflection_sequence': self.reflection_sequence,
                'last_updated': time.time()
            }
            
            # ensure directory exists
            os.makedirs(os.path.dirname(self.memory_file), exist_ok=True)
            
            # write to file
            with open(self.memory_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            logger.bind(tag=TAG).debug(f"memory saved to file: {self.memory_file}")
        
        except Exception as e:
            logger.bind(tag=TAG).error(f"failed to save memory to file: {e}")
    
    def load_from_file(self):
        """load from file"""
        if not os.path.exists(self.memory_file):
            logger.bind(tag=TAG).info(f"memory file not found, creating new memory stream: {self.memory_file}")
            return
        
        try:
            with open(self.memory_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # restore data
            self.role_id = data.get('role_id', self.role_id)
            self.accumulated_importance = data.get('accumulated_importance', 0)
            self.event_sequence = data.get('event_sequence', [])
            self.reflection_sequence = data.get('reflection_sequence', [])
            
            # restore nodes
            nodes_data = data.get('nodes', {})
            for node_id, node_dict in nodes_data.items():
                try:
                    self.nodes[node_id] = ConceptNode.from_dict(node_dict)
                except Exception as e:
                    logger.bind(tag=TAG).warning(f"failed to restore memory node {node_id}: {e}")
            
            logger.bind(tag=TAG).info(
                f"loaded {len(self.nodes)} memory nodes (observations:{len(self.event_sequence)}, reflections:{len(self.reflection_sequence)})"
            )
        
        except Exception as e:
            logger.bind(tag=TAG).error(f"failed to load memory from file: {e}")
    
    def __len__(self) -> int:
        """return memory total number"""
        return len(self.nodes)
    
    def __str__(self) -> str:
        """string representation"""
        stats = self.get_statistics()
        return f"MemoryStream(total={stats['total_nodes']}, obs={stats['observations']}, ref={stats['reflections']})"
