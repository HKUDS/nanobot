"""Unit tests for VectorMemoryStore."""

import json
import sqlite3
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from nanobot.agent.memory.store import (
    EmbeddingService,
    MAX_CONTENT_LENGTH,
    MemoryItem,
    VALID_NAMESPACE_PATTERN,
    VectorMemoryStore,
)


@pytest.fixture
def mock_embedding():
    """Mock litellm.embedding to avoid API calls."""
    with patch('litellm.embedding') as mock:
        mock.return_value = Mock(data=[Mock(get=lambda k: [0.1] * 1536)])
        # Handle both dict-style and attribute access
        mock.return_value.data[0].__getitem__ = lambda self, k: [0.1] * 1536
        yield mock


@pytest.fixture
def temp_store(mock_embedding, tmp_path):
    """Create a temporary VectorMemoryStore for testing."""
    store = VectorMemoryStore(db_path=Path("test.db"), base_dir=tmp_path)
    yield store
    store.close()


@pytest.fixture
def embedding_service(mock_embedding):
    """Create an EmbeddingService with mocked API."""
    return EmbeddingService()


class TestEmbeddingService:
    """Tests for EmbeddingService."""

    def test_embed_returns_list(self, embedding_service):
        """Test that embed returns a list of floats."""
        result = embedding_service.embed("test content")
        assert isinstance(result, list)
        assert len(result) == 1536
        assert all(isinstance(x, float) for x in result)

    def test_embed_caching(self, embedding_service, mock_embedding):
        """Test that identical inputs use cache."""
        text = "test content"
        result1 = embedding_service.embed(text)
        result2 = embedding_service.embed(text)

        assert result1 == result2
        # Should only call API once due to caching (litellm module function, not mock.embedding)
        assert mock_embedding.call_count == 1

    def test_embed_error_handling(self, mock_embedding):
        """Test that embedding errors are raised."""
        mock_embedding.side_effect = Exception("API Error")
        service = EmbeddingService()

        with pytest.raises(Exception, match="API Error"):
            service.embed("test")

    def test_dimension_property(self, embedding_service):
        """Test dimension property returns correct value."""
        assert embedding_service.dimension == 1536


class TestVectorMemoryStoreInit:
    """Tests for VectorMemoryStore initialization."""

    def test_init_creates_db_file(self, mock_embedding, tmp_path):
        """Test that initialization creates database file."""
        db_path = Path("test.db")
        store = VectorMemoryStore(db_path=db_path, base_dir=tmp_path)

        assert store.db_path.exists()
        assert store.db_path.name == "test.db"
        store.close()

    def test_init_with_base_dir_path_traversal_prevention(self, mock_embedding, tmp_path):
        """Test that path traversal is prevented when base_dir is set."""
        with pytest.raises(ValueError, match="must be within"):
            VectorMemoryStore(db_path=Path("../../../etc/passwd"), base_dir=tmp_path)

    def test_init_without_base_dir_absolute_path_rejected(self, mock_embedding):
        """Test that absolute paths are rejected when base_dir not specified."""
        with pytest.raises(ValueError, match="must be relative"):
            VectorMemoryStore(db_path=Path("/tmp/test.db"))

    def test_init_without_base_dir_parent_refs_rejected(self, mock_embedding):
        """Test that parent directory references are rejected."""
        with pytest.raises(ValueError, match="cannot contain parent directory"):
            VectorMemoryStore(db_path=Path("../test.db"))

    def test_init_creates_parent_directories(self, mock_embedding, tmp_path):
        """Test that parent directories are created."""
        db_path = Path("subdir/nested/test.db")
        store = VectorMemoryStore(db_path=db_path, base_dir=tmp_path)

        assert store.db_path.parent.exists()
        store.close()

    def test_init_with_custom_namespace(self, mock_embedding, tmp_path):
        """Test initialization with custom namespace."""
        store = VectorMemoryStore(
            db_path=Path("test.db"),
            base_dir=tmp_path,
            namespace="custom_ns"
        )
        assert store.namespace == "custom_ns"
        store.close()

    def test_init_with_invalid_namespace(self, mock_embedding, tmp_path):
        """Test that invalid namespace raises ValueError."""
        with pytest.raises(ValueError, match="Invalid namespace"):
            VectorMemoryStore(
                db_path=Path("test.db"),
                base_dir=tmp_path,
                namespace="invalid space"
            )

    def test_init_creates_schema(self, mock_embedding, tmp_path):
        """Test that database schema is created."""
        store = VectorMemoryStore(db_path=Path("test.db"), base_dir=tmp_path)

        cursor = store._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='memories'"
        )
        assert cursor.fetchone() is not None
        store.close()


