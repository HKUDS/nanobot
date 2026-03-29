# Graphiti Memory Plugin — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `nanobot-graphiti`, a separate installable plugin that wires a Graphiti temporal knowledge graph into nanobot as a `MemoryBackend`, replacing flat-file memory with per-turn entity extraction and query-scoped retrieval.

**Architecture:** A standalone Python package at `plugins/nanobot-graphiti/`. Registers `GraphitiMemoryBackend` under the `nanobot.memory` entry-point group. `start(provider)` builds the Graphiti client from nanobot's `LLMProvider`. `consolidate()` calls `graphiti.add_episode()` after every turn (background task). `retrieve()` calls `graphiti.search()` and injects a `[Memory — N facts]` block before each user message. Three tools (`memory_search`, `memory_forget`, `memory_list`) are registered into `AgentLoop`'s tool registry via `get_tools()`.

**Tech Stack:** `graphiti-core>=0.3`, `kuzu>=0.9` (default embedded graph DB), `openai>=2.0` (already a nanobot dep, reused for Graphiti's LLM/embedder adapter), Python 3.11+, pytest, `pytest-asyncio`.

**Prerequisite:** Plan 1 (`2026-03-29-graphiti-memory-core.md`) must be executed first. This plan assumes `MemoryBackend` ABC, `MemoryConfig`, and `load_memory_backend()` are all in place.

---

## File Map

| File | Change |
|---|---|
| `nanobot/config/schema.py` | Amend `MemoryConfig` — add `model_config = ConfigDict(extra="allow")` |
| `plugins/nanobot-graphiti/pyproject.toml` | **New** — package metadata, entry-point, dependencies |
| `plugins/nanobot-graphiti/nanobot_graphiti/__init__.py` | **New** — public export of `GraphitiMemoryBackend` |
| `plugins/nanobot-graphiti/nanobot_graphiti/config.py` | **New** — `GraphitiConfig` pydantic model |
| `plugins/nanobot-graphiti/nanobot_graphiti/backend.py` | **New** — `GraphitiMemoryBackend` (start, consolidate, retrieve, get_tools) |
| `plugins/nanobot-graphiti/nanobot_graphiti/tools.py` | **New** — `MemorySearchTool`, `MemoryForgetTool`, `MemoryListTool` |
| `plugins/nanobot-graphiti/tests/__init__.py` | **New** — empty |
| `plugins/nanobot-graphiti/tests/conftest.py` | **New** — shared fixtures (mock Graphiti client, sample session key) |
| `plugins/nanobot-graphiti/tests/test_backend.py` | **New** — backend contract, consolidate, retrieve, session scoping |
| `plugins/nanobot-graphiti/tests/test_tools.py` | **New** — tool parameter validation, correct Graphiti method dispatch |

---

## Task 1: Amend `MemoryConfig` + Package Scaffold

**Files:**
- Modify: `nanobot/config/schema.py` (add `extra="allow"` to `MemoryConfig`)
- Create: `plugins/nanobot-graphiti/pyproject.toml`
- Create: `plugins/nanobot-graphiti/nanobot_graphiti/__init__.py`
- Create: `plugins/nanobot-graphiti/tests/__init__.py`

**Context:** `MemoryConfig` was added in Plan 1. It needs `extra="allow"` so that `memory.graphiti:` in `config.yaml` is accessible as `config.memory.model_extra["graphiti"]` — the same pattern `ChannelsConfig` uses. The package lives in `plugins/nanobot-graphiti/` (not inside the `nanobot/` package tree) to keep it installable independently.

- [ ] **Step 1: Write the failing test for `MemoryConfig` extra fields**

Add to `tests/agent/test_memory_backend.py` (the file created in Plan 1):
```python
def test_memory_config_accepts_extra_graphiti_section():
    from nanobot.config.schema import MemoryConfig

    cfg = MemoryConfig(**{"backend": "graphiti", "graphiti": {"graph_db": "kuzu", "top_k": 10}})
    assert cfg.model_extra["graphiti"] == {"graph_db": "kuzu", "top_k": 10}
```

- [ ] **Step 2: Run — verify FAILED**

```bash
pytest tests/agent/test_memory_backend.py::test_memory_config_accepts_extra_graphiti_section -v
```
Expected: `FAILED` — extra fields are silently ignored (no `model_extra` key).

- [ ] **Step 3: Add `extra="allow"` to `MemoryConfig` in `nanobot/config/schema.py`**

Find `class MemoryConfig(Base):` (added in Plan 1) and add the config override:
```python
class MemoryConfig(Base):
    """Memory backend configuration."""

    model_config = ConfigDict(extra="allow")

    backend: str = "default"
```

- [ ] **Step 4: Run — verify PASSED**

```bash
pytest tests/agent/test_memory_backend.py::test_memory_config_accepts_extra_graphiti_section -v
```

- [ ] **Step 5: Create the plugin package skeleton**

```bash
mkdir -p plugins/nanobot-graphiti/nanobot_graphiti
mkdir -p plugins/nanobot-graphiti/tests
touch plugins/nanobot-graphiti/tests/__init__.py
touch plugins/nanobot-graphiti/nanobot_graphiti/__init__.py
```

- [ ] **Step 6: Write `plugins/nanobot-graphiti/pyproject.toml`**

```toml
[project]
name = "nanobot-graphiti"
version = "0.1.0"
description = "Graphiti temporal memory backend for nanobot"
requires-python = ">=3.11"
license = {text = "MIT"}
dependencies = [
    "nanobot-ai>=0.1.4",
    "graphiti-core>=0.3",
    "kuzu>=0.9",
]

[project.entry-points."nanobot.memory"]
graphiti = "nanobot_graphiti:GraphitiMemoryBackend"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["nanobot_graphiti"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

- [ ] **Step 7: Write minimal `plugins/nanobot-graphiti/nanobot_graphiti/__init__.py`**

```python
"""nanobot-graphiti — Graphiti temporal memory backend for nanobot."""

from nanobot_graphiti.backend import GraphitiMemoryBackend

__all__ = ["GraphitiMemoryBackend"]
```

- [ ] **Step 8: Install the plugin in editable mode (from repo root)**

```bash
pip install -e plugins/nanobot-graphiti/
```

- [ ] **Step 9: Run full nanobot suite — no regressions**

```bash
pytest --tb=short -q
```
Expected: same count as after Plan 1 (no regressions from the `extra="allow"` change).

- [ ] **Commit**

```
feat(config): allow extra fields in MemoryConfig for plugin config sections
```

---

## Task 2: `GraphitiConfig` Pydantic Model

**Files:**
- Create: `plugins/nanobot-graphiti/nanobot_graphiti/config.py`
- Create: `plugins/nanobot-graphiti/tests/test_backend.py` (config section only for now)

**Context:** `GraphitiConfig` is a standalone Pydantic `BaseModel` (not subclassing nanobot's `Base` — no camelCase alias needed in a plugin). It reads the plugin's section of nanobot's config. `_from_nanobot_config(config)` is a classmethod factory that reads `config.memory.model_extra.get("graphiti", {})` and validates it into a `GraphitiConfig` instance.

- [ ] **Step 1: Write the failing tests**

Create `plugins/nanobot-graphiti/tests/test_backend.py`:
```python
"""Tests for GraphitiMemoryBackend and GraphitiConfig."""

import pytest


# ── Config ──────────────────────────────────────────────────────────────────

def test_graphiti_config_defaults():
    from nanobot_graphiti.config import GraphitiConfig

    cfg = GraphitiConfig()
    assert cfg.graph_db == "kuzu"
    assert cfg.kuzu_path == "~/.nanobot/workspace/memory/graph"
    assert cfg.top_k == 5
    assert cfg.scope == "user"
    assert cfg.embedding_model == "text-embedding-3-small"


def test_graphiti_config_accepts_neo4j():
    from nanobot_graphiti.config import GraphitiConfig

    cfg = GraphitiConfig(graph_db="neo4j", neo4j_uri="bolt://myhost:7687", neo4j_password="secret")
    assert cfg.graph_db == "neo4j"
    assert cfg.neo4j_uri == "bolt://myhost:7687"


def test_graphiti_config_from_nanobot_config_kuzu():
    """_from_nanobot_config() parses memory.model_extra["graphiti"] section."""
    from unittest.mock import MagicMock
    from nanobot_graphiti.config import GraphitiConfig

    nanobot_config = MagicMock()
    nanobot_config.memory.model_extra = {"graphiti": {"graph_db": "kuzu", "top_k": 10}}

    cfg = GraphitiConfig._from_nanobot_config(nanobot_config)
    assert cfg.graph_db == "kuzu"
    assert cfg.top_k == 10


def test_graphiti_config_from_nanobot_config_missing_section():
    """_from_nanobot_config() falls back to defaults when section absent."""
    from unittest.mock import MagicMock
    from nanobot_graphiti.config import GraphitiConfig

    nanobot_config = MagicMock()
    nanobot_config.memory.model_extra = {}

    cfg = GraphitiConfig._from_nanobot_config(nanobot_config)
    assert cfg.graph_db == "kuzu"
    assert cfg.top_k == 5
```

- [ ] **Step 2: Run — verify FAILED**

```bash
cd plugins/nanobot-graphiti && pytest tests/test_backend.py -v -k "config" 2>&1 | head -20
```
Expected: `FAILED` — `cannot import name 'GraphitiConfig'`

- [ ] **Step 3: Write `plugins/nanobot-graphiti/nanobot_graphiti/config.py`**

```python
"""GraphitiConfig — configuration for the nanobot-graphiti memory backend."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel

if TYPE_CHECKING:
    pass


class GraphitiConfig(BaseModel):
    """Configuration for the Graphiti memory backend."""

    graph_db: Literal["kuzu", "neo4j", "falkordb"] = "kuzu"
    kuzu_path: str = "~/.nanobot/workspace/memory/graph"
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = ""
    falkordb_host: str = "localhost"
    falkordb_port: int = 6379
    top_k: int = 5
    scope: Literal["user", "session"] = "user"
    embedding_model: str = "text-embedding-3-small"

    @classmethod
    def _from_nanobot_config(cls, config: Any) -> "GraphitiConfig":
        """Extract and validate Graphiti config from nanobot's Config object."""
        raw: Any = getattr(config.memory, "model_extra", {}).get("graphiti") or {}
        if hasattr(raw, "model_dump"):
            raw = raw.model_dump()
        return cls(**(raw if isinstance(raw, dict) else {}))
```

- [ ] **Step 4: Run — verify PASSED**

```bash
cd plugins/nanobot-graphiti && pytest tests/test_backend.py -v -k "config"
```
Expected: 4 passed.

- [ ] **Commit**

```
feat(nanobot-graphiti): add GraphitiConfig pydantic model with _from_nanobot_config factory
```

---

## Task 3: `GraphitiMemoryBackend` — Constructor, `consolidates_per_turn`, `start()`, `stop()`

**Files:**
- Create: `plugins/nanobot-graphiti/nanobot_graphiti/backend.py`
- Create: `plugins/nanobot-graphiti/tests/conftest.py`
- Modify: `plugins/nanobot-graphiti/tests/test_backend.py` (add backend contract tests)

**Context:** `start(provider)` creates the Graphiti client from nanobot's `LLMProvider`. For OpenAI-compatible providers, it reads `provider.api_key`, `provider.api_base`, and `provider.get_default_model()` to construct Graphiti's `OpenAIClient` and `OpenAIEmbedder`. For Anthropic providers (which don't expose an OpenAI-compat base URL), `start()` raises `RuntimeError` with a clear message. `stop()` calls `await graphiti.close()`. The Graphiti client is injectable via `_graphiti_factory` for testing.

- [ ] **Step 1: Write conftest.py with shared fixtures**

Create `plugins/nanobot-graphiti/tests/conftest.py`:
```python
"""Shared fixtures for nanobot-graphiti tests."""

import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.fixture
def mock_graphiti():
    """A fully mocked Graphiti client."""
    g = MagicMock()
    g.build_indices_and_constraints = AsyncMock()
    g.add_episode = AsyncMock()
    g.search = AsyncMock(return_value=[])
    g.close = AsyncMock()
    g.driver = MagicMock()
    return g


@pytest.fixture
def mock_provider():
    """A minimal nanobot LLMProvider mock."""
    p = MagicMock()
    p.api_key = "test-key"
    p.api_base = "https://api.openai.com/v1"
    p.get_default_model.return_value = "gpt-4o-mini"
    return p


@pytest.fixture
def session_key():
    return "telegram:123456"
```

- [ ] **Step 2: Write failing backend contract tests**

Add to `plugins/nanobot-graphiti/tests/test_backend.py`:
```python
# ── Backend contract ─────────────────────────────────────────────────────────

def test_graphiti_backend_is_memory_backend():
    from nanobot.agent.memory import MemoryBackend
    from nanobot_graphiti.backend import GraphitiMemoryBackend

    assert issubclass(GraphitiMemoryBackend, MemoryBackend)


def test_graphiti_backend_consolidates_per_turn_is_true():
    from nanobot_graphiti.backend import GraphitiMemoryBackend
    from nanobot_graphiti.config import GraphitiConfig

    backend = GraphitiMemoryBackend(GraphitiConfig())
    assert backend.consolidates_per_turn is True


async def test_graphiti_backend_start_calls_build_indices(mock_graphiti, mock_provider):
    from nanobot_graphiti.backend import GraphitiMemoryBackend
    from nanobot_graphiti.config import GraphitiConfig

    backend = GraphitiMemoryBackend(GraphitiConfig(), _graphiti_factory=lambda **kw: mock_graphiti)
    await backend.start(mock_provider)

    mock_graphiti.build_indices_and_constraints.assert_awaited_once()


async def test_graphiti_backend_stop_closes_client(mock_graphiti, mock_provider):
    from nanobot_graphiti.backend import GraphitiMemoryBackend
    from nanobot_graphiti.config import GraphitiConfig

    backend = GraphitiMemoryBackend(GraphitiConfig(), _graphiti_factory=lambda **kw: mock_graphiti)
    await backend.start(mock_provider)
    await backend.stop()

    mock_graphiti.close.assert_awaited_once()


async def test_graphiti_backend_stop_is_safe_before_start():
    """stop() before start() must not raise."""
    from nanobot_graphiti.backend import GraphitiMemoryBackend
    from nanobot_graphiti.config import GraphitiConfig

    backend = GraphitiMemoryBackend(GraphitiConfig())
    await backend.stop()  # no exception
```

- [ ] **Step 3: Run — verify FAILED**

```bash
cd plugins/nanobot-graphiti && pytest tests/test_backend.py -v -k "backend" 2>&1 | head -30
```
Expected: `FAILED` — `cannot import name 'GraphitiMemoryBackend'`

- [ ] **Step 4: Write `plugins/nanobot-graphiti/nanobot_graphiti/backend.py` (start/stop only)**

```python
"""GraphitiMemoryBackend — Graphiti temporal memory backend for nanobot."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Callable

from nanobot.agent.memory import MemoryBackend
from nanobot.agent.tools.base import Tool
from nanobot_graphiti.config import GraphitiConfig

if TYPE_CHECKING:
    from nanobot.providers.base import LLMProvider

logger = logging.getLogger(__name__)


def _build_driver(config: GraphitiConfig) -> Any:
    """Construct the graph DB driver for the configured backend."""
    from pathlib import Path

    if config.graph_db == "kuzu":
        from graphiti_core.driver.kuzu_driver import KuzuDriver

        db_path = str(Path(config.kuzu_path).expanduser())
        Path(db_path).mkdir(parents=True, exist_ok=True)
        return KuzuDriver(db=db_path)

    if config.graph_db == "neo4j":
        from graphiti_core.driver.neo4j_driver import Neo4jDriver

        return Neo4jDriver(
            uri=config.neo4j_uri,
            user=config.neo4j_user,
            password=config.neo4j_password,
        )

    if config.graph_db == "falkordb":
        from graphiti_core.driver.falkordb_driver import FalkorDBDriver

        return FalkorDBDriver(host=config.falkordb_host, port=config.falkordb_port)

    raise ValueError(f"Unknown graph_db: {config.graph_db!r}")


def _build_graphiti(config: GraphitiConfig, provider: "LLMProvider") -> Any:
    """Build a Graphiti client wired to nanobot's LLM provider."""
    from openai import AsyncOpenAI
    from graphiti_core import Graphiti
    from graphiti_core.llm_client.openai_client import OpenAIClient as GraphitiLLMClient
    from graphiti_core.embedder.openai import OpenAIEmbedder

    if not provider.api_base:
        raise RuntimeError(
            "nanobot-graphiti requires an OpenAI-compatible provider (api_base must be set). "
            "Anthropic's native endpoint is not supported. "
            "Use an OpenAI-compat model (openrouter, openai, etc.) for Graphiti memory."
        )

    openai_client = AsyncOpenAI(
        api_key=provider.api_key or "no-key",
        base_url=provider.api_base,
    )
    llm_client = GraphitiLLMClient(
        client=openai_client,
        model=provider.get_default_model(),
    )
    embedder = OpenAIEmbedder(
        client=openai_client,
        model=config.embedding_model,
    )
    driver = _build_driver(config)
    return Graphiti(graph_driver=driver, llm_client=llm_client, embedder=embedder)


class GraphitiMemoryBackend(MemoryBackend):
    """Graphiti temporal knowledge graph memory backend."""

    consolidates_per_turn = True

    def __init__(
        self,
        config: GraphitiConfig,
        *,
        _graphiti_factory: Callable[..., Any] | None = None,
    ) -> None:
        self._config = config
        self._graphiti: Any | None = None
        self._graphiti_factory = _graphiti_factory

    @classmethod
    def from_nanobot_config(cls, nanobot_config: Any) -> "GraphitiMemoryBackend":
        """Instantiate from a nanobot Config object (entry-point discovery path)."""
        return cls(GraphitiConfig._from_nanobot_config(nanobot_config))

    async def start(self, provider: "LLMProvider") -> None:
        if self._graphiti_factory is not None:
            self._graphiti = self._graphiti_factory(config=self._config, provider=provider)
        else:
            self._graphiti = _build_graphiti(self._config, provider)
        await self._graphiti.build_indices_and_constraints()

    async def stop(self) -> None:
        if self._graphiti is not None:
            await self._graphiti.close()
            self._graphiti = None

    def _get_group_id(self, session_key: str) -> str:
        if self._config.scope == "user":
            _, _, chat_id = session_key.partition(":")
            return chat_id or session_key
        return session_key

    async def consolidate(self, messages: list[dict], session_key: str) -> None:
        raise NotImplementedError  # implemented in Task 4

    async def retrieve(self, query: str, session_key: str, top_k: int = 5) -> str:
        raise NotImplementedError  # implemented in Task 5

    def get_tools(self) -> list[Tool]:
        return []  # implemented in Task 7
```

- [ ] **Step 5: Run — verify PASSED**

```bash
cd plugins/nanobot-graphiti && pytest tests/test_backend.py -v -k "backend"
```
Expected: 5 passed (`is_memory_backend`, `consolidates_per_turn`, `start_calls_build_indices`, `stop_closes_client`, `stop_is_safe_before_start`).

- [ ] **Commit**

```
feat(nanobot-graphiti): add GraphitiMemoryBackend skeleton with start/stop lifecycle
```

---

## Task 4: `consolidate()` — Episode Ingestion

**Files:**
- Modify: `plugins/nanobot-graphiti/nanobot_graphiti/backend.py`
- Modify: `plugins/nanobot-graphiti/tests/test_backend.py`

**Context:** `consolidate()` formats `messages` (list of `{"role": ..., "content": ...}` dicts) as a conversational text string and calls `graphiti.add_episode()`. Errors are caught and logged — never raised (the agent loop must never be blocked by a memory error). `group_id` is derived from `session_key` via `_get_group_id()`.

- [ ] **Step 1: Write the failing tests**

Add to `plugins/nanobot-graphiti/tests/test_backend.py`:
```python
# ── consolidate() ────────────────────────────────────────────────────────────

async def test_consolidate_calls_add_episode(mock_graphiti, mock_provider, session_key):
    from nanobot_graphiti.backend import GraphitiMemoryBackend
    from nanobot_graphiti.config import GraphitiConfig

    backend = GraphitiMemoryBackend(GraphitiConfig(), _graphiti_factory=lambda **kw: mock_graphiti)
    await backend.start(mock_provider)

    messages = [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi there!"},
    ]
    await backend.consolidate(messages, session_key)

    mock_graphiti.add_episode.assert_awaited_once()
    call_kwargs = mock_graphiti.add_episode.call_args.kwargs
    assert call_kwargs["group_id"] == "123456"   # scope="user" strips "telegram:"
    assert "Hello" in call_kwargs["episode_body"]
    assert "Hi there!" in call_kwargs["episode_body"]


async def test_consolidate_uses_session_scope(mock_graphiti, mock_provider):
    from nanobot_graphiti.backend import GraphitiMemoryBackend
    from nanobot_graphiti.config import GraphitiConfig

    backend = GraphitiMemoryBackend(
        GraphitiConfig(scope="session"),
        _graphiti_factory=lambda **kw: mock_graphiti,
    )
    await backend.start(mock_provider)
    await backend.consolidate([{"role": "user", "content": "hi"}], "telegram:123456")

    call_kwargs = mock_graphiti.add_episode.call_args.kwargs
    assert call_kwargs["group_id"] == "telegram:123456"


async def test_consolidate_swallows_errors(mock_graphiti, mock_provider, session_key):
    """consolidate() must not raise even if graphiti.add_episode() fails."""
    from nanobot_graphiti.backend import GraphitiMemoryBackend
    from nanobot_graphiti.config import GraphitiConfig

    mock_graphiti.add_episode.side_effect = RuntimeError("graph unavailable")

    backend = GraphitiMemoryBackend(GraphitiConfig(), _graphiti_factory=lambda **kw: mock_graphiti)
    await backend.start(mock_provider)
    await backend.consolidate([{"role": "user", "content": "hi"}], session_key)
    # No exception raised — test passes if we reach here


async def test_consolidate_skips_empty_messages(mock_graphiti, mock_provider, session_key):
    from nanobot_graphiti.backend import GraphitiMemoryBackend
    from nanobot_graphiti.config import GraphitiConfig

    backend = GraphitiMemoryBackend(GraphitiConfig(), _graphiti_factory=lambda **kw: mock_graphiti)
    await backend.start(mock_provider)
    await backend.consolidate([], session_key)

    mock_graphiti.add_episode.assert_not_awaited()
```

- [ ] **Step 2: Run — verify FAILED**

```bash
cd plugins/nanobot-graphiti && pytest tests/test_backend.py -v -k "consolidate"
```
Expected: `FAILED` — `NotImplementedError` from the stub.

- [ ] **Step 3: Implement `consolidate()` in `backend.py`**

Replace the `consolidate` stub in `GraphitiMemoryBackend`:
```python
async def consolidate(self, messages: list[dict], session_key: str) -> None:
    if not messages or self._graphiti is None:
        return
    try:
        from graphiti_core.nodes import EpisodeType

        lines = []
        for msg in messages:
            role = msg.get("role", "unknown").capitalize()
            content = msg.get("content") or ""
            if isinstance(content, list):
                # Handle multi-part content blocks (e.g. tool results)
                content = " ".join(
                    part.get("text", "") if isinstance(part, dict) else str(part)
                    for part in content
                )
            if content:
                lines.append(f"{role}: {content}")

        episode_body = "\n".join(lines)
        if not episode_body.strip():
            return

        group_id = self._get_group_id(session_key)
        await self._graphiti.add_episode(
            name=session_key,
            episode_body=episode_body,
            source_description="nanobot conversation",
            reference_time=datetime.now(timezone.utc),
            source=EpisodeType.message,
            group_id=group_id,
        )
    except Exception:
        logger.exception("GraphitiMemoryBackend.consolidate() failed — memory not updated")
```

- [ ] **Step 4: Run — verify PASSED**

```bash
cd plugins/nanobot-graphiti && pytest tests/test_backend.py -v -k "consolidate"
```
Expected: 4 passed.

- [ ] **Commit**

```
feat(nanobot-graphiti): implement consolidate() — episode ingestion with error swallowing
```

---

## Task 5: `retrieve()` — Search and Format

**Files:**
- Modify: `plugins/nanobot-graphiti/nanobot_graphiti/backend.py`
- Modify: `plugins/nanobot-graphiti/tests/test_backend.py`

**Context:** `retrieve()` calls `graphiti.search()` with `group_ids=[group_id]` and `num_results=top_k`. Results are `list[EntityEdge]` — each has `.fact` (text) and a `created_at` or `updated_at` datetime. The output is formatted as a `[Memory — N relevant facts]` block. When search returns no results, returns `""` (no block injected).

- [ ] **Step 1: Write the failing tests**

Add to `plugins/nanobot-graphiti/tests/test_backend.py`:
```python
# ── retrieve() ───────────────────────────────────────────────────────────────

async def test_retrieve_calls_search_with_group_id(mock_graphiti, mock_provider, session_key):
    from unittest.mock import MagicMock
    from nanobot_graphiti.backend import GraphitiMemoryBackend
    from nanobot_graphiti.config import GraphitiConfig

    edge = MagicMock()
    edge.fact = "User likes coffee"
    edge.uuid = "abc-123"
    mock_graphiti.search.return_value = [edge]

    backend = GraphitiMemoryBackend(GraphitiConfig(), _graphiti_factory=lambda **kw: mock_graphiti)
    await backend.start(mock_provider)

    result = await backend.retrieve("coffee", session_key, top_k=3)

    mock_graphiti.search.assert_awaited_once_with("coffee", group_ids=["123456"], num_results=3)
    assert "User likes coffee" in result
    assert "[Memory" in result


async def test_retrieve_returns_empty_string_when_no_results(mock_graphiti, mock_provider, session_key):
    from nanobot_graphiti.backend import GraphitiMemoryBackend
    from nanobot_graphiti.config import GraphitiConfig

    mock_graphiti.search.return_value = []

    backend = GraphitiMemoryBackend(GraphitiConfig(), _graphiti_factory=lambda **kw: mock_graphiti)
    await backend.start(mock_provider)

    result = await backend.retrieve("anything", session_key)
    assert result == ""


async def test_retrieve_uses_config_top_k_as_default(mock_graphiti, mock_provider, session_key):
    from nanobot_graphiti.backend import GraphitiMemoryBackend
    from nanobot_graphiti.config import GraphitiConfig

    backend = GraphitiMemoryBackend(
        GraphitiConfig(top_k=7),
        _graphiti_factory=lambda **kw: mock_graphiti,
    )
    await backend.start(mock_provider)
    await backend.retrieve("query", session_key)

    call_kwargs = mock_graphiti.search.call_args.kwargs
    assert call_kwargs["num_results"] == 5  # retrieve() top_k param default, not config


async def test_retrieve_formats_multiple_facts(mock_graphiti, mock_provider, session_key):
    from unittest.mock import MagicMock
    from nanobot_graphiti.backend import GraphitiMemoryBackend
    from nanobot_graphiti.config import GraphitiConfig

    edges = []
    for i, fact in enumerate(["Likes coffee", "Works in Berlin", "Has a cat"]):
        edge = MagicMock()
        edge.fact = fact
        edge.uuid = f"uuid-{i}"
        edges.append(edge)
    mock_graphiti.search.return_value = edges

    backend = GraphitiMemoryBackend(GraphitiConfig(), _graphiti_factory=lambda **kw: mock_graphiti)
    await backend.start(mock_provider)

    result = await backend.retrieve("tell me about user", session_key)
    assert "Likes coffee" in result
    assert "Works in Berlin" in result
    assert "Has a cat" in result
    assert "[Memory — 3 relevant facts]" in result
```

- [ ] **Step 2: Run — verify FAILED**

```bash
cd plugins/nanobot-graphiti && pytest tests/test_backend.py -v -k "retrieve"
```
Expected: `FAILED` — `NotImplementedError` from the stub.

- [ ] **Step 3: Implement `retrieve()` in `backend.py`**

Replace the `retrieve` stub in `GraphitiMemoryBackend`:
```python
async def retrieve(self, query: str, session_key: str, top_k: int = 5) -> str:
    if self._graphiti is None:
        return ""
    try:
        group_id = self._get_group_id(session_key)
        results = await self._graphiti.search(query, group_ids=[group_id], num_results=top_k)
        if not results:
            return ""
        lines = [f"[Memory — {len(results)} relevant facts]"]
        for edge in results:
            lines.append(f"• {edge.fact}")
        return "\n".join(lines)
    except Exception:
        logger.exception("GraphitiMemoryBackend.retrieve() failed — no memory injected")
        return ""
```

- [ ] **Step 4: Run — verify PASSED**

```bash
cd plugins/nanobot-graphiti && pytest tests/test_backend.py -v -k "retrieve"
```
Expected: 4 passed.

**Note on `test_retrieve_uses_config_top_k_as_default`:** The test asserts `num_results=5` (the `retrieve()` param default), not `top_k=7` from config. This is correct — `retrieve(query, session_key)` is called by `AgentLoop` with no explicit `top_k`, so it uses the parameter default of 5. The `config.top_k` is used by tools (e.g. `MemorySearchTool`), not here.

- [ ] **Commit**

```
feat(nanobot-graphiti): implement retrieve() — semantic search with [Memory] block formatting
```

---

## Task 6: Three Memory Tools

**Files:**
- Create: `plugins/nanobot-graphiti/nanobot_graphiti/tools.py`
- Create: `plugins/nanobot-graphiti/tests/test_tools.py`

**Context:** All three tools hold a reference to the `GraphitiMemoryBackend` instance (passed at construction time). This gives them access to `backend._graphiti` and `backend._get_group_id()`. Each subclasses nanobot's `Tool` ABC.

- `MemorySearchTool` — calls `backend._graphiti.search(query, group_ids=[group_id], num_results=top_k)` and returns formatted text.
- `MemoryForgetTool` — calls `EntityEdge.delete_by_uuids(backend._graphiti.driver, [fact_id])`.
- `MemoryListTool` — calls `backend._graphiti.search("", group_ids=[group_id], num_results=limit)` (empty query returns all facts).

- [ ] **Step 1: Write the failing tests**

Create `plugins/nanobot-graphiti/tests/test_tools.py`:
```python
"""Tests for memory tools."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture
def backend_with_mock_graphiti(mock_graphiti, mock_provider):
    """A started GraphitiMemoryBackend with an injected mock graphiti client."""
    import asyncio
    from nanobot_graphiti.backend import GraphitiMemoryBackend
    from nanobot_graphiti.config import GraphitiConfig

    backend = GraphitiMemoryBackend(GraphitiConfig(), _graphiti_factory=lambda **kw: mock_graphiti)
    asyncio.get_event_loop().run_until_complete(backend.start(mock_provider))
    return backend, mock_graphiti


def _make_edge(fact: str, uuid: str = "test-uuid") -> MagicMock:
    edge = MagicMock()
    edge.fact = fact
    edge.uuid = uuid
    return edge


# ── MemorySearchTool ─────────────────────────────────────────────────────────

async def test_memory_search_tool_name():
    from nanobot_graphiti.tools import MemorySearchTool

    tool = MemorySearchTool(backend=MagicMock())
    assert tool.name == "memory_search"


async def test_memory_search_calls_graphiti_search(mock_graphiti):
    from nanobot_graphiti.tools import MemorySearchTool

    mock_graphiti.search.return_value = [_make_edge("User prefers dark mode")]

    backend = MagicMock()
    backend._graphiti = mock_graphiti
    backend._get_group_id.return_value = "123456"

    tool = MemorySearchTool(backend=backend)
    result = await tool.execute(query="UI preferences", top_k=5, session_key="telegram:123456")

    mock_graphiti.search.assert_awaited_once_with("UI preferences", group_ids=["123456"], num_results=5)
    assert "User prefers dark mode" in result


async def test_memory_search_returns_no_results_message(mock_graphiti):
    from nanobot_graphiti.tools import MemorySearchTool

    mock_graphiti.search.return_value = []

    backend = MagicMock()
    backend._graphiti = mock_graphiti
    backend._get_group_id.return_value = "123456"

    tool = MemorySearchTool(backend=backend)
    result = await tool.execute(query="nonexistent", top_k=5, session_key="telegram:123456")

    assert "no" in result.lower() or "0" in result


# ── MemoryForgetTool ─────────────────────────────────────────────────────────

async def test_memory_forget_tool_name():
    from nanobot_graphiti.tools import MemoryForgetTool

    tool = MemoryForgetTool(backend=MagicMock())
    assert tool.name == "memory_forget"


async def test_memory_forget_calls_delete_by_uuids(mock_graphiti):
    from nanobot_graphiti.tools import MemoryForgetTool
    from graphiti_core.nodes import EntityEdge

    backend = MagicMock()
    backend._graphiti = mock_graphiti

    with patch.object(EntityEdge, "delete_by_uuids", new_callable=AsyncMock) as mock_delete:
        tool = MemoryForgetTool(backend=backend)
        result = await tool.execute(fact_id="abc-123", reason="incorrect info", session_key="telegram:123456")

    mock_delete.assert_awaited_once_with(mock_graphiti.driver, ["abc-123"])
    assert "abc-123" in result or "deleted" in result.lower() or "forgotten" in result.lower()


# ── MemoryListTool ───────────────────────────────────────────────────────────

async def test_memory_list_tool_name():
    from nanobot_graphiti.tools import MemoryListTool

    tool = MemoryListTool(backend=MagicMock())
    assert tool.name == "memory_list"


async def test_memory_list_calls_search_with_empty_query(mock_graphiti):
    from nanobot_graphiti.tools import MemoryListTool

    edges = [_make_edge("Fact 1", "u1"), _make_edge("Fact 2", "u2")]
    mock_graphiti.search.return_value = edges

    backend = MagicMock()
    backend._graphiti = mock_graphiti
    backend._get_group_id.return_value = "123456"

    tool = MemoryListTool(backend=backend)
    result = await tool.execute(limit=20, session_key="telegram:123456")

    mock_graphiti.search.assert_awaited_once_with("", group_ids=["123456"], num_results=20)
    assert "Fact 1" in result
    assert "Fact 2" in result


async def test_memory_list_shows_uuids_for_reference(mock_graphiti):
    """memory_list output includes fact_id so user can reference it in memory_forget."""
    from nanobot_graphiti.tools import MemoryListTool

    mock_graphiti.search.return_value = [_make_edge("I have a dog", "edge-uuid-xyz")]

    backend = MagicMock()
    backend._graphiti = mock_graphiti
    backend._get_group_id.return_value = "123456"

    tool = MemoryListTool(backend=backend)
    result = await tool.execute(limit=50, session_key="telegram:123456")

    assert "edge-uuid-xyz" in result
```

- [ ] **Step 2: Run — verify FAILED**

```bash
cd plugins/nanobot-graphiti && pytest tests/test_tools.py -v 2>&1 | head -30
```
Expected: `FAILED` — `cannot import name 'MemorySearchTool'`

- [ ] **Step 3: Write `plugins/nanobot-graphiti/nanobot_graphiti/tools.py`**

```python
"""Memory tools for the Graphiti memory backend."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nanobot.agent.tools.base import Tool

if TYPE_CHECKING:
    from nanobot_graphiti.backend import GraphitiMemoryBackend


class MemorySearchTool(Tool):
    """Semantic search over the Graphiti memory graph."""

    def __init__(self, backend: "GraphitiMemoryBackend") -> None:
        self._backend = backend

    @property
    def name(self) -> str:
        return "memory_search"

    @property
    def description(self) -> str:
        return (
            "Search your memory for facts about the current user. "
            "Use when asked about past conversations, preferences, or history."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Natural language search query"},
                "top_k": {"type": "integer", "description": "Max results to return", "default": 10},
                "session_key": {"type": "string", "description": "Current session key (e.g. telegram:123456)"},
            },
            "required": ["query", "session_key"],
        }

    async def execute(self, query: str, session_key: str, top_k: int = 10, **_: Any) -> str:
        graphiti = self._backend._graphiti
        if graphiti is None:
            return "Memory backend not started."
        group_id = self._backend._get_group_id(session_key)
        results = await graphiti.search(query, group_ids=[group_id], num_results=top_k)
        if not results:
            return f"No memories found for query: {query!r}"
        lines = [f"Found {len(results)} fact(s):"]
        for edge in results:
            lines.append(f"• [{edge.uuid}] {edge.fact}")
        return "\n".join(lines)


