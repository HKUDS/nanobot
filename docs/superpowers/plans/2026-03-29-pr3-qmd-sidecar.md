# PR 3: QMD Sidecar Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an optional QMD (query-time model decomposition) backend to the memory index. When `backend = "qmd"` is configured and the `qmd` binary is available, `IndexService.search()` retrieves a larger candidate pool via the existing SQLite pipeline, then passes the candidates to the QMD CLI for LLM re-ranking. Absent binary → silent fallback to the existing SQLite search.

**Architecture:** `QMDSearcher` (new `nanobot/memory_index/qmd.py`) is a thin async subprocess wrapper. `IndexService.__init__` constructs one when `cfg.backend == "qmd"`. `IndexService.search()` becomes backend-aware: if QMD is available, retrieve `min(top_k * 3, 30)` candidates then call `QMDSearcher.rerank()`; otherwise delegate directly to `MemoryIndex.search()` as before. `context.py` and `loop.py` are **not** touched — `IndexService.search()` is the only public entry point.

**Tech Stack:** Python 3.11+, asyncio subprocess (`asyncio.create_subprocess_exec`), `shutil.which` for binary detection. No new dependencies.

---

## File Map

| File | Change |
|---|---|
| `nanobot/config/schema.py` | Add `backend: Literal["sqlite", "qmd"] = "sqlite"` and `qmd_binary: str = "qmd"` to `MemoryIndexConfig` |
| `nanobot/memory_index/qmd.py` | **New** — `QMDSearcher`: `is_available()`, `async rerank()`, subprocess JSON protocol |
| `nanobot/memory_index/service.py` | Construct `QMDSearcher` in `__init__` when backend="qmd"; make `search()` backend-aware |
| `tests/test_memory_index/test_qmd_config.py` | **New** — config field defaults and overrides |
| `tests/test_memory_index/test_qmd.py` | **New** — `QMDSearcher` unit tests (mocked subprocess) |
| `tests/test_memory_index/test_service_qmd.py` | **New** — `IndexService` backend routing integration tests |

---

## QMD Subprocess Protocol

**stdin** (UTF-8 JSON, single line):
```json
{
  "query": "user query text",
  "candidates": [
    {"id": 0, "text": "...", "source": "MEMORY.md", "start_line": 10, "end_line": 20, "score": 0.85},
    {"id": 1, "text": "...", "source": "HISTORY.md", "start_line": 5, "end_line": 15, "score": 0.72}
  ]
}
```

**stdout** (UTF-8 JSON):
```json
{"ranked": [1, 0]}
```
`ranked` is a list of candidate `id` values in best-first order. IDs not present in candidates are ignored. Subprocess timeout: 10 seconds.

---

## Task 1: Config Additions

**Files:**
- Modify: `nanobot/config/schema.py` (around line 166)
- Create: `tests/test_memory_index/test_qmd_config.py`

**Context:** `MemoryIndexConfig` currently has `enabled`, `embedding`, `query`, `inject_top_k`, `watch_files`. Add two more fields with `Literal` type annotation from `typing`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_memory_index/test_qmd_config.py`:
```python
def test_memory_index_config_defaults_backend_sqlite():
    from nanobot.config.schema import MemoryIndexConfig

    cfg = MemoryIndexConfig()
    assert cfg.backend == "sqlite"
    assert cfg.qmd_binary == "qmd"


def test_memory_index_config_backend_can_be_qmd():
    from nanobot.config.schema import MemoryIndexConfig

    cfg = MemoryIndexConfig(backend="qmd")
    assert cfg.backend == "qmd"


def test_memory_index_config_qmd_binary_can_be_custom_path():
    from nanobot.config.schema import MemoryIndexConfig

    cfg = MemoryIndexConfig(backend="qmd", qmd_binary="/usr/local/bin/qmd")
    assert cfg.qmd_binary == "/usr/local/bin/qmd"
```

- [ ] **Step 2: Run tests — verify FAILED**

```bash
pytest tests/test_memory_index/test_qmd_config.py -v
```

Expected: `FAILED` — `MemoryIndexConfig` has no attribute `backend`.

- [ ] **Step 3: Add fields to `MemoryIndexConfig`**

```python
from typing import Literal  # already imported elsewhere; add if not present