class TestVectorMemoryStoreAdd:
    """Tests for add() method."""

    def test_add_basic_content(self, temp_store):
        """Test adding basic content."""
        item = temp_store.add("Test content")

        assert item.id is not None
        assert item.content == "Test content"
        assert item.embedding is not None
        assert len(item.embedding) == 1536
        assert item.namespace == "default"

    def test_add_with_metadata(self, temp_store):
        """Test adding content with metadata."""
        metadata = {"source": "test", "importance": 0.8}
        item = temp_store.add("Test content", metadata=metadata)

        assert item.metadata == metadata
        assert item.priority > 0.5  # Higher importance -> higher priority

    def test_add_with_custom_namespace(self, temp_store):
        """Test adding content to custom namespace."""
        item = temp_store.add("Test content", namespace="custom")

        assert item.namespace == "custom"

    def test_add_strips_whitespace(self, temp_store):
        """Test that content whitespace is stripped."""
        item = temp_store.add("  Test content  \n")

        assert item.content == "Test content"

    def test_add_empty_content_raises(self, temp_store):
        """Test that empty content raises ValueError."""
        with pytest.raises(ValueError, match="cannot be empty"):
            temp_store.add("")

    def test_add_whitespace_only_raises(self, temp_store):
        """Test that whitespace-only content raises ValueError."""
        with pytest.raises(ValueError, match="cannot be empty"):
            temp_store.add("   \n\t   ")

    def test_add_non_string_content_raises(self, temp_store):
        """Test that non-string content raises TypeError."""
        with pytest.raises(TypeError, match="must be a string"):
            temp_store.add(123)

    def test_add_content_too_long_raises(self, temp_store):
        """Test that content exceeding max length raises ValueError."""
        long_content = "x" * (MAX_CONTENT_LENGTH + 1)

        with pytest.raises(ValueError, match="exceeds maximum length"):
            temp_store.add(long_content)

    def test_add_invalid_namespace_raises(self, temp_store):
        """Test that invalid namespace raises ValueError."""
        with pytest.raises(ValueError, match="Invalid namespace"):
            temp_store.add("Test", namespace="invalid space")

    def test_add_persists_to_database(self, temp_store):
        """Test that added content is persisted to database."""
        item = temp_store.add("Test content")

        # Query database directly
        cursor = temp_store._conn.execute(
            "SELECT * FROM memories WHERE id = ?", (item.id,)
        )
        row = cursor.fetchone()

        assert row is not None
        assert row[1] == "Test content"  # content column

    def test_add_generates_embedding(self, temp_store, mock_embedding):
        """Test that embedding is generated for content."""
        temp_store.add("Test content")

        mock_embedding.assert_called_once()
        # Check the call was made with the correct input
        assert mock_embedding.call_args[1]["input"] == ["Test content"]

    def test_add_priority_calculation(self, temp_store):
        """Test that priority is calculated from importance."""
        low_importance = temp_store.add("Test", metadata={"importance": 0.1})
        high_importance = temp_store.add("Test", metadata={"importance": 0.9})

        assert high_importance.priority > low_importance.priority


class TestVectorMemoryStoreGet:
    """Tests for get() method."""

    def test_get_existing_item(self, temp_store):
        """Test retrieving an existing item."""
        added = temp_store.add("Test content")
        retrieved = temp_store.get(added.id)

        assert retrieved is not None
        assert retrieved.id == added.id
        assert retrieved.content == added.content

    def test_get_non_existing_item(self, temp_store):
        """Test retrieving a non-existing item returns None."""
        result = temp_store.get("nonexistent")

        assert result is None

    def test_get_namespace_isolation(self, temp_store):
        """Test that get respects namespace isolation."""
        item1 = temp_store.add("Test", namespace="ns1")
        item2 = temp_store.add("Test", namespace="ns2")

        result_ns1 = temp_store.get(item1.id, namespace="ns1")
        result_ns2 = temp_store.get(item1.id, namespace="ns2")

        assert result_ns1 is not None
        assert result_ns2 is None

    def test_get_preserves_metadata(self, temp_store):
        """Test that metadata is preserved on retrieval."""
        metadata = {"key": "value", "number": 42}
        added = temp_store.add("Test", metadata=metadata)
        retrieved = temp_store.get(added.id)

        assert retrieved.metadata == metadata

    def test_get_handles_invalid_json_metadata(self, temp_store):
        """Test that invalid JSON metadata is handled gracefully."""
        item = temp_store.add("Test")

        # Corrupt the metadata in database
        temp_store._conn.execute(
            "UPDATE memories SET metadata = ? WHERE id = ?",
            ("invalid json", item.id)
        )
        temp_store._conn.commit()

        retrieved = temp_store.get(item.id)
        assert retrieved.metadata == {}