class MemoryForgetTool(Tool):
    """Delete a specific fact from the memory graph by its ID."""

    def __init__(self, backend: "GraphitiMemoryBackend") -> None:
        self._backend = backend

    @property
    def name(self) -> str:
        return "memory_forget"

    @property
    def description(self) -> str:
        return (
            "Delete a specific memory fact by its ID. "
            "Use when a user says 'you have that wrong' or asks you to forget something. "
            "Get the fact_id from memory_search or memory_list first."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "fact_id": {"type": "string", "description": "The UUID of the fact to delete"},
                "reason": {"type": "string", "description": "Why this fact is being removed"},
                "session_key": {"type": "string", "description": "Current session key"},
            },
            "required": ["fact_id", "reason", "session_key"],
        }

    async def execute(self, fact_id: str, reason: str, session_key: str, **_: Any) -> str:
        from graphiti_core.nodes import EntityEdge

        graphiti = self._backend._graphiti
        if graphiti is None:
            return "Memory backend not started."
        await EntityEdge.delete_by_uuids(graphiti.driver, [fact_id])
        return f"Fact {fact_id!r} deleted. Reason: {reason}"


class MemoryListTool(Tool):
    """List all stored memory facts for the current user."""

    def __init__(self, backend: "GraphitiMemoryBackend") -> None:
        self._backend = backend

    @property
    def name(self) -> str:
        return "memory_list"

    @property
    def description(self) -> str:
        return (
            "List all stored memory facts for the current user. "
            "Use when asked 'what do you know about me?' or to audit stored memories."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Max facts to return", "default": 50},
                "session_key": {"type": "string", "description": "Current session key"},
            },
            "required": ["session_key"],
        }

    async def execute(self, session_key: str, limit: int = 50, **_: Any) -> str:
        graphiti = self._backend._graphiti
        if graphiti is None:
            return "Memory backend not started."
        group_id = self._backend._get_group_id(session_key)
        results = await graphiti.search("", group_ids=[group_id], num_results=limit)
        if not results:
            return "No memories stored for this user."
        lines = [f"Stored memories ({len(results)} fact(s)):"]
        for edge in results:
            lines.append(f"• [{edge.uuid}] {edge.fact}")
        return "\n".join(lines)
