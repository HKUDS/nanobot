"""
MemoryManager: unified memory manager

Integrates the Stanford Generative Agents memory system:
- Memory storage (MemoryStream)
- Importance scoring (ImportanceScorer)
- Embedding generation (EmbeddingGenerator)
- 3D retrieval (RetrieveModule)
- Reflection mechanism (ReflectModule)

Flow:
1. Receive message → Store observation + evaluate importance
2. Retrieve relevant memories (3D retrieval)
3. Build context (includes retrieved memories)
4. Call LLM → Execute tools
5. Check if reflection is triggered
6. Store assistant response
7. Response
"""

import uuid
import time
from typing import List, Optional, Dict, Any, Tuple
from pathlib import Path

from loguru import logger

from .memony.concept_node import ConceptNode
from .memony.memory_stream import MemoryStream
from .memony.importance_scorer import ImportanceScorer
from .memony.embedding_generator import EmbeddingGenerator
from .memony.retrieve import RetrieveModule
from .memony.reflect import ReflectModule

TAG = __name__



class MemoryManager:
    """
    Unified memory manager
    
    Integrates all memory-related operations, providing a simple API for AgentLoop usage
    """
    
    def __init__(
        self,
        role_id: str,
        workspace: Path,
        embedding_config: Optional[Dict[str, Any]] = None,
        reflection_threshold: int = 150,
        reflection_enabled: bool = True,
        use_llm_for_importance: bool = False,
    ):
        """
        Initialize memory manager
        
        Args:
            role_id: role/session ID
            workspace: workspace path
            embedding_config: embedding generation configuration
            reflection_threshold: reflection trigger threshold
            reflection_enabled: whether to enable reflection
            use_llm_for_importance: whether to use LLM for importance evaluation
        """
        self.role_id = role_id
        self.workspace = workspace
        
        # Initialize each module
        self.memory_stream = MemoryStream(
            role_id=role_id,
            save_to_file=True,
            memory_file=str(workspace / "memory" / f".memory_{role_id}.json")
        )
        
        self.importance_scorer = ImportanceScorer(use_llm=use_llm_for_importance)
        
        self.embedding_generator = EmbeddingGenerator(embedding_config or {
            "provider": "dummy",  # default using dummy, should configure openai or local in production environment
            "dimension": 1536,
        })
        
        self.retriever = RetrieveModule(
            alpha=1.0,   # recency weight
            beta=1.0,    # importance weight
            gamma=1.0,   # relevance weight
            decay_rate=0.99,
        )
        
        self.reflector = ReflectModule(
            threshold=reflection_threshold,
            depth=3,
            min_time_interval=3600,  # minimum 1 hour interval
            enabled=reflection_enabled,
        )
        
        logger.bind(tag=TAG).info(
            f"MemoryManager initialized for role_id={role_id}, "
            f"reflection_enabled={reflection_enabled}, threshold={reflection_threshold}"
        )
    
    async def add_observation(
        self,
        content: str,
        role: str = "user",
        llm=None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ConceptNode:
        """
        Add observation memory (user message or assistant response)
        
        This is the 2nd and 8th step of the flow:
        - Step 2: Store user message + evaluate importance
        - Step 8: Store assistant response
        
        Args:
            content: memory content
            role: role (user/assistant)
            llm: LLM instance (for importance evaluation, optional)
            metadata: additional metadata
        
        Returns:
            created memory node
        """
        # 1. Evaluate importance
        importance = self.importance_scorer.score(content, role, llm)
        
        # 2. Generate vector representation
        embedding = await self.embedding_generator.generate_embedding(content)
        
        # 3. Create memory node
        current_time = time.time()
        node = ConceptNode(
            node_id=f"obs_{uuid.uuid4().hex[:12]}",
            content=content,
            created=current_time,
            last_accessed=current_time,
            importance=importance,
            embedding=embedding,
            memory_type="observation",
            role=role,
            metadata=metadata or {},
        )
        
        # 4. Add to memory stream
        self.memory_stream.add_node(node, accumulate_importance=True)
        
        logger.bind(tag=TAG).debug(
            f"Added observation: role={role}, importance={importance}, "
            f"content={content[:50]}..."
        )
        
        return node
    
    async def retrieve_relevant_memories(
        self,
        query: str,
        k: int = 5,
    ) -> List[Tuple[ConceptNode, float]]:
        """
        Retrieve relevant memories (3D retrieval)
        
        This is the 3rd step of the flow: Retrieve relevant memories
        
        Args:
            query: query text (usually the user's new message)
            k: number of memories to return
        
        Returns:
            relevant memories list, each item is (memory node, combined score)
        """
        # 1. Generate query vector
        query_embedding = await self.embedding_generator.generate_embedding(query)
        
        # 2. Get all memories
        all_memories = self.memory_stream.get_all_nodes(include_expired=False)
        
        if not all_memories:
            logger.bind(tag=TAG).debug("No memories to retrieve from")
            return []
        
        # 3. Use 3D retrieval
        relevant = self.retriever.retrieve(
            query_embedding=query_embedding,
            memories=all_memories,
            k=k,
        )
        
        logger.bind(tag=TAG).debug(
            f"Retrieved {len(relevant)} memories for query: {query[:50]}..."
        )
        
        return relevant
    
    def format_memories_for_context(
        self,
        memories: List[Tuple[ConceptNode, float]],
        max_memories: int = 10,
    ) -> str:
        """
        Format retrieved memories into a context string
        
        This is part of the 4th step of the flow: Build context
        
        Args:
            memories: retrieved memories list
            max_memories: maximum number of memories
        
        Returns:
            formatted memory context
        """
        if not memories:
            return ""
        
        lines = ["## Related memories"]
        
        for i, (node, score) in enumerate(memories[:max_memories], 1):
            age_hours = node.get_age_hours()
            role_label = "user" if node.role == "user" else "assistant"
            
            # Format: [time ago] role: content (relevance)
            lines.append(
                f"{i}. [{age_hours:.1f} hours ago] {role_label}: {node.content} "
                f"(importance:{node.importance}, relevance:{score:.2f})"
            )
        
        return "\n".join(lines)
    
    async def check_and_reflect(
        self,
        llm,
        agent_name: str = "用户",
    ) -> List[ConceptNode]:
        """
        Check if reflection is needed, if needed then perform reflection
        
        This is the 7th step of the flow: Check if reflection is triggered
        
        Args:
            llm: LLM instance
            agent_name: Agent name
        
        Returns:
            generated reflection memories list (if reflection is triggered)
        """
        # 1. Check if reflection is needed
        accumulated = self.memory_stream.accumulated_importance
        if not self.reflector.should_reflect(accumulated):
            return []
        
        logger.bind(tag=TAG).info(
            f"Reflection triggered! accumulated_importance={accumulated}"
        )
        
        # 2. Get recent memories
        recent_memories = self.memory_stream.get_recent_nodes(n=50)
        
        # 3. Generate reflection questions
        questions = await self.reflector.generate_reflection_questions_async(
            agent_name=agent_name,
            recent_memories=recent_memories,
            llm=llm,
            num_questions=3,
        )
        
        # 4. Retrieve relevant memories for each question and generate insights
        insights = []
        for question in questions:
            # Retrieve relevant memories for the question
            relevant = await self.retrieve_relevant_memories(question, k=10)
            
            # Generate insights
            question_insights = await self.reflector.generate_insights(
                questions=[question],
                relevant_memories=relevant,
                llm=llm,
                agent_name=agent_name,
            )
            insights.extend(question_insights)
        
        # 5. Store insights into memory
        reflection_nodes = []
        for insight in insights:
            embedding = await self.embedding_generator.generate_embedding(insight["insight"])
            
            current_time = time.time()
            node = ConceptNode(
                node_id=f"ref_{uuid.uuid4().hex[:12]}",
                content=insight["insight"],
                created=current_time,
                last_accessed=current_time,
                importance=insight["importance"],
                embedding=embedding,
                memory_type="reflection",
                role="assistant",
                related_nodes=insight["evidence"],
                metadata={
                    "question": insight["question"],
                },
            )
            
            # Reflection memory does not accumulate importance (to avoid infinite reflection)
            self.memory_stream.add_node(node, accumulate_importance=False)
            reflection_nodes.append(node)
        
        # 6. Reset accumulated importance
        self.memory_stream.reset_accumulated_importance()
        self.reflector.update_reflection_state()
        
        logger.bind(tag=TAG).info(
            f"Reflection completed: generated {len(reflection_nodes)} insights"
        )
        
        return reflection_nodes
    
    def get_recent_context(self, n: int = 10) -> str:
        """
        Get recent memory context (not based on query)
        
        Args:
            n: number of memories to return
        
        Returns:
            formatted memory context
        """
        recent = self.memory_stream.get_recent_nodes(n=n)
        
        if not recent:
            return ""
        
        lines = ["## Recent memories"]
        
        for node in recent:
            age_hours = node.get_age_hours()
            role_label = "user" if node.role == "user" else "assistant"
            type_label = "[reflection]" if node.memory_type == "reflection" else ""
            
            lines.append(
                f"- [{age_hours:.1f} hours ago] {type_label}{role_label}: {node.content[:100]}"
            )
        
        return "\n".join(lines)
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get memory statistics"""
        stream_stats = self.memory_stream.get_statistics()
        
        return {
            **stream_stats,
            "reflection_enabled": self.reflector.enabled,
            "reflection_threshold": self.reflector.threshold,
            "last_reflection_time": self.reflector.last_reflection_time,
        }
    
    def clear_expired(self) -> int:
        """Clear expired memories"""
        return self.memory_stream.clear_expired_nodes()