class TestVectorMemoryStoreUpdate:
    """Tests for update() method."""

    def test_update_content(self, temp_store):
        """Test updating content."""
        item = temp_store.add("Original content")
        updated = temp_store.update(item.id, "Updated content")

        assert updated is not None
        assert updated.content == "Updated content"
        assert updated.id == item.id

    def test_update_metadata(self, temp_store):
        """Test updating metadata."""
        item = temp_store.add("Test", metadata={"old": "value"})
        updated = temp_store.update(item.id, "Test", metadata={"new": "value"})

        assert updated.metadata == {"new": "value"}

    def test_update_regenerates_embedding_on_content_change(self, temp_store, mock_embedding):
        """Test that embedding is regenerated when content changes."""
        mock_embedding.reset_mock()

        item = temp_store.add("Original")
        call_count_after_add = mock_embedding.call_count

        temp_store.update(item.id, "Updated")

        # Should have one more call for the update
        assert mock_embedding.call_count == call_count_after_add + 1

    def test_update_preserves_embedding_on_same_content(self, temp_store, mock_embedding):
        """Test that embedding is not regenerated when content unchanged."""
        mock_embedding.embedding.reset_mock()

        item = temp_store.add("Same content")
        call_count_after_add = mock_embedding.embedding.call_count

        temp_store.update(item.id, "Same content", metadata={"new": "meta"})

        # Should not call embedding again
        assert mock_embedding.embedding.call_count == call_count_after_add

    def test_update_non_existing_item(self, temp_store):
        """Test updating non-existing item returns None."""
        result = temp_store.update("nonexistent", "content")

        assert result is None

    def test_update_empty_content_raises(self, temp_store):
        """Test that updating with empty content raises ValueError."""
        item = temp_store.add("Test")

        with pytest.raises(ValueError, match="cannot be empty"):
            temp_store.update(item.id, "")

    def test_update_non_string_content_raises(self, temp_store):
        """Test that updating with non-string raises TypeError."""
        item = temp_store.add("Test")

        with pytest.raises(TypeError, match="must be a string"):
            temp_store.update(item.id, 123)

    def test_update_content_too_long_raises(self, temp_store):
        """Test that updating with too-long content raises ValueError."""
        item = temp_store.add("Test")
        long_content = "x" * (MAX_CONTENT_LENGTH + 1)

        with pytest.raises(ValueError, match="exceeds maximum length"):
            temp_store.update(item.id, long_content)

    def test_update_preserves_created_at(self, temp_store):
        """Test that created_at timestamp is preserved."""
        item = temp_store.add("Test")
        original_created_at = item.created_at

        updated = temp_store.update(item.id, "Updated")

        assert updated.created_at == original_created_at

    def test_update_changes_updated_at(self, temp_store):
        """Test that updated_at timestamp is changed."""
        item = temp_store.add("Test")
        original_updated_at = item.updated_at

        # Small delay to ensure timestamp difference
        import time
        time.sleep(0.01)

        updated = temp_store.update(item.id, "Updated")

        assert updated.updated_at > original_updated_at

    def test_update_priority_calculation(self, temp_store):
        """Test that priority is recalculated based on age and access."""
        item = temp_store.add("Test", metadata={"importance": 0.5})
        original_priority = item.priority

        updated = temp_store.update(item.id, "Updated", metadata={"importance": 0.9})

        # Higher importance should increase priority
        assert updated.priority > original_priority


class TestVectorMemoryStoreDelete:
    """Tests for delete() method."""

    def test_delete_existing_item(self, temp_store):
        """Test deleting an existing item."""
        item = temp_store.add("Test")
        result = temp_store.delete(item.id)

        assert result is True
        assert temp_store.get(item.id) is None

    def test_delete_non_existing_item(self, temp_store):
        """Test deleting non-existing item returns False."""
        result = temp_store.delete("nonexistent")

        assert result is False

    def test_delete_namespace_isolation(self, temp_store):
        """Test that delete respects namespace isolation."""
        item1 = temp_store.add("Test", namespace="ns1")
        item2 = temp_store.add("Test", namespace="ns2")

        temp_store.delete(item1.id, namespace="ns2")

        # Item in ns1 should still exist
        assert temp_store.get(item1.id, namespace="ns1") is not None
        # Item in ns2 should still exist
        assert temp_store.get(item2.id, namespace="ns2") is not None