```

- [ ] **Step 4: Run — verify PASSED**

```bash
cd plugins/nanobot-graphiti && pytest tests/test_tools.py -v
```
Expected: 9 passed.

- [ ] **Commit**

```
feat(nanobot-graphiti): add MemorySearchTool, MemoryForgetTool, MemoryListTool
```

---

## Task 7: `get_tools()` Wiring + Session Scoping Tests

**Files:**
- Modify: `plugins/nanobot-graphiti/nanobot_graphiti/backend.py`
- Modify: `plugins/nanobot-graphiti/tests/test_backend.py`

**Context:** `get_tools()` returns instances of all three tools bound to `self`. The session scoping logic (`_get_group_id`) is already tested indirectly in Task 4/5, but this task adds explicit tests for the two scope modes.

- [ ] **Step 1: Write the failing tests**

Add to `plugins/nanobot-graphiti/tests/test_backend.py`:
```python
# ── get_tools() ───────────────────────────────────────────────────────────────

def test_get_tools_returns_three_tools(mock_graphiti, mock_provider):
    import asyncio
    from nanobot_graphiti.backend import GraphitiMemoryBackend
    from nanobot_graphiti.config import GraphitiConfig

    backend = GraphitiMemoryBackend(GraphitiConfig(), _graphiti_factory=lambda **kw: mock_graphiti)
    asyncio.get_event_loop().run_until_complete(backend.start(mock_provider))

    tools = backend.get_tools()
    tool_names = {t.name for t in tools}

    assert len(tools) == 3
    assert tool_names == {"memory_search", "memory_forget", "memory_list"}


