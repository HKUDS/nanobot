"""
Retrieve Module - retrieve relevant information from memories

Implement Stanford GA's three-dimensional memory retrieval algorithm:
1. Recency (recent): time decay, the closer the memory, the higher the weight
2. Importance (important): memory importance score (1-10)
3. Relevance (relevant): semantic similarity with the query

Retrieval score = α·recency + β·importance + γ·relevance

References: Stanford Generative Agents paper
"""

import numpy as np
from typing import List, Optional, Tuple
from .concept_node import ConceptNode
from loguru import logger
import time

TAG = __name__

class RetrieveModule:
    """
    Retrieve Module - retrieve relevant information from memories
    
    This is the first step of Stanford GA cognitive loop: Retrieve
    """
    
    def __init__(
        self,
        alpha: float = 1.0,    # recency weight
        beta: float = 1.0,     # importance weight
        gamma: float = 1.0,    # relevance weight
        decay_rate: float = 0.99,  # time decay rate (1% decay per hour)
    ):
        """
        initialize retrieve module
        
        Args:
            alpha: recency weight
            beta: importance weight
            gamma: relevance weight
            decay_rate: time decay rate, default 0.99 (1% decay per hour)
        """
        self.alpha = alpha
        self.beta = beta
        self.gamma = gamma
        self.decay_rate = decay_rate
        
        logger.bind(tag=TAG).info(
            f"RetrieveModule initialized with weights: "
            f"alpha={alpha}, beta={beta}, gamma={gamma}, decay_rate={decay_rate}"
        )
    
    def retrieve(
        self,
        query_embedding: List[float],
        memories: List[ConceptNode],
        k: int = 5,
        current_time: Optional[float] = None,
    ) -> List[Tuple[ConceptNode, float]]:
        """
        retrieve the most relevant k memories
        
        Args:
            query_embedding: query embedding
            memories: candidate memories list
            k: number of memories to return
            current_time: current timestamp, default is current time
        
        Returns:
            List[Tuple[ConceptNode, float]]: (memory node, total score) list, sorted by score in descending order
        """
        if not memories:
            return []
        
        if current_time is None:
            current_time = time.time()
        
        # calculate the three-dimensional score for each memory
        scored_memories = []
        for memory in memories:
            score = self._calculate_retrieval_score(
                query_embedding=query_embedding,
                memory=memory,
                current_time=current_time
            )
            # ensure the score is Python native float (avoid numpy.float64 serialization problem)
            scored_memories.append((memory, float(score)))
            
            # record access (affects last_accessed)
            memory.record_access()
        
        # sort by score in descending order
        scored_memories.sort(key=lambda x: x[1], reverse=True)
        
        # return the top k memories
        return scored_memories[:k]
    
    def _calculate_retrieval_score(
        self,
        query_embedding: List[float],
        memory: ConceptNode,
        current_time: float,
    ) -> float:
        """
        calculate the retrieval score for a single memory
        
        Score = α·recency + β·importance + γ·relevance
        
        Args:
            query_embedding: query embedding
            memory: memory node
            current_time: current timestamp
        
        Returns:
            retrieval score (0-1 range, normalized)
        """
        # 1. calculate Recency (recent)
        recency = self._calculate_recency(memory, current_time)
        
        # 2. calculate Importance (important)
        importance = self._calculate_importance(memory)
        
        # 3. calculate Relevance (relevant)
        relevance = self._calculate_relevance(query_embedding, memory)
        
        # 4. weighted combination
        total_weight = self.alpha + self.beta + self.gamma
        score = (
            self.alpha * recency +
            self.beta * importance +
            self.gamma * relevance
        ) / total_weight
        
        logger.bind(tag=TAG).debug(
            f"Memory '{memory.content[:30]}...': "
            f"recency={recency:.4f}, importance={importance:.4f}, relevance={relevance:.4f}, "
            f"final_score={score:.4f}"
        )
        
        # ensure the return value is Python native float type
        return float(score)
    
    def _calculate_recency(self, memory: ConceptNode, current_time: float) -> float:
        """
        calculate recent score (time decay)
        
        recency = decay_rate ^ hours_since_creation
        
        Args:
            memory: memory node
            current_time: current timestamp
        
        Returns:
            recent score (0-1)
        """
        return memory.get_recency_score(current_time, self.decay_rate)
    
    def _calculate_importance(self, memory: ConceptNode) -> float:
        """
        calculate importance score (normalized to 0-1)
        
        Args:
            memory: memory node (importance score 1-10)
        
        Returns:
            importance score (0-1)
        """
        # importance score is 1-10, normalized to 0-1
        return (memory.importance - 1) / 9.0
    
    def _calculate_relevance(
        self,
        query_embedding: List[float],
        memory: ConceptNode,
    ) -> float:
        """
        calculate relevance score (cosine similarity)
        
        Args:
            query_embedding: query embedding
            memory: memory node
        
        Returns:
            relevance score (0-1)
        """
        if memory.embedding is None or len(memory.embedding) == 0:
            # if memory has no embedding, return medium relevance
            logger.bind(tag=TAG).warning(
                f"Memory '{memory.node_id}' has no embedding, using default relevance 0.5"
            )
            return 0.5
        
        # calculate cosine similarity
        similarity = self._cosine_similarity(query_embedding, memory.embedding)
        
        # cosine similarity range is [-1, 1], normalized to [0, 1]
        normalized_similarity = (similarity + 1) / 2
        
        return normalized_similarity
    
    @staticmethod
    def _cosine_similarity(vec1: List[float], vec2: List[float]) -> float:
        """
        calculate cosine similarity of two vectors
        
        Args:
            vec1: vector 1
            vec2: vector 2
        
        Returns:
            cosine similarity (-1 to 1)
        """
        if len(vec1) != len(vec2):
            logger.bind(tag=TAG).error(
                f"Vector dimension mismatch: {len(vec1)} vs {len(vec2)}"
            )
            return 0.0
        
        # convert to numpy array
        v1 = np.array(vec1)
        v2 = np.array(vec2)
        
        # calculate cosine similarity
        dot_product = np.dot(v1, v2)
        norm1 = np.linalg.norm(v1)
        norm2 = np.linalg.norm(v2)
        
        if norm1 == 0 or norm2 == 0:
            return 0.0
        
        # convert to Python native float to avoid msgpack serialization problem
        return float(dot_product / (norm1 * norm2))
    
    def update_weights(
        self,
        alpha: Optional[float] = None,
        beta: Optional[float] = None,
        gamma: Optional[float] = None,
    ):
        """
        dynamically update retrieval weights
        
        Args:
            alpha: new recency weight
            beta: new importance weight
            gamma: new relevance weight
        """
        if alpha is not None:
            self.alpha = alpha
        if beta is not None:
            self.beta = beta
        if gamma is not None:
            self.gamma = gamma
        
        logger.bind(tag=TAG).info(
            f"Retrieval weights updated: alpha={self.alpha}, beta={self.beta}, gamma={self.gamma}"
        )


# keep backward compatibility alias
MemoryRetrieval = RetrieveModule