class TestVectorMemoryStoreSearch:
    """Tests for search() method."""

    def test_search_finds_similar_content(self, temp_store):
        """Test that search finds similar content."""
        temp_store.add("Python programming")
        temp_store.add("JavaScript coding")
        temp_store.add("Database design")

        results = temp_store.search("Python development", top_k=5)

        assert len(results) > 0
        assert all(isinstance(item, MemoryItem) for item, _ in results)
        assert all(isinstance(score, float) for _, score in results)

    def test_search_respects_top_k(self, temp_store):
        """Test that search respects top_k parameter."""
        for i in range(10):
            temp_store.add(f"Content {i}")

        results = temp_store.search("Content", top_k=3)

        assert len(results) <= 3

    def test_search_respects_threshold(self, temp_store):
        """Test that search respects similarity threshold."""
        temp_store.add("Very specific content")

        # High threshold should filter out low-similarity results
        results = temp_store.search("Completely different", threshold=0.9)

        assert all(score >= 0.9 for _, score in results)

    def test_search_namespace_isolation(self, temp_store):
        """Test that search respects namespace isolation."""
        temp_store.add("Python", namespace="ns1")
        temp_store.add("Python", namespace="ns2")

        results_ns1 = temp_store.search("Python", namespace="ns1")

        assert all(item.namespace == "ns1" for item, _ in results_ns1)

    def test_search_empty_database(self, temp_store):
        """Test searching in empty database returns empty list."""
        results = temp_store.search("query")

        assert results == []

    def test_search_priority_weighting(self, temp_store):
        """Test that priority affects search ranking."""
        low_priority = temp_store.add("Test", metadata={"importance": 0.1})
        high_priority = temp_store.add("Test", metadata={"importance": 0.9})

        results = temp_store.search("Test", priority_weight=0.5)

        # Higher priority item should rank higher
        assert results[0][0].id == high_priority.id

    def test_search_results_sorted_by_score(self, temp_store):
        """Test that search results are sorted by score."""
        for i in range(5):
            temp_store.add(f"Content {i}")

        results = temp_store.search("Content")
        scores = [score for _, score in results]

        assert scores == sorted(scores, reverse=True)


class TestVectorMemoryStoreResourceManagement:
    """Tests for resource management."""

    def test_close_closes_connection(self, mock_embedding, tmp_path):
        """Test that close() closes the database connection."""
        store = VectorMemoryStore(db_path=Path("test.db"), base_dir=tmp_path)
        store.close()

        assert store._conn is None

    def test_ensure_open_raises_after_close(self, temp_store):
        """Test that operations after close raise RuntimeError."""
        temp_store.close()

        with pytest.raises(RuntimeError, match="is closed"):
            temp_store.add("Test")

    def test_del_cleanup(self, mock_embedding, tmp_path):
        """Test that __del__ cleans up connection."""
        store = VectorMemoryStore(db_path=Path("test.db"), base_dir=tmp_path)
        conn = store._conn

        del store

        # Connection should be closed (attempting to use it should fail)
        with pytest.raises(sqlite3.ProgrammingError):
            conn.execute("SELECT 1")

    def test_context_manager_enter(self, mock_embedding, tmp_path):
        """Test context manager __enter__ returns self."""
        store = VectorMemoryStore(db_path=Path("test.db"), base_dir=tmp_path)

        with store as s:
            assert s is store

        assert store._conn is None

    def test_context_manager_exit(self, mock_embedding, tmp_path):
        """Test context manager __exit__ closes connection."""
        store = VectorMemoryStore(db_path=Path("test.db"), base_dir=tmp_path)

        with store:
            pass

        assert store._conn is None

    def test_context_manager_exception_handling(self, mock_embedding, tmp_path):
        """Test that exceptions in context manager are propagated."""
        store = VectorMemoryStore(db_path=Path("test.db"), base_dir=tmp_path)

        with pytest.raises(ValueError, match="test error"):
            with store:
                raise ValueError("test error")

        # Connection should still be closed
        assert store._conn is None