class MemoryIndexConfig(Base):
    """Semantic memory index configuration. Off by default."""

    enabled: bool = False
    embedding: MemoryIndexEmbeddingConfig = Field(default_factory=MemoryIndexEmbeddingConfig)
    query: MemoryIndexQueryConfig = Field(default_factory=MemoryIndexQueryConfig)
    inject_top_k: int = 3        # chunks auto-injected per turn; 0 = disabled
    watch_files: bool = True     # enable watchdog file watcher
    backend: Literal["sqlite", "qmd"] = "sqlite"  # search backend
    qmd_binary: str = "qmd"      # path or name resolved via shutil.which
```

- [ ] **Step 4: Run tests — verify PASSED**

```bash
pytest tests/test_memory_index/test_qmd_config.py -v
```

- [ ] **Step 5: Run full suite — verify no regressions**

```bash
pytest --tb=short -q
```

Expected: 652 passed (649 + 3 new), 1 skipped.

- [ ] **Commit**

```
feat(memory_index): add backend + qmd_binary fields to MemoryIndexConfig
```

---

## Task 2: `nanobot/memory_index/qmd.py` — QMDSearcher

**Files:**
- Create: `nanobot/memory_index/qmd.py`
- Create: `tests/test_memory_index/test_qmd.py`

**Context:** `SearchResult` is a dataclass in `nanobot/memory_index/search.py` with fields: `text: str`, `source: str`, `start_line: int`, `end_line: int`, `score: float`. The module must not import anything from `nanobot` at module level (keep it inside functions or `TYPE_CHECKING` guard) — follow the same pattern as `service.py` which guards `from nanobot.config.schema import MemoryIndexConfig` under `TYPE_CHECKING`.

```python
# nanobot/memory_index/qmd.py
"""QMDSearcher — async subprocess wrapper for the QMD re-ranking CLI."""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from nanobot.memory_index.search import SearchResult