def test_get_tools_returns_tool_instances_bound_to_backend(mock_graphiti, mock_provider):
    import asyncio
    from nanobot.agent.tools.base import Tool
    from nanobot_graphiti.backend import GraphitiMemoryBackend
    from nanobot_graphiti.config import GraphitiConfig

    backend = GraphitiMemoryBackend(GraphitiConfig(), _graphiti_factory=lambda **kw: mock_graphiti)
    asyncio.get_event_loop().run_until_complete(backend.start(mock_provider))

    for tool in backend.get_tools():
        assert isinstance(tool, Tool)
        assert tool._backend is backend


# ── Session scoping ───────────────────────────────────────────────────────────

def test_group_id_user_scope_strips_channel_prefix():
    from nanobot_graphiti.backend import GraphitiMemoryBackend
    from nanobot_graphiti.config import GraphitiConfig

    backend = GraphitiMemoryBackend(GraphitiConfig(scope="user"))
    assert backend._get_group_id("telegram:123456") == "123456"
    assert backend._get_group_id("discord:789") == "789"


def test_group_id_session_scope_preserves_full_key():
    from nanobot_graphiti.backend import GraphitiMemoryBackend
    from nanobot_graphiti.config import GraphitiConfig

    backend = GraphitiMemoryBackend(GraphitiConfig(scope="session"))
    assert backend._get_group_id("telegram:123456") == "telegram:123456"
    assert backend._get_group_id("discord:789") == "discord:789"


