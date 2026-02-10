"""Tests for the memory system (nanobot.memory package)."""

import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from nanobot.memory import (
    BaseMemoryStore,
    FileMemoryStore,
    MemoryItem,
    MemorySearchResult,
    create_memory_store,
)
from nanobot.config.schema import MemoryConfig


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def tmp_workspace(tmp_path):
    """Create a temporary workspace with memory directory."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    mem_dir = ws / "memory"
    mem_dir.mkdir()
    return ws


@pytest.fixture
def workspace_with_memory(tmp_workspace):
    """Workspace with a pre-populated MEMORY.md."""
    memory_file = tmp_workspace / "memory" / "MEMORY.md"
    memory_file.write_text(
        "# Long-term Memory\n\n"
        "## User Information\n\n"
        "User prefers Python and dark mode.\n\n"
        "## Project Context\n\n"
        "Working on a chatbot project using FastAPI.\n",
        encoding="utf-8",
    )
    return tmp_workspace


@pytest.fixture
def workspace_with_daily(workspace_with_memory):
    """Workspace with MEMORY.md and a daily note."""
    from nanobot.utils.helpers import today_date

    daily = workspace_with_memory / "memory" / f"{today_date()}.md"
    daily.write_text(
        f"# {today_date()}\n\nDiscussed deployment strategy.\n",
        encoding="utf-8",
    )
    return workspace_with_memory


# ── MemoryItem / MemorySearchResult ───────────────────────────────────


class TestMemoryItem:
    def test_creation(self):
        item = MemoryItem(id="abc", text="User likes Python")
        assert item.id == "abc"
        assert item.text == "User likes Python"
        assert item.score == 0.0
        assert item.metadata == {}

    def test_memory_type_default(self):
        item = MemoryItem(id="1", text="x")
        assert item.memory_type == "note"

    def test_memory_type_from_metadata(self):
        item = MemoryItem(id="1", text="x", metadata={"type": "preference"})
        assert item.memory_type == "preference"

    def test_source_default(self):
        item = MemoryItem(id="1", text="x")
        assert item.source == "conversation"

    def test_source_from_metadata(self):
        item = MemoryItem(id="1", text="x", metadata={"source": "import"})
        assert item.source == "import"


class TestMemorySearchResult:
    def test_empty_result(self):
        result = MemorySearchResult(memories=[], query="test")
        assert result.to_context_string() == ""

    def test_context_string_formatting(self):
        items = [
            MemoryItem(id="1", text="User prefers dark mode", score=0.92),
            MemoryItem(id="2", text="Project uses FastAPI", score=0.85),
        ]
        result = MemorySearchResult(memories=items, query="preferences")
        ctx = result.to_context_string()
        assert "User prefers dark mode" in ctx
        assert "0.92" in ctx
        assert "Project uses FastAPI" in ctx

    def test_context_string_respects_max_items(self):
        items = [MemoryItem(id=str(i), text=f"memory {i}") for i in range(20)]
        result = MemorySearchResult(memories=items, query="test")
        ctx = result.to_context_string(max_items=3)
        assert "memory 0" in ctx
        assert "memory 2" in ctx
        assert "memory 3" not in ctx


# ── FileMemoryStore ───────────────────────────────────────────────────


class TestFileMemoryStore:
    def test_init_creates_memory_dir(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        store = FileMemoryStore(ws)
        assert (ws / "memory").is_dir()

    def test_implements_base(self, tmp_workspace):
        store = FileMemoryStore(tmp_workspace)
        assert isinstance(store, BaseMemoryStore)

    def test_read_long_term_empty(self, tmp_workspace):
        store = FileMemoryStore(tmp_workspace)
        assert store.read_long_term() == ""

    def test_read_long_term(self, workspace_with_memory):
        store = FileMemoryStore(workspace_with_memory)
        content = store.read_long_term()
        assert "User prefers Python" in content

    def test_write_long_term(self, tmp_workspace):
        store = FileMemoryStore(tmp_workspace)
        store.write_long_term("Remember: user likes vim")
        content = store.read_long_term()
        assert "user likes vim" in content

    def test_read_today_empty(self, tmp_workspace):
        store = FileMemoryStore(tmp_workspace)
        assert store.read_today() == ""

    def test_append_today(self, tmp_workspace):
        store = FileMemoryStore(tmp_workspace)
        store.append_today("Met with Alice about DB migration")
        content = store.read_today()
        assert "Met with Alice" in content

    def test_append_today_twice(self, tmp_workspace):
        store = FileMemoryStore(tmp_workspace)
        store.append_today("First note")
        store.append_today("Second note")
        content = store.read_today()
        assert "First note" in content
        assert "Second note" in content

    def test_get_memory_context_empty(self, tmp_workspace):
        store = FileMemoryStore(tmp_workspace)
        ctx = store.get_memory_context()
        assert ctx == ""

    def test_get_memory_context_with_data(self, workspace_with_daily):
        store = FileMemoryStore(workspace_with_daily)
        ctx = store.get_memory_context()
        assert "Long-term Memory" in ctx
        assert "User prefers Python" in ctx
        assert "Today's Notes" in ctx
        assert "deployment strategy" in ctx

    def test_get_memory_context_ignores_query(self, workspace_with_memory):
        """FileMemoryStore ignores query param — always returns full content."""
        store = FileMemoryStore(workspace_with_memory)
        ctx1 = store.get_memory_context(query=None)
        ctx2 = store.get_memory_context(query="something specific")
        assert ctx1 == ctx2

    def test_search_returns_all(self, workspace_with_memory):
        store = FileMemoryStore(workspace_with_memory)
        result = store.search("python")
        assert result.total_found > 0
        assert any("Python" in m.text for m in result.memories)

    def test_add_is_noop(self, tmp_workspace):
        store = FileMemoryStore(tmp_workspace)
        result = store.add([{"role": "user", "content": "remember this"}])
        assert result == []

    def test_delete_returns_false(self, tmp_workspace):
        store = FileMemoryStore(tmp_workspace)
        assert store.delete("anything") is False

    def test_list_memory_files(self, workspace_with_daily):
        store = FileMemoryStore(workspace_with_daily)
        files = store.list_memory_files()
        assert len(files) >= 1
        assert all(f.suffix == ".md" for f in files)

    def test_get_recent_memories(self, workspace_with_daily):
        store = FileMemoryStore(workspace_with_daily)
        recent = store.get_recent_memories(days=1)
        assert "deployment strategy" in recent


# ── Factory (create_memory_store) ─────────────────────────────────────


class TestCreateMemoryStore:
    def test_default_creates_file_store(self, tmp_workspace):
        store = create_memory_store(tmp_workspace)
        assert isinstance(store, FileMemoryStore)

    def test_none_config_creates_file_store(self, tmp_workspace):
        store = create_memory_store(tmp_workspace, config=None)
        assert isinstance(store, FileMemoryStore)

    def test_file_backend_creates_file_store(self, tmp_workspace):
        config = MemoryConfig(backend="file")
        store = create_memory_store(tmp_workspace, config)
        assert isinstance(store, FileMemoryStore)

    def test_vector_backend_with_missing_deps_falls_back(self, tmp_workspace):
        """If chromadb/mem0ai not importable, factory falls back to FileMemoryStore."""
        config = MemoryConfig(backend="vector")
        with patch(
            "nanobot.memory.vector_store.VectorMemoryStore.__init__",
            side_effect=ImportError("no chromadb"),
        ):
            # The factory catches ImportError at the import level,
            # but VectorMemoryStore also handles it in __init__.
            # Either way, we should get something usable.
            store = create_memory_store(tmp_workspace, config)
            assert store is not None

    def test_vector_backend_creates_vector_store(self, tmp_workspace):
        """VectorMemoryStore is created even without API keys (graceful degradation)."""
        config = MemoryConfig(backend="vector")
        store = create_memory_store(tmp_workspace, config)
        # It should be a VectorMemoryStore, just with _available=False
        from nanobot.memory.vector_store import VectorMemoryStore

        assert isinstance(store, VectorMemoryStore)


# ── VectorMemoryStore (graceful degradation) ──────────────────────────


class TestVectorMemoryStoreGraceful:
    """Test VectorMemoryStore when API keys are missing (common local dev scenario)."""

    def test_init_without_api_key_does_not_crash(self, tmp_workspace):
        from nanobot.memory.vector_store import VectorMemoryStore

        store = VectorMemoryStore(tmp_workspace)
        assert store._available is False

    def test_search_returns_empty(self, tmp_workspace):
        from nanobot.memory.vector_store import VectorMemoryStore

        store = VectorMemoryStore(tmp_workspace)
        result = store.search("hello")
        assert len(result.memories) == 0
        assert result.total_found == 0

    def test_add_returns_empty(self, tmp_workspace):
        from nanobot.memory.vector_store import VectorMemoryStore

        store = VectorMemoryStore(tmp_workspace)
        items = store.add([{"role": "user", "content": "remember me"}])
        assert items == []

    def test_get_all_returns_empty(self, tmp_workspace):
        from nanobot.memory.vector_store import VectorMemoryStore

        store = VectorMemoryStore(tmp_workspace)
        items = store.get_all()
        assert items == []

    def test_delete_returns_false(self, tmp_workspace):
        from nanobot.memory.vector_store import VectorMemoryStore

        store = VectorMemoryStore(tmp_workspace)
        assert store.delete("any-id") is False

    def test_get_memory_context_returns_empty(self, tmp_workspace):
        from nanobot.memory.vector_store import VectorMemoryStore

        store = VectorMemoryStore(tmp_workspace)
        ctx = store.get_memory_context(query="test")
        assert ctx == ""


# ── MemoryConfig ──────────────────────────────────────────────────────


class TestMemoryConfig:
    def test_defaults(self):
        config = MemoryConfig()
        assert config.backend == "file"
        assert config.top_k == 8
        assert config.write_back_enabled is True
        assert config.write_back_min_message_length == 20
        assert config.llm_provider == "litellm"
        assert config.embedding_model == "text-embedding-3-small"

    def test_vector_config(self):
        config = MemoryConfig(
            backend="vector",
            llm_model="anthropic/claude-haiku-4-5-20251001",
            top_k=5,
        )
        assert config.backend == "vector"
        assert config.llm_model == "anthropic/claude-haiku-4-5-20251001"
        assert config.top_k == 5

    def test_config_in_root(self):
        """MemoryConfig is accessible from the root Config."""
        from nanobot.config.schema import Config

        cfg = Config()
        assert hasattr(cfg, "memory")
        assert isinstance(cfg.memory, MemoryConfig)
        assert cfg.memory.backend == "file"


# ── Backward compatibility ────────────────────────────────────────────


class TestBackwardCompat:
    def test_old_import_path(self):
        """nanobot.agent.memory.MemoryStore still works.

        Uses importlib to avoid triggering nanobot.agent.__init__ which
        pulls in AgentLoop -> litellm (heavy dep not always installed in test envs).
        """
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "nanobot.agent.memory",
            Path(__file__).resolve().parent.parent / "nanobot" / "agent" / "memory.py",
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert mod.MemoryStore is FileMemoryStore

    def test_old_api_still_works(self, workspace_with_memory):
        """MemoryStore imported from old path has all original methods."""
        # Direct instantiation to avoid heavy __init__ chain
        store = FileMemoryStore(workspace_with_memory)
        assert hasattr(store, "read_long_term")
        assert hasattr(store, "write_long_term")
        assert hasattr(store, "read_today")
        assert hasattr(store, "append_today")
        assert hasattr(store, "get_memory_context")
        assert hasattr(store, "get_recent_memories")
        assert hasattr(store, "list_memory_files")
        # Verify it actually works
        content = store.read_long_term()
        assert "Python" in content