class QMDSearcher:
    """Thin async wrapper around an external QMD binary for LLM-based re-ranking.

    Protocol: send JSON to stdin, read ranked IDs from stdout. Falls back
    silently to the original candidate order on any error or if the binary
    is not installed.
    """

    _TIMEOUT = 10.0  # seconds

    def __init__(self, binary: str) -> None:
        self._binary = binary

    def is_available(self) -> bool:
        """Return True if the QMD binary can be found on PATH (or is an absolute path)."""
        import shutil
        return shutil.which(self._binary) is not None

    async def rerank(
        self,
        query: str,
        candidates: list[SearchResult],
        top_k: int,
    ) -> list[SearchResult]:
        """Re-rank candidates via the QMD subprocess; fallback on any failure.

        If the binary is unavailable or the subprocess fails, returns
        candidates[:top_k] unchanged.
        """
        if not candidates:
            return []
        if not self.is_available():
            logger.debug("QMD binary '{}' not found, skipping re-rank", self._binary)
            return candidates[:top_k]

        payload = {
            "query": query,
            "candidates": [
                {
                    "id": i,
                    "text": r.text,
                    "source": r.source,
                    "start_line": r.start_line,
                    "end_line": r.end_line,
                    "score": r.score,
                }
                for i, r in enumerate(candidates)
            ],
        }

        try:
            proc = await asyncio.create_subprocess_exec(
                self._binary,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(
                proc.communicate(json.dumps(payload).encode()),
                timeout=self._TIMEOUT,
            )
            data = json.loads(stdout)
            ranked_ids: list[int] = data["ranked"]
        except Exception:
            logger.warning("QMD reranking failed, falling back to original order")
            return candidates[:top_k]

        id_to_result = dict(enumerate(candidates))
        reranked = [id_to_result[rid] for rid in ranked_ids if rid in id_to_result]
        # Append any candidates not mentioned by QMD (safety net)
        mentioned = set(ranked_ids)
        for i, r in enumerate(candidates):
            if i not in mentioned:
                reranked.append(r)
        return reranked[:top_k]
```

- [ ] **Step 1: Write the failing tests**

Create `tests/test_memory_index/test_qmd.py`:
```python
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot.memory_index.search import SearchResult


def _make_result(text="chunk text", source="MEMORY.md", start=1, end=5, score=0.9):
    return SearchResult(text=text, source=source, start_line=start, end_line=end, score=score)


# --- is_available ---

def test_is_available_returns_false_when_binary_absent():
    from nanobot.memory_index.qmd import QMDSearcher

    with patch("shutil.which", return_value=None):
        searcher = QMDSearcher("qmd")
        assert searcher.is_available() is False


def test_is_available_returns_true_when_binary_present():
    from nanobot.memory_index.qmd import QMDSearcher

    with patch("shutil.which", return_value="/usr/local/bin/qmd"):
        searcher = QMDSearcher("qmd")
        assert searcher.is_available() is True


# --- rerank: fallback paths ---

async def test_rerank_returns_empty_list_for_empty_candidates():
    from nanobot.memory_index.qmd import QMDSearcher

    searcher = QMDSearcher("qmd")
    result = await searcher.rerank("query", [], top_k=3)
    assert result == []


async def test_rerank_returns_candidates_sliced_when_binary_absent():
    from nanobot.memory_index.qmd import QMDSearcher

    candidates = [_make_result(text=f"chunk {i}") for i in range(5)]
    with patch("shutil.which", return_value=None):
        searcher = QMDSearcher("qmd")
        result = await searcher.rerank("query", candidates, top_k=2)
    assert result == candidates[:2]


# --- rerank: happy path ---

async def test_rerank_happy_path_respects_qmd_order():
    from nanobot.memory_index.qmd import QMDSearcher

    c0 = _make_result(text="chunk 0", score=0.9)
    c1 = _make_result(text="chunk 1", score=0.8)
    c2 = _make_result(text="chunk 2", score=0.7)
    candidates = [c0, c1, c2]

    # QMD says: best is c2, then c0 (c1 omitted → appended at end)
    qmd_output = json.dumps({"ranked": [2, 0]}).encode()

    mock_proc = MagicMock()
    mock_proc.communicate = AsyncMock(return_value=(qmd_output, b""))

    with patch("shutil.which", return_value="/usr/local/bin/qmd"), \
         patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        searcher = QMDSearcher("qmd")
        result = await searcher.rerank("query", candidates, top_k=3)

    assert result[0] is c2
    assert result[1] is c0
    assert result[2] is c1  # appended as unmentioned candidate


async def test_rerank_top_k_limits_output():
    from nanobot.memory_index.qmd import QMDSearcher

    candidates = [_make_result(text=f"chunk {i}") for i in range(5)]
    qmd_output = json.dumps({"ranked": [4, 3, 2, 1, 0]}).encode()

    mock_proc = MagicMock()
    mock_proc.communicate = AsyncMock(return_value=(qmd_output, b""))

    with patch("shutil.which", return_value="/usr/local/bin/qmd"), \
         patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        searcher = QMDSearcher("qmd")
        result = await searcher.rerank("query", candidates, top_k=2)

    assert len(result) == 2
    assert result[0] is candidates[4]
    assert result[1] is candidates[3]


# --- rerank: error handling ---

async def test_rerank_falls_back_on_subprocess_exception():
    from nanobot.memory_index.qmd import QMDSearcher

    candidates = [_make_result(text=f"chunk {i}") for i in range(3)]

    with patch("shutil.which", return_value="/usr/local/bin/qmd"), \
         patch("asyncio.create_subprocess_exec", side_effect=OSError("no such file")):
        searcher = QMDSearcher("qmd")
        result = await searcher.rerank("query", candidates, top_k=2)

    assert result == candidates[:2]


async def test_rerank_falls_back_on_invalid_json_response():
    from nanobot.memory_index.qmd import QMDSearcher

    candidates = [_make_result(text=f"chunk {i}") for i in range(3)]
    mock_proc = MagicMock()
    mock_proc.communicate = AsyncMock(return_value=(b"not-valid-json", b""))

    with patch("shutil.which", return_value="/usr/local/bin/qmd"), \
         patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        searcher = QMDSearcher("qmd")
        result = await searcher.rerank("query", candidates, top_k=2)

    assert result == candidates[:2]


async def test_rerank_falls_back_on_timeout():
    from nanobot.memory_index.qmd import QMDSearcher

    candidates = [_make_result(text=f"chunk {i}") for i in range(3)]
    mock_proc = MagicMock()
    mock_proc.communicate = AsyncMock(side_effect=asyncio.TimeoutError())

    with patch("shutil.which", return_value="/usr/local/bin/qmd"), \
         patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        searcher = QMDSearcher("qmd")
        result = await searcher.rerank("query", candidates, top_k=2)

    assert result == candidates[:2]
```

- [ ] **Step 2: Run tests — verify FAILED (module not found)**

```bash
pytest tests/test_memory_index/test_qmd.py -v
```

- [ ] **Step 3: Create `nanobot/memory_index/qmd.py`** (full implementation as shown in Context above)

- [ ] **Step 4: Run tests — verify PASSED**

```bash
pytest tests/test_memory_index/test_qmd.py -v
```

- [ ] **Step 5: Run full suite — verify no regressions**

```bash
pytest --tb=short -q
```

Expected: 663 passed (652 + 9 new), 1 skipped.

- [ ] **Commit**

```
feat(memory_index): add QMDSearcher subprocess wrapper for LLM re-ranking
```

---

## Task 3: Wire QMDSearcher into IndexService

**Files:**
- Modify: `nanobot/memory_index/service.py`
- Create: `tests/test_memory_index/test_service_qmd.py`

**Context:** Current `IndexService.search()` (service.py line 43) delegates directly to `self.index.search(query, top_k=top_k)`. Need to:
1. Add `self._qmd: QMDSearcher | None = None` to `__init__`, constructed when `cfg.backend == "qmd"`.
2. In `search()`, resolve `k` from `top_k` or config default, then branch: if `_qmd is not None and _qmd.is_available()` → get `min(k * 3, 30)` candidates from SQLite, rerank via QMD; else → delegate as before.

Add `TYPE_CHECKING` guard for the `QMDSearcher` import (consistent with existing pattern in `service.py`).

Modified `service.py` structure:

```python
if TYPE_CHECKING:
    from nanobot.config.schema import MemoryIndexConfig
    from nanobot.memory_index.qmd import QMDSearcher
    from nanobot.memory_index.search import SearchResult

class IndexService:
    def __init__(self, workspace: Path, cfg: MemoryIndexConfig) -> None:
        from nanobot.memory_index.index import MemoryIndex

        self.index = MemoryIndex(workspace, cfg)
        self._cfg = cfg
        self._observer = None
        self._qmd: QMDSearcher | None = None
        if cfg.backend == "qmd":
            from nanobot.memory_index.qmd import QMDSearcher
            self._qmd = QMDSearcher(cfg.qmd_binary)

    # ... start/stop/inject_top_k unchanged ...

    async def search(self, query: str, top_k: int | None = None) -> list[SearchResult]:
        """Backend-aware search: SQLite with optional QMD re-ranking."""
        k = top_k if top_k is not None else self._cfg.query.top_k
        if self._qmd is not None and self._qmd.is_available():
            candidate_k = min(k * 3, 30)
            candidates = await self.index.search(query, top_k=candidate_k)
            return await self._qmd.rerank(query, candidates, top_k=k)
        return await self.index.search(query, top_k=top_k)
```

- [ ] **Step 1: Write the failing tests**

Create `tests/test_memory_index/test_service_qmd.py`:
```python
"""Integration tests for IndexService QMD backend routing."""
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot.config.schema import MemoryIndexConfig
from nanobot.memory_index.search import SearchResult


def _make_results(n):
    return [SearchResult(text=f"chunk {i}", source="MEMORY.md", start_line=i, end_line=i+5, score=0.9-i*0.1) for i in range(n)]


def _make_cfg(backend="sqlite", qmd_binary="qmd", **kwargs):
    cfg = MemoryIndexConfig(**kwargs)
    cfg.backend = backend
    cfg.qmd_binary = qmd_binary
    return cfg


# --- backend=sqlite (default) ---

async def test_sqlite_backend_delegates_to_index_search(tmp_path):
    from nanobot.memory_index.service import IndexService

    cfg = _make_cfg(backend="sqlite")
    with patch("nanobot.memory_index.index.MemoryIndex.__init__", return_value=None), \
         patch.object(IndexService, "start", new_callable=AsyncMock):
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

    # Falls back: calls index.search with original top_k
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
```

- [ ] **Step 2: Run tests — verify FAILED**

```bash
pytest tests/test_memory_index/test_service_qmd.py -v
```

- [ ] **Step 3: Modify `nanobot/memory_index/service.py`** (as shown in Context above)

- [ ] **Step 4: Run tests — verify PASSED**

```bash
pytest tests/test_memory_index/test_service_qmd.py -v
```

- [ ] **Step 5: Run full suite — verify no regressions**

```bash
pytest --tb=short -q
```

Expected: 668 passed (663 + 5 new), 1 skipped.

- [ ] **Commit**

```
feat(memory_index): wire QMDSearcher into IndexService for backend-aware re-ranking
```
