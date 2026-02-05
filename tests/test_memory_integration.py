"""Integration tests for memory system component interactions."""

import json
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from nanobot.agent.memory.consolidator import (
    ConsolidationResult,
    MemoryConsolidator,
    Operation,
)
from nanobot.agent.memory.extractor import ExtractedFact, MemoryExtractor
from nanobot.agent.memory.store import EmbeddingService, VectorMemoryStore
from nanobot.session.compaction import CompactionConfig, SessionCompactor


@pytest.fixture
def temp_db():
    """Create a temporary database for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_memory.db"
        yield db_path


@pytest.fixture
def embedding_service():
    """Mock embedding service for testing."""
    service = Mock(spec=EmbeddingService)
    service.dimension = 1536

    # Consistent embeddings based on content with better distribution
    def mock_embed(text):
        # Create more distinctive embeddings based on key terms
        text_lower = text.lower()
        base = [0.1] * 1536

        # Generate pseudo-random but consistent pattern from text
        hash_val = abs(hash(text)) % 10000

        # Set different dimensions based on content keywords
        if "alice" in text_lower or "name" in text_lower:
            base[0:10] = [0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2, 0.1, 0.05]
        elif "data scientist" in text_lower or "work" in text_lower or "job" in text_lower:
            base[10:20] = [0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2, 0.1, 0.05]
        elif "mountain" in text_lower or "hiking" in text_lower or "climbing" in text_lower:
            base[20:30] = [0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2, 0.1, 0.05]
        elif "python" in text_lower or "programming" in text_lower:
            base[30:40] = [0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2, 0.1, 0.05]
        elif "javascript" in text_lower:
            base[40:50] = [0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2, 0.1, 0.05]
        else:
            # Use hash for generic content
            for i in range(10):
                base[i] = ((hash_val * (i + 1)) % 1000) / 1000.0

        return base

    service.embed.side_effect = mock_embed
    return service


@pytest.fixture
def memory_store(temp_db, embedding_service):
    """Create a memory store for testing."""
    # Use base_dir for absolute paths
    base_dir = temp_db.parent
    db_name = temp_db.name
    store = VectorMemoryStore(
        db_path=Path(db_name),
        base_dir=base_dir,
        embedding_service=embedding_service,
        namespace="default"
    )
    yield store
    store.close()


@pytest.fixture
def mock_llm_response():
    """Mock LLM response factory."""
    def _create_response(content):
        response = Mock()
        response.choices = [Mock()]
        response.choices[0].message.content = content
        return response
    return _create_response


class TestExtractorConsolidatorStorePipeline:
    """Test the full extraction → consolidation → storage pipeline."""

    def test_end_to_end_fact_lifecycle(self, memory_store, mock_llm_response):
        """Test complete lifecycle: extract → consolidate → store → retrieve."""
        # Setup messages
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
            {"role": "user", "content": "My name is Alice"},
            {"role": "assistant", "content": "Nice to meet you, Alice!"},
            {"role": "user", "content": "I work as a data scientist"},
            {"role": "assistant", "content": "That's interesting!"},
        ]

        # Mock LLM extraction
        extraction_response = json.dumps([
            {"fact": "User's name is Alice", "importance": "high"},
            {"fact": "User works as a data scientist", "importance": "medium"}
        ])

        # Mock LLM consolidation - ADD operations
        # Note: For ADD operations with no similar memories, LLM is not called
        # The consolidator returns ADD directly when no similar memories found

        with patch('litellm.completion') as mock_completion:
            # First call: extraction
            mock_completion.return_value = mock_llm_response(extraction_response)

            # Extract facts
            extractor = MemoryExtractor()
            facts = extractor.extract(messages, max_facts=5)

            assert len(facts) == 2
            assert facts[0].content == "User's name is Alice"
            assert facts[1].content == "User works as a data scientist"

            # Consolidate into store
            # No need to mock consolidation - it will ADD directly since no similar memories
            consolidator = MemoryConsolidator(memory_store)
            results = consolidator.consolidate(facts)

            assert len(results) == 2
            assert all(r.operation == Operation.ADD for r in results)

        # Verify storage
        assert memory_store.count() == 2

        # Retrieve and verify - use keywords that match embedding patterns
        alice_results = memory_store.search("user name Alice", top_k=1)
        assert len(alice_results) == 1
        assert "Alice" in alice_results[0][0].content

        job_results = memory_store.search("user work data scientist job", top_k=1)
        assert len(job_results) == 1
        assert "data scientist" in job_results[0][0].content

    def test_update_existing_memory(self, memory_store, mock_llm_response):
        """Test updating an existing memory through consolidation."""
        # Add initial memory
        initial = memory_store.add("User lives in New York")

        # New fact that should update
        new_fact = ExtractedFact(
            content="User lives in San Francisco",
            importance=0.8,
            source="llm"
        )

        # Mock LLM decision - UPDATE operation
        update_response = json.dumps({
            "operation": "UPDATE",
            "memory_id": initial.id,
            "content": "User lives in San Francisco (moved from New York)",
            "reason": "Location updated"
        })

        with patch('litellm.completion') as mock_completion:
            mock_completion.return_value = mock_llm_response(update_response)

            consolidator = MemoryConsolidator(memory_store)
            results = consolidator.consolidate([new_fact])

            assert len(results) == 1
            assert results[0].operation == Operation.UPDATE
            assert results[0].memory_id == initial.id

        # Verify update
        updated = memory_store.get(initial.id)
        assert updated is not None
        assert "San Francisco" in updated.content
        assert memory_store.count() == 1  # Still only one memory

    def test_delete_contradicting_memory(self, memory_store, mock_llm_response):
        """Test deleting a contradicting memory and adding new one."""
        # Add initial memory
        initial = memory_store.add("User prefers Python")

        # Contradicting fact
        new_fact = ExtractedFact(
            content="User prefers JavaScript",
            importance=0.9,
            source="llm"
        )

        # Mock LLM decision - DELETE operation
        delete_response = json.dumps({
            "operation": "DELETE",
            "memory_id": initial.id,
            "content": "User prefers JavaScript",
            "reason": "Preference changed"
        })

        with patch('litellm.completion') as mock_completion:
            mock_completion.return_value = mock_llm_response(delete_response)

            consolidator = MemoryConsolidator(memory_store)
            results = consolidator.consolidate([new_fact])

            assert len(results) == 1
            assert results[0].operation == Operation.DELETE

        # Verify deletion and new addition
        assert memory_store.get(initial.id) is None
        results = memory_store.search("programming language", top_k=1)
        assert len(results) == 1
        assert "JavaScript" in results[0][0].content


class TestCompactionExtractorIntegration:
    """Test compaction and extractor integration."""

    def test_compaction_uses_extract_facts(self):
        """Verify compaction uses extract_facts_from_messages correctly."""
        # Create messages with extractable facts
        messages = [
            {"role": "user", "content": "My name is Bob"},
            {"role": "assistant", "content": "Hello Bob!"},
            {"role": "user", "content": "I prefer using Python"},
            {"role": "assistant", "content": "Great choice!"},
        ]

        # Add filler messages to trigger compaction
        for i in range(50):
            messages.extend([
                {"role": "user", "content": f"Question {i}?"},
                {"role": "assistant", "content": f"Answer {i}"}
            ])

        config = CompactionConfig(threshold=50, recent_turns_keep=4)
        compactor = SessionCompactor(config)

        compacted = compactor.compact(messages)

        # Should have recall message + recent messages
        assert len(compacted) < len(messages)
        assert compacted[0]["role"] == "assistant"
        assert "[Recalling from earlier in our conversation]" in compacted[0]["content"]

        # Facts should be extracted
        recall_content = compacted[0]["content"]
        assert "name" in recall_content.lower() or "bob" in recall_content.lower()

    def test_extracted_facts_match_patterns(self):
        """Verify extracted facts match expected patterns."""
        messages = [
            {"role": "user", "content": "My email is test@example.com"},
            {"role": "assistant", "content": "Got it!"},
            {"role": "user", "content": "I work at OpenAI"},
            {"role": "assistant", "content": "Interesting!"},
            {"role": "user", "content": "Important: project uses TypeScript"},
            {"role": "assistant", "content": "Noted!"},
        ]

        from nanobot.agent.memory.extractor import extract_facts_from_messages

        facts = extract_facts_from_messages(messages, max_facts=10)

        assert len(facts) > 0
        # Check that keyword-triggered facts are captured
        fact_text = " ".join(facts).lower()
        assert "email" in fact_text or "work" in fact_text or "important" in fact_text


class TestStoreSearchRetrieval:
    """Test store search and retrieval functionality."""

    def test_similarity_ordering(self, memory_store):
        """Verify search results are ordered by similarity."""
        memory_store.add("User enjoys hiking in mountains")
        memory_store.add("User likes reading science fiction")
        memory_store.add("User loves mountain climbing")

        results = memory_store.search("mountain activities", top_k=3)

        assert len(results) >= 2
        # Results with "mountain" should rank higher
        top_result = results[0][0]
        assert "mountain" in top_result.content.lower()

    def test_priority_weighting_effect(self, memory_store):
        """Verify priority weighting affects ranking."""
        # Add low-priority memory with exact match
        low_priority = memory_store.add(
            "Python programming language",
            metadata={"importance": 0.1}
        )

        # Add high-priority memory with partial match
        high_priority = memory_store.add(
            "User prefers Python",
            metadata={"importance": 0.9}
        )

        # Search with high priority weight
        results = memory_store.search(
            "Python",
            top_k=2,
            priority_weight=0.7  # Heavy priority weighting
        )

        assert len(results) == 2
        # High priority item should rank higher due to weighting
        assert results[0][0].priority > results[1][0].priority

    def test_threshold_filtering(self, memory_store):
        """Verify threshold filters low-similarity results."""
        memory_store.add("User enjoys hiking")
        memory_store.add("User likes programming")

        # High threshold should return fewer results
        results_high = memory_store.search(
            "outdoor activities",
            top_k=10,
            threshold=0.8
        )

        results_low = memory_store.search(
            "outdoor activities",
            top_k=10,
            threshold=0.3
        )

        assert len(results_low) >= len(results_high)


class TestNamespaceIsolation:
    """Test namespace isolation functionality."""

    def test_cross_namespace_isolation(self, temp_db, embedding_service):
        """Verify memories are isolated across namespaces."""
        base_dir = temp_db.parent
        db_name = temp_db.name
        store1 = VectorMemoryStore(
            db_path=Path(db_name),
            base_dir=base_dir,
            embedding_service=embedding_service,
            namespace="project_a"
        )
        store2 = VectorMemoryStore(
            db_path=Path(db_name),
            base_dir=base_dir,
            embedding_service=embedding_service,
            namespace="project_b"
        )

        try:
            # Add to different namespaces
            store1.add("Project A uses Python")
            store2.add("Project B uses JavaScript")

            # Search should only return namespace-specific results
            results_a = store1.search("programming language", namespace="project_a")
            results_b = store2.search("programming language", namespace="project_b")

            assert len(results_a) == 1
            assert len(results_b) == 1
            assert "Python" in results_a[0][0].content
            assert "JavaScript" in results_b[0][0].content

            # Verify counts are namespace-specific
            assert store1.count(namespace="project_a") == 1
            assert store2.count(namespace="project_b") == 1

        finally:
            store1.close()
            store2.close()

    def test_namespace_search_no_cross_contamination(self, temp_db, embedding_service):
        """Verify search never returns results from other namespaces."""
        base_dir = temp_db.parent
        db_name = temp_db.name
        store = VectorMemoryStore(
            db_path=Path(db_name),
            base_dir=base_dir,
            embedding_service=embedding_service,
            namespace="default"
        )

        try:
            # Add to multiple namespaces
            store.add("Default namespace content", namespace="default")
            store.add("Alpha namespace content", namespace="alpha")
            store.add("Beta namespace content", namespace="beta")

            # Search default namespace
            results = store.search("namespace", namespace="default", top_k=10)

            # Should only get default namespace result
            assert len(results) == 1
            assert results[0][0].namespace == "default"
            assert "Default" in results[0][0].content

        finally:
            store.close()


class TestMemoryLifecycle:
    """Test complete memory lifecycle operations."""

    def test_add_update_delete_cycle(self, memory_store):
        """Test ADD → UPDATE → DELETE lifecycle."""
        # ADD
        memory = memory_store.add("User's favorite color is blue")
        original_id = memory.id
        assert memory_store.count() == 1

        # UPDATE
        updated = memory_store.update(
            original_id,
            "User's favorite color is green (changed from blue)"
        )
        assert updated is not None
        assert updated.id == original_id
        assert "green" in updated.content
        assert memory_store.count() == 1  # Count unchanged

        # Verify embedding was regenerated
        assert updated.embedding is not None
        assert updated.embedding != memory.embedding

        # DELETE
        deleted = memory_store.delete(original_id)
        assert deleted is True
        assert memory_store.count() == 0
        assert memory_store.get(original_id) is None

    def test_final_state_after_operations(self, memory_store, mock_llm_response):
        """Verify final state after multiple operations."""
        # Initial state
        mem1 = memory_store.add("Initial fact 1")
        mem2 = memory_store.add("Initial fact 2")

        assert memory_store.count() == 2

        # Apply operations through consolidator
        facts = [
            ExtractedFact("Updated fact 1", importance=0.8, source="llm"),
            ExtractedFact("New fact 3", importance=0.7, source="llm"),
        ]

        with patch('litellm.completion') as mock_completion:
            mock_completion.side_effect = [
                # UPDATE first fact
                mock_llm_response(json.dumps({
                    "operation": "UPDATE",
                    "memory_id": mem1.id,
                    "content": "Updated fact 1 (merged)",
                    "reason": "Update"
                })),
                # ADD new fact
                mock_llm_response(json.dumps({
                    "operation": "ADD",
                    "content": "New fact 3",
                    "reason": "New"
                }))
            ]

            consolidator = MemoryConsolidator(memory_store)
            consolidator.consolidate(facts)

        # Final state verification
        assert memory_store.count() == 3

        # mem1 should be updated
        updated_mem1 = memory_store.get(mem1.id)
        assert "Updated" in updated_mem1.content

        # mem2 should be unchanged
        unchanged_mem2 = memory_store.get(mem2.id)
        assert unchanged_mem2.content == "Initial fact 2"

        # New memory should exist
        all_results = memory_store.search("fact", top_k=10, threshold=0.0)
        assert len(all_results) == 3


class TestSessionCompactionIntegration:
    """Test session compaction with memory system."""

    def test_large_history_compaction(self):
        """Test compaction of large message history."""
        messages = []

        # Add old messages with facts
        messages.extend([
            {"role": "user", "content": "My name is Charlie"},
            {"role": "assistant", "content": "Hi Charlie!"},
            {"role": "user", "content": "I work at Microsoft"},
            {"role": "assistant", "content": "Great!"},
        ])

        # Add middle section - need more to exceed threshold
        for i in range(30):
            messages.extend([
                {"role": "user", "content": f"What about topic {i}?"},
                {"role": "assistant", "content": f"Here's info on topic {i}"}
            ])

        # Add recent messages
        messages.extend([
            {"role": "user", "content": "What's my name again?"},
            {"role": "assistant", "content": "Your name is Charlie!"},
        ])

        config = CompactionConfig(
            threshold=50,
            recent_turns_keep=4,
            summary_max_turns=10
        )
        compactor = SessionCompactor(config)

        compacted = compactor.compact(messages)

        # Should compact since len(messages) > threshold
        assert len(compacted) < len(messages)
        assert len(compacted) > config.recent_turns_keep * 2

    def test_recent_messages_retained_verbatim(self):
        """Verify recent messages are kept verbatim."""
        messages = []

        # Add many old messages
        for i in range(40):
            messages.append({"role": "user", "content": f"Old message {i}"})
            messages.append({"role": "assistant", "content": f"Old response {i}"})

        # Add recent distinct messages
        recent_messages = [
            {"role": "user", "content": "Recent question 1?"},
            {"role": "assistant", "content": "Recent answer 1"},
            {"role": "user", "content": "Recent question 2?"},
            {"role": "assistant", "content": "Recent answer 2"},
        ]
        messages.extend(recent_messages)

        config = CompactionConfig(threshold=50, recent_turns_keep=2)
        compactor = SessionCompactor(config)

        compacted = compactor.compact(messages)

        # Last 4 messages should be exactly the recent ones
        assert compacted[-4:] == recent_messages

    def test_middle_section_summarized(self):
        """Verify middle section is summarized, not verbatim."""
        messages = []

        # Old section
        for i in range(15):
            messages.extend([
                {"role": "user", "content": f"Old {i}"},
                {"role": "assistant", "content": f"Response {i}"}
            ])

        # Middle section with questions
        middle_start = len(messages)
        for i in range(10):
            messages.extend([
                {"role": "user", "content": f"What is the answer to question {i}?"},
                {"role": "assistant", "content": f"The answer to question {i} is complex. It involves multiple factors."}
            ])
        middle_end = len(messages)

        # Recent section
        for i in range(4):
            messages.extend([
                {"role": "user", "content": f"Recent {i}"},
                {"role": "assistant", "content": f"Recent response {i}"}
            ])

        config = CompactionConfig(
            threshold=50,
            recent_turns_keep=4,
            summary_max_turns=10
        )
        compactor = SessionCompactor(config)

        compacted = compactor.compact(messages)

        # Middle messages should not appear verbatim
        middle_messages = messages[middle_start:middle_end]
        for middle_msg in middle_messages:
            # None of the middle messages should appear exactly in compacted
            assert middle_msg not in compacted[1:-8]  # Exclude recall and recent


class TestErrorPropagation:
    """Test error handling and graceful degradation."""

    def test_llm_failure_heuristic_fallback(self, memory_store):
        """Test that LLM failure falls back to heuristic extraction."""
        messages = [
            {"role": "user", "content": "My name is Dave"},
            {"role": "assistant", "content": "Hello!"},
            {"role": "user", "content": "I live in Seattle"},
            {"role": "assistant", "content": "Nice!"},
            {"role": "user", "content": "I work as an engineer"},
            {"role": "assistant", "content": "Great!"},
        ]

        with patch('litellm.completion') as mock_completion:
            # Simulate LLM failure
            mock_completion.side_effect = Exception("LLM API error")

            extractor = MemoryExtractor()
            facts = extractor.extract(messages, max_facts=5)

            # Should still extract facts using heuristics
            assert len(facts) > 0
            assert all(f.source == "heuristic" for f in facts)

            # Verify facts contain expected content (case-insensitive)
            fact_content = " ".join(f.content for f in facts).lower()
            assert "dave" in fact_content or "seattle" in fact_content

    def test_consolidation_continues_after_llm_error(self, memory_store, mock_llm_response):
        """Test that consolidation continues even if LLM decision fails."""
        facts = [
            ExtractedFact("Fact 1", importance=0.8, source="llm"),
            ExtractedFact("Fact 2", importance=0.7, source="llm"),
        ]

        with patch('litellm.completion') as mock_completion:
            # First call fails, second succeeds
            mock_completion.side_effect = [
                Exception("LLM error"),
                mock_llm_response(json.dumps({
                    "operation": "ADD",
                    "content": "Fact 2",
                    "reason": "New"
                }))
            ]

            consolidator = MemoryConsolidator(memory_store)
            results = consolidator.consolidate(facts)

            # Both facts should be processed
            assert len(results) == 2
            # First should fallback to ADD due to error
            assert results[0].operation == Operation.ADD

        # Verify both were stored
        assert memory_store.count() == 2

    def test_store_functionality_after_embedding_failure(self, temp_db):
        """Test that basic store operations work even with embedding issues."""
        # Create store with failing embedding service
        failing_service = Mock(spec=EmbeddingService)
        failing_service.dimension = 1536
        failing_service.embed.side_effect = Exception("Embedding API down")

        base_dir = temp_db.parent
        db_name = temp_db.name
        store = VectorMemoryStore(
            db_path=Path(db_name),
            base_dir=base_dir,
            embedding_service=failing_service,
            namespace="default"
        )

        try:
            # add() should fail
            with pytest.raises(Exception):
                store.add("Test content")

            # But we can still do operations that don't need embeddings
            # (This is informational - in real scenario, would need pre-existing data)
            assert store.count() == 0

        finally:
            store.close()

    def test_invalid_importance_handled_gracefully(self, memory_store, mock_llm_response):
        """Test that invalid importance values are normalized."""
        facts = [
            ExtractedFact("Fact with NaN", importance=float('nan'), source="llm"),
            ExtractedFact("Fact with infinity", importance=float('inf'), source="llm"),
            ExtractedFact("Fact with negative", importance=-5.0, source="llm"),
            ExtractedFact("Fact with too high", importance=100.0, source="llm"),
        ]

        with patch('litellm.completion') as mock_completion:
            mock_completion.side_effect = [
                mock_llm_response(json.dumps({"operation": "ADD", "content": f"Fact {i}", "reason": "New"}))
                for i in range(4)
            ]

            consolidator = MemoryConsolidator(memory_store)
            results = consolidator.consolidate(facts)

            assert len(results) == 4

            # All should be added despite invalid importance values
            assert all(r.operation == Operation.ADD for r in results)

        # Verify all stored with normalized priorities
        assert memory_store.count() == 4

        # Check that priorities are in valid range [0, 1]
        all_memories = memory_store.search("Fact", top_k=10, threshold=0.0)
        for memory, _ in all_memories:
            assert 0.0 <= memory.priority <= 1.0


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_empty_fact_content_skipped(self, memory_store, mock_llm_response):
        """Test that empty or whitespace-only facts are skipped."""
        facts = [
            ExtractedFact("", importance=0.8, source="llm"),
            ExtractedFact("   ", importance=0.8, source="llm"),
            ExtractedFact("Valid fact", importance=0.8, source="llm"),
        ]

        with patch('litellm.completion') as mock_completion:
            mock_completion.return_value = mock_llm_response(json.dumps({
                "operation": "ADD",
                "content": "Valid fact",
                "reason": "New"
            }))

            consolidator = MemoryConsolidator(memory_store)
            results = consolidator.consolidate(facts)

            # Only valid fact should be processed
            assert len(results) == 1
            assert results[0].new_content == "Valid fact"

    def test_very_similar_memories_deduplicated(self, memory_store, mock_llm_response):
        """Test that very similar facts are marked as NOOP."""
        # Add existing memory
        memory_store.add("User's favorite color is blue")

        # Try to add nearly identical fact
        fact = ExtractedFact(
            "User's favorite color is blue",
            importance=0.8,
            source="llm"
        )

        with patch('litellm.completion') as mock_completion:
            mock_completion.return_value = mock_llm_response(json.dumps({
                "operation": "NOOP",
                "reason": "Already captured"
            }))

            consolidator = MemoryConsolidator(memory_store)
            results = consolidator.consolidate([fact])

            assert len(results) == 1
            assert results[0].operation == Operation.NOOP

        # Count should remain 1
        assert memory_store.count() == 1

    def test_namespace_validation_enforced(self, temp_db, embedding_service):
        """Test that invalid namespaces are rejected."""
        base_dir = temp_db.parent
        db_name = temp_db.name
        store = VectorMemoryStore(
            db_path=Path(db_name),
            base_dir=base_dir,
            embedding_service=embedding_service,
            namespace="default"
        )

        try:
            # Invalid namespace characters
            with pytest.raises(ValueError, match="Invalid namespace"):
                store.add("Test", namespace="invalid namespace!")

            # Too long namespace
            with pytest.raises(ValueError, match="Invalid namespace"):
                store.add("Test", namespace="a" * 100)

            # Special characters
            with pytest.raises(ValueError, match="Invalid namespace"):
                store.add("Test", namespace="test@namespace")

        finally:
            store.close()


# Run with: pytest tests/test_memory_integration.py -v