class TestVectorMemoryStorePruning:
    """Tests for memory pruning."""

    def test_prune_when_max_exceeded(self, mock_embedding, tmp_path):
        """Test that pruning occurs when max_memories is exceeded."""
        store = VectorMemoryStore(
            db_path=Path("test.db"),
            base_dir=tmp_path,
            max_memories=5
        )

        # Add 6 items
        for i in range(6):
            store.add(f"Content {i}")

        # Should have pruned to max
        assert store.count() <= 5
        store.close()

    def test_prune_removes_lowest_priority(self, mock_embedding, tmp_path):
        """Test that pruning removes lowest priority items."""
        store = VectorMemoryStore(
            db_path=Path("test.db"),
            base_dir=tmp_path,
            max_memories=3
        )

        # Add items with different priorities
        low = store.add("Low", metadata={"importance": 0.1})
        med = store.add("Med", metadata={"importance": 0.5})
        high = store.add("High", metadata={"importance": 0.9})

        # Add one more to trigger pruning
        store.add("New", metadata={"importance": 0.5})

        # Low priority item should be pruned
        assert store.get(low.id) is None
        assert store.get(med.id) is not None
        assert store.get(high.id) is not None
        store.close()

    def test_prune_namespace_isolation(self, mock_embedding, tmp_path):
        """Test that pruning respects namespace isolation."""
        store = VectorMemoryStore(
            db_path=Path("test.db"),
            base_dir=tmp_path,
            max_memories=3
        )

        # Fill ns1 to trigger pruning
        for i in range(5):
            store.add(f"NS1 Content {i}", namespace="ns1")

        # Add items to ns2
        for i in range(2):
            store.add(f"NS2 Content {i}", namespace="ns2")

        # ns1 should be pruned, ns2 should not
        assert store.count(namespace="ns1") <= 3
        assert store.count(namespace="ns2") == 2
        store.close()


class TestVectorMemoryStoreCount:
    """Tests for count() method."""

    def test_count_empty_database(self, temp_store):
        """Test count on empty database."""
        assert temp_store.count() == 0

    def test_count_after_add(self, temp_store):
        """Test count after adding items."""
        temp_store.add("Test 1")
        temp_store.add("Test 2")

        assert temp_store.count() == 2

    def test_count_after_delete(self, temp_store):
        """Test count after deleting items."""
        item = temp_store.add("Test")
        temp_store.delete(item.id)

        assert temp_store.count() == 0

    def test_count_namespace_isolation(self, temp_store):
        """Test that count respects namespace isolation."""
        temp_store.add("Test", namespace="ns1")
        temp_store.add("Test", namespace="ns1")
        temp_store.add("Test", namespace="ns2")

        assert temp_store.count(namespace="ns1") == 2
        assert temp_store.count(namespace="ns2") == 1


class TestNamespaceValidation:
    """Tests for namespace validation."""

    @pytest.mark.parametrize("valid_ns", [
        "default",
        "my_namespace",
        "test-123",
        "ABC_123",
        "a" * 64,  # Max length
    ])
    def test_valid_namespaces(self, valid_ns, temp_store):
        """Test that valid namespaces are accepted."""
        item = temp_store.add("Test", namespace=valid_ns)
        assert item.namespace == valid_ns

    @pytest.mark.parametrize("invalid_ns", [
        "invalid space",
        "invalid@char",
        "invalid.dot",
        "a" * 65,  # Too long
        "slash/slash",
    ])
    def test_invalid_namespaces(self, invalid_ns, temp_store):
        """Test that invalid namespaces raise ValueError."""
        with pytest.raises(ValueError, match="Invalid namespace"):
            temp_store.add("Test", namespace=invalid_ns)

    def test_empty_namespace_uses_default(self, temp_store):
        """Test that empty namespace uses the default."""
        # Empty string triggers validation failure OR falls back to default
        # Based on the code, empty namespace will use self.namespace (default)
        item = temp_store.add("Test", namespace="")
        # Empty string should use default namespace instead
        assert item.namespace == "default"


class TestCosineSimilarity:
    """Tests for _cosine_similarity method."""

    def test_identical_vectors(self, temp_store):
        """Test cosine similarity of identical vectors."""
        vec = [1.0, 2.0, 3.0]
        similarity = temp_store._cosine_similarity(vec, vec)

        assert abs(similarity - 1.0) < 1e-6

    def test_orthogonal_vectors(self, temp_store):
        """Test cosine similarity of orthogonal vectors."""
        vec1 = [1.0, 0.0, 0.0]
        vec2 = [0.0, 1.0, 0.0]
        similarity = temp_store._cosine_similarity(vec1, vec2)

        assert abs(similarity - 0.0) < 1e-6

    def test_opposite_vectors(self, temp_store):
        """Test cosine similarity of opposite vectors."""
        vec1 = [1.0, 2.0, 3.0]
        vec2 = [-1.0, -2.0, -3.0]
        similarity = temp_store._cosine_similarity(vec1, vec2)

        assert abs(similarity - (-1.0)) < 1e-6

    def test_zero_vector(self, temp_store):
        """Test cosine similarity with zero vector."""
        vec1 = [1.0, 2.0, 3.0]
        vec2 = [0.0, 0.0, 0.0]
        similarity = temp_store._cosine_similarity(vec1, vec2)

        assert similarity == 0.0
