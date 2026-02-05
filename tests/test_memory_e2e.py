"""End-to-end scenario tests for the memory system.

Tests realistic conversation flows simulating actual user interactions,
covering extraction, consolidation, compaction, and cross-session persistence.
"""

import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import Mock, patch

import pytest

from nanobot.agent.memory.consolidator import MemoryConsolidator, Operation
from nanobot.agent.memory.extractor import ExtractedFact, MemoryExtractor
from nanobot.agent.memory.store import VectorMemoryStore
from nanobot.session.compaction import SessionCompactor


class MockEmbeddingService:
    """Mock embedding service for testing without API calls."""

    def __init__(self):
        self.dimension = 1536
        self._cache = {}

    def embed(self, text: str) -> list[float]:
        """Generate deterministic embeddings based on text hash."""
        if text in self._cache:
            return self._cache[text]

        # Simple hash-based embedding for deterministic testing
        import hashlib
        hash_val = int(hashlib.md5(text.encode()).hexdigest(), 16)
        embedding = [(hash_val >> (i % 128)) % 100 / 100.0 for i in range(self.dimension)]
        self._cache[text] = embedding
        return embedding


@pytest.fixture
def temp_dir():
    """Temporary directory for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def mock_embedding():
    """Mock embedding service."""
    return MockEmbeddingService()


@pytest.fixture
def store(temp_dir, mock_embedding):
    """Memory store with mock embeddings."""
    return VectorMemoryStore(Path("test.db"), base_dir=temp_dir, embedding_service=mock_embedding)


@pytest.fixture
def extractor():
    """Memory extractor (will be mocked for LLM calls)."""
    return MemoryExtractor(model="gpt-4o-mini")


@pytest.fixture
def consolidator(store):
    """Memory consolidator (will be mocked for LLM calls)."""
    return MemoryConsolidator(store, model="gpt-4o-mini")


@pytest.fixture
def compactor():
    """Session compactor."""
    return SessionCompactor()


# Scenario 1: New User Onboarding
def test_scenario_new_user_onboarding(store, extractor, consolidator):
    """Test extracting and storing facts from new user introduction."""
    conversation = [
        {"role": "user", "content": "Hi, my name is John and I'm a software developer"},
        {"role": "assistant", "content": "Hello John! Nice to meet you."},
        {"role": "user", "content": "I work at TechCorp in San Francisco"},
        {"role": "assistant", "content": "Great! How can I help you today?"},
        {"role": "user", "content": "I prefer Python over JavaScript"},
        {"role": "assistant", "content": "Noted! Python is a great choice."},
    ]

    # Mock LLM extraction
    mock_facts = [
        ExtractedFact(content="User's name is John", importance=0.9, source="llm"),
        ExtractedFact(content="User is a software developer", importance=0.8, source="llm"),
        ExtractedFact(content="User works at TechCorp in San Francisco", importance=0.8, source="llm"),
        ExtractedFact(content="User prefers Python over JavaScript", importance=0.7, source="llm"),
    ]

    with patch.object(extractor, 'extract', return_value=mock_facts):
        facts = extractor.extract(conversation)

    # Mock LLM consolidation decisions (all ADD for new user)
    with patch.object(consolidator, '_llm_decide_operation') as mock_decide:
        mock_decide.side_effect = lambda fact, candidates: type('Result', (), {
            'operation': Operation.ADD,
            'new_content': fact,
            'memory_id': None,
            'old_content': None,
            'similarity': 0.0,
            'reason': 'No similar memories found'
        })()

        results = consolidator.consolidate(facts)

    # Verify: 4 facts extracted and stored
    assert len(results) == 4
    assert all(r.operation == Operation.ADD for r in results)
    assert store.count() == 4

    # Search for user preferences
    search_results = store.search("user preferences", top_k=5)
    assert len(search_results) > 0

    # Verify Python preference is stored
    contents = [item.content for item, _ in search_results]
    assert any("Python" in c for c in contents)


# Scenario 2: Preference Update
def test_scenario_preference_update(store, consolidator):
    """Test updating contradictory preferences."""
    # Initial preference
    initial_fact = ExtractedFact(
        content="User prefers dark mode",
        importance=0.7,
        source="llm"
    )

    # Mock initial ADD
    with patch.object(consolidator, '_llm_decide_operation') as mock_decide:
        mock_decide.return_value = type('Result', (), {
            'operation': Operation.ADD,
            'new_content': initial_fact.content,
            'memory_id': None,
            'old_content': None,
            'similarity': 0.0,
            'reason': 'New preference'
        })()
        consolidator.consolidate([initial_fact])

    assert store.count() == 1
    initial_memory = store.search("mode preference", top_k=1)[0][0]

    # Updated preference
    updated_fact = ExtractedFact(
        content="User prefers light mode",
        importance=0.7,
        source="llm"
    )

    # Mock DELETE operation for contradiction
    with patch.object(consolidator, '_llm_decide_operation') as mock_decide:
        mock_decide.return_value = type('Result', (), {
            'operation': Operation.DELETE,
            'memory_id': initial_memory.id,
            'old_content': "User prefers dark mode",
            'new_content': "User prefers light mode",
            'similarity': 0.85,
            'reason': 'Contradicts existing preference'
        })()
        consolidator.consolidate([updated_fact])

    # Verify: old preference deleted, new one added
    assert store.count() == 1
    final_memories = store.search("mode preference", top_k=2)
    assert len(final_memories) == 1
    assert "light mode" in final_memories[0][0].content.lower()
    assert "dark mode" not in final_memories[0][0].content.lower()


# Scenario 3: Long Conversation Compaction
def test_scenario_long_conversation_compaction(compactor):
    """Test compacting a 50+ message conversation."""
    messages = []

    # Early: user info and preferences (messages 0-10)
    messages.extend([
        {"role": "user", "content": "My name is Alice and I work as a data scientist"},
        {"role": "assistant", "content": "Hello Alice!"},
        {"role": "user", "content": "I prefer using pandas for data analysis"},
        {"role": "assistant", "content": "Great choice!"},
    ])

    # Middle: technical discussion (messages 10-40)
    for i in range(15):
        messages.extend([
            {"role": "user", "content": f"Can you help with technical question {i}?"},
            {"role": "assistant", "content": f"Here's the solution for question {i}: detailed technical explanation with code examples."},
        ])

    # Recent: current task (messages 40-60)
    for i in range(10):
        messages.extend([
            {"role": "user", "content": f"Working on current task step {i}"},
            {"role": "assistant", "content": f"For step {i}, you should proceed as follows..."},
        ])

    assert len(messages) == 54  # 4 + 30 + 20 = 54

    # Compact the conversation
    compacted = compactor.compact(messages)

    # Verify: messages reduced, structure preserved
    assert len(compacted) < len(messages)

    # Verify: recall message exists
    assert any(msg.get("role") == "assistant" and "Recalling from earlier" in msg.get("content", "")
               for msg in compacted)

    # Verify: recent messages preserved verbatim
    recent_count = compactor.config.recent_turns_keep * 2
    assert compacted[-recent_count:] == messages[-recent_count:]


# Scenario 4: Multi-Session Memory
def test_scenario_multi_session_memory(temp_dir, mock_embedding):
    """Test memory persistence across sessions."""
    # Session 1: Store project info
    with VectorMemoryStore(Path("test.db"), base_dir=temp_dir, embedding_service=mock_embedding) as store1:
        store1.add("Project uses FastAPI framework", metadata={"importance": 0.8})
        store1.add("Database is PostgreSQL", metadata={"importance": 0.8})
        store1.add("Deploy to AWS Lambda", metadata={"importance": 0.7})
        assert store1.count() == 3

    # Session 2: Query retrieves project context
    with VectorMemoryStore(Path("test.db"), base_dir=temp_dir, embedding_service=mock_embedding) as store2:
        results = store2.search("project tech stack", top_k=5)

        assert len(results) > 0
        contents = [item.content for item, _ in results]

        # Verify cross-session persistence
        assert any("FastAPI" in c for c in contents)
        assert any("PostgreSQL" in c for c in contents)


# Scenario 5: Memory Deduplication
def test_scenario_memory_deduplication(store, consolidator):
    """Test that repeated facts result in NOOP operations."""
    fact_content = "User works at Google in Mountain View"

    # First mention: ADD
    fact1 = ExtractedFact(content=fact_content, importance=0.8, source="llm")

    with patch.object(consolidator, '_llm_decide_operation') as mock_decide:
        mock_decide.return_value = type('Result', (), {
            'operation': Operation.ADD,
            'new_content': fact_content,
            'memory_id': None,
            'old_content': None,
            'similarity': 0.0,
            'reason': 'New information'
        })()
        consolidator.consolidate([fact1])

    assert store.count() == 1
    memory_id = store.search(fact_content, top_k=1)[0][0].id

    # Second mention: NOOP (duplicate)
    fact2 = ExtractedFact(content=fact_content, importance=0.8, source="llm")

    with patch.object(consolidator, '_llm_decide_operation') as mock_decide:
        mock_decide.return_value = type('Result', (), {
            'operation': Operation.NOOP,
            'new_content': fact_content,
            'memory_id': memory_id,
            'old_content': fact_content,
            'similarity': 0.95,
            'reason': 'Already captured'
        })()
        results = consolidator.consolidate([fact2])

    # Verify: Still only 1 memory, no duplicates
    assert store.count() == 1
    assert results[0].operation == Operation.NOOP


# Scenario 6: Namespace Isolation (Multi-tenant)
def test_scenario_namespace_isolation(temp_dir, mock_embedding):
    """Test that different namespaces are isolated."""
    store = VectorMemoryStore(Path("test.db"), base_dir=temp_dir, embedding_service=mock_embedding)

    # Channel A: User A preferences
    store.add("User A prefers vim", metadata={"importance": 0.7}, namespace="channel_a")
    store.add("User A works in Tokyo", metadata={"importance": 0.8}, namespace="channel_a")

    # Channel B: User B preferences
    store.add("User B prefers emacs", metadata={"importance": 0.7}, namespace="channel_b")
    store.add("User B works in London", metadata={"importance": 0.8}, namespace="channel_b")

    # Verify counts per namespace
    assert store.count(namespace="channel_a") == 2
    assert store.count(namespace="channel_b") == 2

    # Query in Channel A: should not return Channel B data
    results_a = store.search("editor preference", namespace="channel_a", top_k=5)
    contents_a = [item.content for item, _ in results_a]

    assert any("vim" in c for c in contents_a)
    assert not any("emacs" in c for c in contents_a)

    # Query in Channel B: should not return Channel A data
    results_b = store.search("editor preference", namespace="channel_b", top_k=5)
    contents_b = [item.content for item, _ in results_b]

    assert any("emacs" in c for c in contents_b)
    assert not any("vim" in c for c in contents_b)


# Scenario 7: Graceful Degradation
def test_scenario_graceful_degradation(extractor):
    """Test that heuristic extraction kicks in when LLM fails."""
    conversation = [
        {"role": "user", "content": "My name is Bob"},
        {"role": "assistant", "content": "Hi Bob!"},
        {"role": "user", "content": "I work at Microsoft"},
        {"role": "assistant", "content": "Great!"},
        {"role": "user", "content": "I prefer using TypeScript"},
        {"role": "assistant", "content": "Good choice!"},
    ]

    # Mock LLM failure
    with patch.object(extractor, '_llm_extract', side_effect=Exception("API error")):
        facts = extractor.extract(conversation, max_facts=5)

    # Verify: heuristic extraction still works
    assert len(facts) > 0
    assert all(f.source == "heuristic" for f in facts)

    # Check that basic facts are captured
    contents = [f.content.lower() for f in facts]
    assert any("bob" in c for c in contents)
    assert any("microsoft" in c for c in contents)


# Additional E2E test: Full pipeline integration
def test_scenario_full_pipeline_integration(store, extractor, consolidator, compactor):
    """Test complete pipeline: conversation → extraction → consolidation → compaction."""
    # Stage 1: Multi-turn conversation
    conversation = [
        {"role": "user", "content": "Hi, I'm Sarah, a frontend developer"},
        {"role": "assistant", "content": "Hello Sarah!"},
        {"role": "user", "content": "I work at Stripe in San Francisco"},
        {"role": "assistant", "content": "Nice!"},
        {"role": "user", "content": "I prefer React over Vue"},
        {"role": "assistant", "content": "React is popular!"},
    ]

    # Stage 2: Extract facts
    mock_facts = [
        ExtractedFact(content="User's name is Sarah", importance=0.9, source="llm"),
        ExtractedFact(content="User is a frontend developer", importance=0.8, source="llm"),
        ExtractedFact(content="User works at Stripe in San Francisco", importance=0.8, source="llm"),
        ExtractedFact(content="User prefers React over Vue", importance=0.7, source="llm"),
    ]

    with patch.object(extractor, 'extract', return_value=mock_facts):
        facts = extractor.extract(conversation)

    # Stage 3: Consolidate into memory
    with patch.object(consolidator, '_llm_decide_operation') as mock_decide:
        mock_decide.side_effect = lambda fact, candidates: type('Result', (), {
            'operation': Operation.ADD,
            'new_content': fact,
            'memory_id': None,
            'old_content': None,
            'similarity': 0.0,
            'reason': 'New information'
        })()
        consolidator.consolidate(facts)

    # Verify memory storage
    assert store.count() == 4

    # Stage 4: Add more conversation turns for compaction
    extended_conversation = conversation.copy()
    for i in range(30):
        extended_conversation.extend([
            {"role": "user", "content": f"Question {i}?"},
            {"role": "assistant", "content": f"Answer {i}"},
        ])

    # Stage 5: Compact conversation
    compacted = compactor.compact(extended_conversation)

    # Verify: compaction worked
    assert len(compacted) < len(extended_conversation)

    # Stage 6: Retrieve memories during new session
    search_results = store.search("Sarah's job and preferences", top_k=5)
    assert len(search_results) > 0

    contents = [item.content for item, _ in search_results]
    assert any("Sarah" in c for c in contents)
    assert any("frontend developer" in c or "Stripe" in c for c in contents)


def test_scenario_importance_based_pruning(temp_dir, mock_embedding):
    """Test that low-priority memories are pruned when limit is reached."""
    store = VectorMemoryStore(Path("test.db"), base_dir=temp_dir, embedding_service=mock_embedding, max_memories=5)

    # Add 3 high-importance memories
    store.add("Critical: API key rotation required", metadata={"importance": 0.9})
    store.add("Critical: Database migration planned", metadata={"importance": 0.9})
    store.add("Important: User prefers dark mode", metadata={"importance": 0.8})

    # Add 3 low-importance memories
    store.add("User said hello", metadata={"importance": 0.3})
    store.add("User asked about weather", metadata={"importance": 0.3})
    store.add("User likes coffee", metadata={"importance": 0.4})

    # Verify: only 5 memories kept, lowest priority pruned
    assert store.count() <= 5

    # Verify: high-importance memories are retained
    all_memories = store.search("", top_k=10, threshold=0.0)
    contents = [item.content for item, _ in all_memories]

    assert any("API key rotation" in c for c in contents)
    assert any("Database migration" in c for c in contents)


def test_scenario_update_with_merge(store, consolidator):
    """Test UPDATE operation that merges old and new information."""
    # Initial fact
    initial = ExtractedFact(
        content="User works at Google",
        importance=0.8,
        source="llm"
    )

    with patch.object(consolidator, '_llm_decide_operation') as mock_decide:
        mock_decide.return_value = type('Result', (), {
            'operation': Operation.ADD,
            'new_content': initial.content,
            'memory_id': None,
            'old_content': None,
            'similarity': 0.0,
            'reason': 'New information'
        })()
        consolidator.consolidate([initial])

    memory_id = store.search("Google", top_k=1)[0][0].id

    # Additional context to merge
    updated = ExtractedFact(
        content="User works at Google as Senior Engineer",
        importance=0.8,
        source="llm"
    )

    with patch.object(consolidator, '_llm_decide_operation') as mock_decide:
        mock_decide.return_value = type('Result', (), {
            'operation': Operation.UPDATE,
            'memory_id': memory_id,
            'old_content': "User works at Google",
            'new_content': "User works at Google as Senior Engineer",
            'similarity': 0.75,
            'reason': 'Adding job title to existing employment fact'
        })()
        consolidator.consolidate([updated])

    # Verify: updated with merged content
    final_memory = store.get(memory_id)
    assert final_memory is not None
    assert "Senior Engineer" in final_memory.content
    assert store.count() == 1  # Still just one memory
