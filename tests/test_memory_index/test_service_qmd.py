"""Integration tests for IndexService QMD backend routing."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot.config.schema import MemoryIndexConfig
from nanobot.memory_index.search import SearchResult


def _make_results(n):
    return [
        SearchResult(text=f"chunk {i}", source="MEMORY.md", start_line=i, end_line=i + 5, score=0.9 - i * 0.1)
        for i in range(n)
    ]


def _make_cfg(backend="sqlite", qmd_binary="qmd", **kwargs):
    cfg = MemoryIndexConfig(**kwargs)
    cfg.backend = backend
    cfg.qmd_binary = qmd_binary
    return cfg


# --- backend=sqlite (default) ---

async def test_sqlite_backend_delegates_to_index_search(tmp_path):
    from nanobot.memory_index.service import IndexService

    cfg = _make_cfg(backend="sqlite")
    with patch("nanobot.memory_index.index.MemoryIndex.__init__", return_value=None):
        svc = IndexService.__new__(IndexService)
        svc._cfg = cfg
        svc._observer = None
        svc._qmd = None
        mock_index = MagicMock()
        mock_index.search = AsyncMock(return_value=_make_results(3))
        svc.index = mock_index

        result = await svc.search("test query", top_k=3)

    mock_index.search.assert_called_once_with("test query", top_k=3)
    assert len(result) == 3


# --- backend=qmd, binary absent → fallback ---

async def test_qmd_backend_falls_back_to_sqlite_when_binary_absent(tmp_path):
    from nanobot.memory_index.qmd import QMDSearcher
    from nanobot.memory_index.service import IndexService

    cfg = _make_cfg(backend="qmd", qmd_binary="qmd-missing")

    with patch("shutil.which", return_value=None):
        svc = IndexService.__new__(IndexService)
        svc._cfg = cfg
        svc._observer = None
        svc._qmd = QMDSearcher("qmd-missing")
        mock_index = MagicMock()
        mock_index.search = AsyncMock(return_value=_make_results(3))
        svc.index = mock_index

        result = await svc.search("test query", top_k=3)

    # Falls back: calls index.search with original top_k (not candidate_k)
    mock_index.search.assert_called_once_with("test query", top_k=3)
    assert len(result) == 3


# --- backend=qmd, binary present → QMD reranking ---

async def test_qmd_backend_calls_rerank_with_larger_candidate_pool(tmp_path):
    from nanobot.memory_index.qmd import QMDSearcher
    from nanobot.memory_index.service import IndexService

    cfg = _make_cfg(backend="qmd", qmd_binary="qmd")
    candidates = _make_results(9)  # candidate_k = min(3*3, 30) = 9
    reranked = candidates[:3]

    with patch("shutil.which", return_value="/usr/local/bin/qmd"):
        svc = IndexService.__new__(IndexService)
        svc._cfg = cfg
        svc._observer = None
        mock_index = MagicMock()
        mock_index.search = AsyncMock(return_value=candidates)
        svc.index = mock_index
        mock_qmd = MagicMock(spec=QMDSearcher)
        mock_qmd.is_available.return_value = True
        mock_qmd.rerank = AsyncMock(return_value=reranked)
        svc._qmd = mock_qmd

        result = await svc.search("test query", top_k=3)

    # SQLite called with candidate_k = min(3*3, 30) = 9
    mock_index.search.assert_called_once_with("test query", top_k=9)
    mock_qmd.rerank.assert_called_once_with("test query", candidates, top_k=3)
    assert result is reranked


# --- IndexService.__init__ constructs QMDSearcher when backend=qmd ---

def test_index_service_init_creates_qmd_searcher_when_backend_qmd(tmp_path):
    from nanobot.memory_index.qmd import QMDSearcher
    from nanobot.memory_index.service import IndexService

    cfg = _make_cfg(backend="qmd", qmd_binary="qmd")
    with patch("nanobot.memory_index.index.MemoryIndex.__init__", return_value=None):
        svc = IndexService(tmp_path, cfg)

    assert isinstance(svc._qmd, QMDSearcher)


def test_index_service_init_no_qmd_when_backend_sqlite(tmp_path):
    from nanobot.memory_index.service import IndexService

    cfg = _make_cfg(backend="sqlite")
    with patch("nanobot.memory_index.index.MemoryIndex.__init__", return_value=None):
        svc = IndexService(tmp_path, cfg)

    assert svc._qmd is None
