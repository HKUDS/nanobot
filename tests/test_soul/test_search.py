"""Tests for nanobot.soul.search module."""

import pytest
from pathlib import Path

from nanobot.soul.search import (
    tokenize,
    cosine_similarity,
    bm25_score,
    MemorySearchIndex,
    SEARCH_MAX_RESULTS,
    SEARCH_MIN_SCORE,
)
from collections import Counter


class TestTokenize:
    """Tests for tokenize function."""

    def test_english_tokens(self):
        tokens = tokenize("Hello World test")
        assert "hello" in tokens
        assert "world" in tokens
        assert "test" in tokens

    def test_filters_short_tokens(self):
        tokens = tokenize("I am a big dog")
        # Single-char English tokens should be filtered (len > 1 required)
        assert "i" not in tokens
        assert "a" not in tokens
        assert "am" in tokens
        assert "big" in tokens
        assert "dog" in tokens

    def test_chinese_chars_kept(self):
        tokens = tokenize("我是中国人")
        # Consecutive Chinese chars form a single token
        assert "我是中国人" in tokens

    def test_mixed_content(self):
        tokens = tokenize("Hello 世界 test123")
        assert "hello" in tokens
        assert "世界" in tokens
        assert "test123" in tokens

    def test_empty_string(self):
        assert tokenize("") == []

    def test_special_chars_only(self):
        assert tokenize("!@#$%^&*()") == []

    def test_lowercase(self):
        tokens = tokenize("ABC DEF")
        assert "abc" in tokens
        assert "def" in tokens


class TestCosineSimilarity:
    """Tests for cosine_similarity function."""

    def test_identical_vectors(self):
        vec = {"a": 1.0, "b": 2.0}
        sim = cosine_similarity(vec, vec)
        assert abs(sim - 1.0) < 1e-6

    def test_orthogonal_vectors(self):
        a = {"x": 1.0}
        b = {"y": 1.0}
        assert cosine_similarity(a, b) == 0.0

    def test_empty_vectors(self):
        assert cosine_similarity({}, {"a": 1.0}) == 0.0
        assert cosine_similarity({}, {}) == 0.0

    def test_partial_overlap(self):
        a = {"x": 1.0, "y": 1.0}
        b = {"y": 1.0, "z": 1.0}
        sim = cosine_similarity(a, b)
        assert 0.0 < sim < 1.0


class TestBM25Score:
    """Tests for bm25_score function."""

    def test_matching_terms(self):
        query = ["python", "programming"]
        doc = ["python", "programming", "language", "code"]
        doc_freq = Counter({"python": 2, "programming": 1, "language": 3, "code": 5})
        score = bm25_score(query, doc, doc_freq, n_docs=10)
        assert score > 0.0

    def test_no_matching_terms(self):
        query = ["java"]
        doc = ["python", "programming"]
        doc_freq = Counter({"python": 1, "programming": 1})
        score = bm25_score(query, doc, doc_freq, n_docs=10)
        assert score == 0.0

    def test_empty_query(self):
        score = bm25_score([], ["python"], Counter({"python": 1}), n_docs=10)
        assert score == 0.0

    def test_empty_doc(self):
        score = bm25_score(["python"], [], Counter(), n_docs=10)
        assert score == 0.0


class TestMemorySearchIndex:
    """Tests for MemorySearchIndex."""

    @pytest.fixture
    def ws_with_memory(self, tmp_path):
        """Create workspace with memory files."""
        ws_dir = tmp_path / "agent"
        ws_dir.mkdir()
        mem_dir = ws_dir / "memory"
        mem_dir.mkdir()

        # Long-term memory
        (ws_dir / "MEMORY.md").write_text(
            "# Long-term Memory\n\n"
            "## User Preferences\n\n"
            "User prefers Python over JavaScript.\n"
            "User's name is Alice.\n\n"
            "## Project Notes\n\n"
            "Working on a chatbot project using DeepSeek API.\n"
            "Database is PostgreSQL.\n",
            encoding="utf-8",
        )

        # Daily log
        (mem_dir / "2026-03-14.md").write_text(
            "# Memory Log: 2026-03-14\n\n"
            "## [10:30:00] decision\n\n"
            "Decided to use Redis for caching.\n\n"
            "## [14:00:00] fact\n\n"
            "Deployment scheduled for Friday.\n",
            encoding="utf-8",
        )

        return ws_dir

    def test_collect_files(self, ws_with_memory):
        idx = MemorySearchIndex(ws_with_memory)
        files = idx._collect_files()
        assert len(files) == 2  # MEMORY.md + daily log

    def test_chunk_file(self, ws_with_memory):
        idx = MemorySearchIndex(ws_with_memory)
        chunks = idx._chunk_file(ws_with_memory / "MEMORY.md")
        assert len(chunks) >= 2  # At least 2 heading-based chunks
        assert all(c["path"] == "MEMORY.md" for c in chunks)

    def test_build_index(self, ws_with_memory):
        idx = MemorySearchIndex(ws_with_memory)
        chunks = idx.build_index()
        assert len(chunks) > 0
        paths = {c["path"] for c in chunks}
        assert "MEMORY.md" in paths

    def test_search_finds_relevant(self, ws_with_memory):
        idx = MemorySearchIndex(ws_with_memory)
        results = idx.search("Python preference")
        assert len(results) > 0
        # The chunk about Python should score highest
        assert "Python" in results[0]["snippet"]

    def test_search_finds_daily(self, ws_with_memory):
        idx = MemorySearchIndex(ws_with_memory)
        results = idx.search("Redis caching")
        assert len(results) > 0
        top = results[0]
        assert "Redis" in top["snippet"]

    def test_search_empty_query(self, ws_with_memory):
        idx = MemorySearchIndex(ws_with_memory)
        results = idx.search("")
        assert results == []

    def test_search_no_results(self, ws_with_memory):
        idx = MemorySearchIndex(ws_with_memory)
        results = idx.search("quantum physics relativity", min_score=0.9)
        assert results == []

    def test_search_max_results(self, ws_with_memory):
        idx = MemorySearchIndex(ws_with_memory)
        results = idx.search("memory", max_results=1)
        assert len(results) <= 1

    def test_search_citation_format(self, ws_with_memory):
        idx = MemorySearchIndex(ws_with_memory)
        results = idx.search("Alice")
        assert len(results) > 0
        for r in results:
            assert "citation" in r
            assert "#L" in r["citation"]

    def test_search_empty_workspace(self, tmp_path):
        ws_dir = tmp_path / "empty"
        ws_dir.mkdir()
        (ws_dir / "memory").mkdir()
        idx = MemorySearchIndex(ws_dir)
        results = idx.search("anything")
        assert results == []

    def test_search_score_range(self, ws_with_memory):
        idx = MemorySearchIndex(ws_with_memory)
        results = idx.search("Python", min_score=0.0)
        for r in results:
            assert 0.0 <= r["score"] <= 1.5  # Hybrid score can exceed 1.0 slightly