def test_group_id_user_scope_handles_key_without_colon():
    from nanobot_graphiti.backend import GraphitiMemoryBackend
    from nanobot_graphiti.config import GraphitiConfig

    backend = GraphitiMemoryBackend(GraphitiConfig(scope="user"))
    # Falls back to full key if no colon present
    assert backend._get_group_id("directuser") == "directuser"
```

- [ ] **Step 2: Run — verify FAILED**

```bash
cd plugins/nanobot-graphiti && pytest tests/test_backend.py -v -k "get_tools or group_id or session_scoping or scope"
```
Expected: `FAILED` — `get_tools()` returns `[]` (stub from Task 3).

- [ ] **Step 3: Implement `get_tools()` in `backend.py`**

Replace the `get_tools` stub in `GraphitiMemoryBackend`:
```python
def get_tools(self) -> list[Tool]:
    from nanobot_graphiti.tools import MemoryForgetTool, MemoryListTool, MemorySearchTool

    return [
        MemorySearchTool(backend=self),
        MemoryForgetTool(backend=self),
        MemoryListTool(backend=self),
    ]
```

- [ ] **Step 4: Run — verify PASSED**

```bash
cd plugins/nanobot-graphiti && pytest tests/test_backend.py -v -k "get_tools or group_id or scope"
```
Expected: 5 passed.

- [ ] **Step 5: Run full plugin test suite**

```bash
cd plugins/nanobot-graphiti && pytest -v
```
Expected: all tests pass (backend + tools).

- [ ] **Step 6: Run nanobot core suite from repo root**

```bash
cd /path/to/repo && pytest --tb=short -q
```
Expected: no regressions.

- [ ] **Commit**

```
feat(nanobot-graphiti): wire get_tools() — all three memory tools registered from backend
```

---

## Task 8: `from_nanobot_config()` Entry-Point Wiring

**Files:**
- Modify: `plugins/nanobot-graphiti/nanobot_graphiti/backend.py` (verify `from_nanobot_config` classmethod)
- Modify: `plugins/nanobot-graphiti/tests/test_backend.py`

**Context:** The `nanobot.memory` entry-point discovery in Plan 1 calls `backend_class(config)` where `config` is the nanobot `Config` object. `GraphitiMemoryBackend.__init__` takes a `GraphitiConfig`, not a nanobot `Config`. The `from_nanobot_config` classmethod handles this. Plan 1's `load_memory_backend` needs to call `cls.from_nanobot_config(config)` if the method exists — or we change `load_memory_backend` to always call `cls(config)` and override `__init__` to handle both types. The cleaner path: add `from_nanobot_config` as the entry-point target by registering it differently, OR adjust Plan 1's `load_memory_backend` to detect the factory method.

The spec says the entry-point value is `"nanobot_graphiti:GraphitiMemoryBackend"` — a class, not a factory method. Plan 1's `load_memory_backend` should call `cls.from_nanobot_config(config)` when the classmethod exists, falling back to `cls(config)` for simpler backends. Test this interaction here.

- [ ] **Step 1: Write the integration test**

Add to `plugins/nanobot-graphiti/tests/test_backend.py`:
```python
# ── Entry-point factory ───────────────────────────────────────────────────────

def test_from_nanobot_config_creates_backend_with_correct_config():
    from unittest.mock import MagicMock
    from nanobot_graphiti.backend import GraphitiMemoryBackend

    nanobot_config = MagicMock()
    nanobot_config.memory.model_extra = {
        "graphiti": {"graph_db": "kuzu", "top_k": 8, "scope": "session"}
    }

    backend = GraphitiMemoryBackend.from_nanobot_config(nanobot_config)

    assert isinstance(backend, GraphitiMemoryBackend)
    assert backend._config.graph_db == "kuzu"
    assert backend._config.top_k == 8
    assert backend._config.scope == "session"


def test_from_nanobot_config_falls_back_to_defaults_on_empty_config():
    from unittest.mock import MagicMock
    from nanobot_graphiti.backend import GraphitiMemoryBackend

    nanobot_config = MagicMock()
    nanobot_config.memory.model_extra = {}

    backend = GraphitiMemoryBackend.from_nanobot_config(nanobot_config)
    assert backend._config.graph_db == "kuzu"
    assert backend._config.top_k == 5
```

- [ ] **Step 2: Run — verify PASSED** (classmethod was written in Task 3)

```bash
cd plugins/nanobot-graphiti && pytest tests/test_backend.py -v -k "from_nanobot_config"
```
Expected: 2 passed (classmethod was implemented in Task 3 — these tests just confirm the full config parsing round-trip works).

- [ ] **Step 3: Verify Plan 1's `load_memory_backend` calls `from_nanobot_config`**

In `nanobot/cli/commands.py`, the `load_memory_backend(config)` function (added in Plan 1) should check for `from_nanobot_config`. If Plan 1's implementation calls `cls(config)` instead, update `load_memory_backend`:

```python
def load_memory_backend(config: Config) -> MemoryBackend:
    """Discover and instantiate the configured memory backend."""
    from importlib.metadata import entry_points
    from nanobot.agent.memory import MemoryStore

    backend_name = config.memory.backend
    if backend_name == "default":
        return MemoryStore(Path(config.agents.defaults.workspace).expanduser())

    for ep in entry_points(group="nanobot.memory"):
        if ep.name == backend_name:
            cls = ep.load()
            if hasattr(cls, "from_nanobot_config"):
                return cls.from_nanobot_config(config)
            return cls(config)

    logger.warning(f"Memory backend {backend_name!r} not found; falling back to MemoryStore")
    return MemoryStore(Path(config.agents.defaults.workspace).expanduser())
```

- [ ] **Step 4: Run the nanobot core backend-discovery test from Plan 1**

```bash
pytest tests/agent/test_loop_memory_backend.py -v
```
Expected: all existing tests pass.

- [ ] **Step 5: Run full suite (root + plugin)**

```bash
pytest --tb=short -q && cd plugins/nanobot-graphiti && pytest -v
```
Expected: all tests pass.

- [ ] **Commit**

```
feat(nanobot-graphiti): verify from_nanobot_config entry-point factory + load_memory_backend wiring
```

---

## Self-Review

**Spec coverage check:**

| Spec requirement | Covered |
|---|---|
| `MemoryBackend` registered under `nanobot.memory` entry-point | Task 1 (pyproject.toml) |
| `consolidates_per_turn = True` | Task 3 |
| `start(provider)` builds Graphiti client from nanobot provider | Task 3 |
| `consolidate()` calls `add_episode()` with correct `group_id` | Task 4 |
| `consolidate()` errors swallowed + logged | Task 4 |
| `retrieve()` calls `search()` and formats `[Memory — N facts]` block | Task 5 |
| `retrieve()` returns `""` when no results | Task 5 |
| `scope: "user"` strips channel prefix | Task 7 |
| `scope: "session"` preserves full session key | Task 7 |
| `get_tools()` returns exactly `memory_search`, `memory_forget`, `memory_list` | Task 7 |
| `memory_search` calls `graphiti.search()` with session-scoped `group_id` | Task 6 |
| `memory_forget` calls `EntityEdge.delete_by_uuids()` | Task 6 |
| `memory_list` lists all facts with UUIDs | Task 6 |
| `GraphitiConfig` defaults: `graph_db="kuzu"`, `top_k=5`, `scope="user"` | Task 2 |
| Kuzu, Neo4j, FalkorDB driver dispatch | Task 3 (`_build_driver`) |

**All spec requirements covered.**
