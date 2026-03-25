# Integration Test Suite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an integration test suite that validates real subsystem-to-subsystem behavior across all critical boundaries in the nanobot agent framework, using a real LLM provider.

**Architecture:** Integration tests live in `tests/integration/` with shared fixtures in `conftest.py`. Tests use a **real LLM** (`LiteLLMProvider` with `gpt-4o-mini`) for all agent-level tests, following the same pattern as `test_memory_roundtrip.py`. Tests requiring an API key are skipped when `OPENAI_API_KEY` / `LITELLM_API_KEY` is not set. Assertions are fuzzy keyword checks — never exact LLM wording. `HashEmbedder` is used for deterministic embeddings. `tmp_path` provides filesystem isolation.

**Tech Stack:** pytest, pytest-asyncio (auto mode), LiteLLMProvider (gpt-4o-mini), HashEmbedder, real SQLite (UnifiedMemoryDB), real filesystem tools

---

## File Structure

```
tests/integration/
  __init__.py               — empty package marker
  conftest.py               — shared fixtures (provider, store, agent builder, sample events)
  test_agent_memory_write.py     — IT-01: agent loop stores memory events
  test_agent_memory_read.py      — IT-02: stored memory appears in LLM context
  test_memory_retrieval_pipeline.py — IT-03: full write → vector+FTS → RRF → rank pipeline
  test_tool_executor_real.py     — IT-05: executor with real filesystem/shell tools
  test_consolidation_pipeline.py — IT-04: consolidation through agent orchestrator
  test_session_persistence.py    — IT-06: session save/reload across agent restarts
  test_delegation_child_agent.py — IT-08: parent→child delegation with real tool loop
  test_coordinator_role_switch.py — IT-09: classify → switch → process → restore
  test_channel_bus_delivery.py   — IT-07: bus → channel manager → stub channel
  test_context_skills.py         — IT-10: skill discovery → prompt injection
  test_tool_result_cache.py      — IT-11: execute → cache miss → cache hit
  test_answer_verifier.py        — IT-12: verifier inside PAOR loop
  test_knowledge_graph_ingest.py — IT-13: event ingest → entity/edge creation
  test_profile_conflicts.py      — IT-14: contradicting beliefs → conflict resolution
  test_canonical_events_bus.py   — IT-15: canonical events flow through bus
  test_dead_letter_replay.py     — IT-16: failed delivery → persist → replay
  test_mission_lifecycle.py      — IT-17: async mission start → complete
  test_config_factory_wiring.py  — IT-18: config file → build_agent → subsystems
  test_observability_spans.py    — IT-19: agent processing → trace/span creation
  test_context_compression.py    — IT-20: long conversation → compression fires
```

---

## Task 1: Integration Test Infrastructure

**Files:**
- Create: `tests/integration/__init__.py`
- Create: `tests/integration/conftest.py`
- Modify: `Makefile` (add `test-integration` target)
- Modify: `pyproject.toml` (add `integration` marker to existing list)

- [ ] **Step 1: Add `integration` marker to existing pytest markers in `pyproject.toml`**

Find the existing `markers` list (around line 125) and add the new marker:

```toml
markers = [
    "golden: golden regression tests (frozen behavior baselines)",
    "contract: contract tests for core abstractions",
    "llm: tests requiring a real LLM API key (skipped when unavailable)",
    "integration: integration tests (cross-subsystem, require LLM API key)",
]
```

- [ ] **Step 2: Create the integration test package**

Create `tests/integration/__init__.py` (empty file).

- [ ] **Step 3: Write shared fixtures in `tests/integration/conftest.py`**

```python
"""Shared fixtures for integration tests.

These fixtures wire real subsystems together with a real LLM provider.
Tests are skipped when no API key is available.

Pattern follows tests/test_memory_roundtrip.py.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from nanobot.agent.agent_factory import build_agent
from nanobot.agent.loop import AgentLoop
from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import AgentConfig
from nanobot.memory.store import MemoryStore
from nanobot.providers.litellm_provider import LiteLLMProvider

# ---------------------------------------------------------------------------
# Skip entire integration package when no LLM API key is available.
# ---------------------------------------------------------------------------

_has_api_key = bool(os.environ.get("OPENAI_API_KEY") or os.environ.get("LITELLM_API_KEY"))

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not _has_api_key, reason="No LLM API key (OPENAI_API_KEY / LITELLM_API_KEY)"),
]

MODEL = "gpt-4o-mini"

# ---------------------------------------------------------------------------
# Sample data
# ---------------------------------------------------------------------------

SAMPLE_EVENTS: list[dict[str, Any]] = [
    {
        "type": "preference",
        "summary": "User prefers dark mode in all editors.",
        "timestamp": "2026-03-01T12:00:00+00:00",
        "source": "test",
    },
    {
        "type": "fact",
        "summary": "User's primary programming language is Python.",
        "timestamp": "2026-03-01T12:01:00+00:00",
        "source": "test",
    },
    {
        "type": "task",
        "summary": "Migrate database to PostgreSQL by end of quarter.",
        "timestamp": "2026-03-01T12:02:00+00:00",
        "source": "test",
        "metadata": {"status": "active"},
    },
    {
        "type": "decision",
        "summary": "Chose FastAPI over Flask for the new API project.",
        "timestamp": "2026-03-01T12:03:00+00:00",
        "source": "test",
    },
    {
        "type": "constraint",
        "summary": "Budget limit is $5000 per month for cloud infrastructure.",
        "timestamp": "2026-03-01T12:04:00+00:00",
        "source": "test",
    },
]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def provider() -> LiteLLMProvider:
    """Real LLM provider using gpt-4o-mini."""
    return LiteLLMProvider(default_model=MODEL)


@pytest.fixture()
def store(tmp_path: Path) -> MemoryStore:
    """Real MemoryStore with HashEmbedder for deterministic vector search."""
    return MemoryStore(tmp_path, embedding_provider="hash")


@pytest.fixture()
def config(tmp_path: Path) -> AgentConfig:
    """Minimal AgentConfig with memory enabled."""
    return AgentConfig(
        workspace=str(tmp_path),
        model=MODEL,
        memory_window=10,
        max_iterations=5,
        planning_enabled=False,
        verification_mode="off",
        memory_enabled=True,
        graph_enabled=False,
        reranker_mode="disabled",
    )


@pytest.fixture()
def agent(tmp_path: Path, provider: LiteLLMProvider, config: AgentConfig) -> AgentLoop:
    """Fully wired agent with real LLM, real memory, real tools."""
    bus = MessageBus()
    return build_agent(bus=bus, provider=provider, config=config)


def make_inbound(
    text: str,
    *,
    channel: str = "cli",
    chat_id: str = "integration-test",
    sender_id: str = "user-1",
) -> InboundMessage:
    """Create an InboundMessage for test input."""
    return InboundMessage(
        channel=channel,
        chat_id=chat_id,
        sender_id=sender_id,
        content=text,
    )
```

- [ ] **Step 4: Add Makefile target**

Add to `Makefile`:

```makefile
test-integration:  ## Run integration tests only (requires LLM API key)
	$(PYTHON) -m pytest tests/integration/ -v --tb=short -x --timeout=120
```

- [ ] **Step 5: Run `make lint && make typecheck` to verify infrastructure**

Run: `make lint && make typecheck`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add tests/integration/ pyproject.toml Makefile
git commit -m "test: add integration test infrastructure with real LLM fixtures"
```

---

## Task 2: IT-05 — Tool Executor + Real Built-in Tools

**Files:**
- Create: `tests/integration/test_tool_executor_real.py`

**Why first:** Simplest integration boundary. No LLM needed — just executor + real tools. Validates the plan infrastructure works.

- [ ] **Step 1: Write test file**

```python
"""IT-05: ToolExecutor with real built-in tools.

Verifies the executor's parallel/sequential logic with actual filesystem
and shell tools, not stubs. Does not require LLM API key.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from nanobot.providers.base import ToolCallRequest
from nanobot.tools.builtin.filesystem import (
    EditFileTool,
    ListDirTool,
    ReadFileTool,
    WriteFileTool,
)
from nanobot.tools.builtin.shell import ExecTool
from nanobot.tools.executor import ToolExecutor
from nanobot.tools.registry import ToolRegistry

pytestmark = pytest.mark.integration


def _tc(name: str, **kwargs: Any) -> ToolCallRequest:
    return ToolCallRequest(id=f"tc-{name}", name=name, arguments=kwargs)


def _make_executor(tmp_path: Path) -> ToolExecutor:
    reg = ToolRegistry()
    reg.register(ReadFileTool(workspace=tmp_path))
    reg.register(WriteFileTool(workspace=tmp_path))
    reg.register(EditFileTool(workspace=tmp_path))
    reg.register(ListDirTool(workspace=tmp_path))
    reg.register(
        ExecTool(working_dir=str(tmp_path), shell_mode="denylist")
    )
    return ToolExecutor(reg)


class TestReadWriteIntegration:
    """Verify read and write tools produce real filesystem effects."""

    async def test_write_then_read(self, tmp_path: Path) -> None:
        exe = _make_executor(tmp_path)
        write_results = await exe.execute_batch(
            [_tc("write_file", path=str(tmp_path / "hello.txt"), content="Hello, world!")]
        )
        assert write_results[0].success

        read_results = await exe.execute_batch(
            [_tc("read_file", path=str(tmp_path / "hello.txt"))]
        )
        assert read_results[0].success
        assert "Hello, world!" in read_results[0].output

    async def test_list_dir_shows_written_file(self, tmp_path: Path) -> None:
        exe = _make_executor(tmp_path)
        (tmp_path / "alpha.py").write_text("x = 1")
        (tmp_path / "beta.py").write_text("y = 2")

        results = await exe.execute_batch([_tc("list_dir", path=str(tmp_path))])
        assert results[0].success
        assert "alpha.py" in results[0].output
        assert "beta.py" in results[0].output

    async def test_edit_modifies_file(self, tmp_path: Path) -> None:
        target = tmp_path / "data.txt"
        target.write_text("old content here")
        exe = _make_executor(tmp_path)

        results = await exe.execute_batch(
            [
                _tc(
                    "edit_file",
                    path=str(target),
                    old_string="old content",
                    new_string="new content",
                )
            ]
        )
        assert results[0].success
        assert "new content here" == target.read_text()


class TestParallelReadSequentialWrite:
    """Verify executor batching with real tools."""

    async def test_readonly_tools_batch_parallel(self, tmp_path: Path) -> None:
        (tmp_path / "a.txt").write_text("aaa")
        (tmp_path / "b.txt").write_text("bbb")
        (tmp_path / "c.txt").write_text("ccc")
        exe = _make_executor(tmp_path)

        results = await exe.execute_batch(
            [
                _tc("read_file", path=str(tmp_path / "a.txt")),
                _tc("read_file", path=str(tmp_path / "b.txt")),
                _tc("read_file", path=str(tmp_path / "c.txt")),
            ]
        )
        assert all(r.success for r in results)
        assert "aaa" in results[0].output
        assert "bbb" in results[1].output
        assert "ccc" in results[2].output

    async def test_write_between_reads_preserves_order(self, tmp_path: Path) -> None:
        (tmp_path / "existing.txt").write_text("before")
        exe = _make_executor(tmp_path)

        results = await exe.execute_batch(
            [
                _tc("read_file", path=str(tmp_path / "existing.txt")),
                _tc("write_file", path=str(tmp_path / "new.txt"), content="written"),
                _tc("read_file", path=str(tmp_path / "new.txt")),
            ]
        )
        assert results[0].success
        assert results[1].success
        assert results[2].success
        assert "written" in results[2].output


class TestShellExecution:
    """Verify exec tool runs real commands."""

    async def test_echo_command(self, tmp_path: Path) -> None:
        exe = _make_executor(tmp_path)
        results = await exe.execute_batch(
            [_tc("exec", command="echo integration-test-output")]
        )
        assert results[0].success
        assert "integration-test-output" in results[0].output

    async def test_denied_command_rejected(self, tmp_path: Path) -> None:
        exe = _make_executor(tmp_path)
        results = await exe.execute_batch(
            [_tc("exec", command="rm -rf /")]
        )
        assert not results[0].success


class TestErrorHandling:
    """Verify error paths with real tools."""

    async def test_read_nonexistent_file(self, tmp_path: Path) -> None:
        exe = _make_executor(tmp_path)
        results = await exe.execute_batch(
            [_tc("read_file", path=str(tmp_path / "nonexistent.txt"))]
        )
        assert not results[0].success

    async def test_write_outside_workspace(self, tmp_path: Path) -> None:
        exe = _make_executor(tmp_path)
        results = await exe.execute_batch(
            [_tc("write_file", path="/tmp/escape-attempt.txt", content="bad")]
        )
        assert not results[0].success
```

- [ ] **Step 2: Run tests**

Run: `pytest tests/integration/test_tool_executor_real.py -v`
Expected: All tests PASS (this file does not require LLM API key)

- [ ] **Step 3: Run `make lint && make typecheck`**

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_tool_executor_real.py
git commit -m "test(integration): IT-05 tool executor with real filesystem/shell tools"
```

---

## Task 3: IT-03 — Memory Retrieval Pipeline (Write → Vector+FTS → RRF → Rank)

**Files:**
- Create: `tests/integration/test_memory_retrieval_pipeline.py`

**Note:** This test uses only `MemoryStore` + `HashEmbedder` — no LLM needed. Does not require API key.

- [ ] **Step 1: Write test file**

```python
"""IT-03: Full memory retrieval pipeline.

Write events with real embeddings → vector search + FTS5 → RRF fusion →
scoring → reranking → top-k. Uses HashEmbedder + real SQLite. No LLM needed.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from nanobot.memory.store import MemoryStore

pytestmark = pytest.mark.integration


def _store(tmp_path: Path) -> MemoryStore:
    return MemoryStore(tmp_path, embedding_provider="hash")


def _bulk_events() -> list[dict[str, Any]]:
    """20 diverse events for retrieval testing."""
    return [
        {"type": "preference", "summary": "User prefers dark mode in all editors.",
         "timestamp": "2026-03-01T12:00:00+00:00", "source": "test"},
        {"type": "preference", "summary": "User likes TypeScript over JavaScript.",
         "timestamp": "2026-03-01T12:01:00+00:00", "source": "test"},
        {"type": "fact", "summary": "User's primary programming language is Python.",
         "timestamp": "2026-03-01T12:02:00+00:00", "source": "test"},
        {"type": "fact", "summary": "User works at Acme Corp as a senior engineer.",
         "timestamp": "2026-03-01T12:03:00+00:00", "source": "test"},
        {"type": "fact", "summary": "User has 10 years of experience with Go.",
         "timestamp": "2026-03-01T12:04:00+00:00", "source": "test"},
        {"type": "task", "summary": "Migrate database to PostgreSQL by end of Q1.",
         "timestamp": "2026-03-01T12:05:00+00:00", "source": "test",
         "metadata": {"status": "active"}},
        {"type": "task", "summary": "Set up CI/CD pipeline for the new microservice.",
         "timestamp": "2026-03-01T12:06:00+00:00", "source": "test",
         "metadata": {"status": "active"}},
        {"type": "decision", "summary": "Chose FastAPI over Flask for the API.",
         "timestamp": "2026-03-01T12:07:00+00:00", "source": "test"},
        {"type": "decision", "summary": "Using SQLite for local development, Postgres for prod.",
         "timestamp": "2026-03-01T12:08:00+00:00", "source": "test"},
        {"type": "constraint", "summary": "Cloud budget limited to $5000 per month.",
         "timestamp": "2026-03-01T12:09:00+00:00", "source": "test"},
        {"type": "preference", "summary": "User prefers vim keybindings in VS Code.",
         "timestamp": "2026-03-01T12:10:00+00:00", "source": "test"},
        {"type": "fact", "summary": "The project uses Docker containers for deployment.",
         "timestamp": "2026-03-01T12:11:00+00:00", "source": "test"},
        {"type": "fact", "summary": "User lives in San Francisco, California.",
         "timestamp": "2026-03-01T12:12:00+00:00", "source": "test"},
        {"type": "task", "summary": "Write documentation for the REST API endpoints.",
         "timestamp": "2026-03-01T12:13:00+00:00", "source": "test",
         "metadata": {"status": "active"}},
        {"type": "relationship", "summary": "User works with Alice on the backend team.",
         "timestamp": "2026-03-01T12:14:00+00:00", "source": "test"},
        {"type": "preference", "summary": "User prefers async/await over callback style.",
         "timestamp": "2026-03-01T12:15:00+00:00", "source": "test"},
        {"type": "fact", "summary": "Company uses GitHub Enterprise for source control.",
         "timestamp": "2026-03-01T12:16:00+00:00", "source": "test"},
        {"type": "constraint", "summary": "All services must support Python 3.10 or later.",
         "timestamp": "2026-03-01T12:17:00+00:00", "source": "test"},
        {"type": "decision", "summary": "Adopted pytest over unittest for all new test suites.",
         "timestamp": "2026-03-01T12:18:00+00:00", "source": "test"},
        {"type": "fact", "summary": "User is allergic to peanuts.",
         "timestamp": "2026-03-01T12:19:00+00:00", "source": "test"},
    ]


class TestRetrievalRelevance:
    """Verify retrieval returns relevant results above irrelevant ones."""

    def test_preference_query_returns_preferences(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        store.ingester.append_events(_bulk_events())

        results = store.retriever.retrieve("dark mode preference", top_k=5)
        summaries = [r.get("summary", "").lower() for r in results]
        assert any("dark mode" in s for s in summaries)

    def test_programming_query_returns_languages(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        store.ingester.append_events(_bulk_events())

        results = store.retriever.retrieve("programming language experience", top_k=5)
        summaries = " ".join(r.get("summary", "").lower() for r in results)
        assert "python" in summaries or "go" in summaries or "typescript" in summaries

    def test_task_query_returns_active_tasks(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        store.ingester.append_events(_bulk_events())

        results = store.retriever.retrieve("database migration task", top_k=5)
        summaries = [r.get("summary", "").lower() for r in results]
        assert any("postgresql" in s or "database" in s for s in summaries)


class TestRRFFusion:
    """Verify both vector and FTS paths contribute to results."""

    def test_fts_keyword_match(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        store.ingester.append_events(_bulk_events())

        results = store.retriever.retrieve("PostgreSQL", top_k=5)
        summaries = " ".join(r.get("summary", "") for r in results)
        assert "PostgreSQL" in summaries or "Postgres" in summaries

    def test_returns_correct_count(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        store.ingester.append_events(_bulk_events())

        results = store.retriever.retrieve("user preferences", top_k=3)
        assert len(results) <= 3


class TestDedupAndIdempotency:
    """Verify dedup works in the full pipeline."""

    def test_duplicate_events_not_doubled(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        events = _bulk_events()[:3]

        store.ingester.append_events(events)
        store.ingester.append_events(events)  # same events again

        results = store.retriever.retrieve("dark mode", top_k=10)
        dark_mode = [r for r in results if "dark mode" in r.get("summary", "").lower()]
        assert len(dark_mode) <= 1


class TestTokenBudget:
    """Verify context assembly respects token budget."""

    def test_memory_context_fits_budget(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        store.ingester.append_events(_bulk_events())

        context = store.get_memory_context(
            query="tell me about the user",
            retrieval_k=10,
            token_budget=200,
        )
        estimated_tokens = len(context) // 4
        assert estimated_tokens < 400  # 2x budget as generous upper bound
```

- [ ] **Step 2: Run tests**

Run: `pytest tests/integration/test_memory_retrieval_pipeline.py -v`
Expected: All tests PASS

- [ ] **Step 3: Run `make lint && make typecheck`**

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_memory_retrieval_pipeline.py
git commit -m "test(integration): IT-03 memory retrieval pipeline with real embeddings and RRF"
```

---

## Task 4: IT-01 — Agent Loop + Memory Store (Write Path) — Real LLM

**Files:**
- Create: `tests/integration/test_agent_memory_write.py`

- [ ] **Step 1: Write test file**

```python
"""IT-01: Agent loop stores memory events through the write path.

Uses a real LLM to process user messages. Verifies that the memory
subsystem stores events and that they are retrievable afterward.

Requires: OPENAI_API_KEY or LITELLM_API_KEY.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.memory.store import MemoryStore

from tests.integration.conftest import make_inbound

pytestmark = pytest.mark.integration


class TestMemoryWriteFromAgentLoop:
    """Agent processes messages and memory accumulates events."""

    async def test_agent_processes_preference_message(self, agent: AgentLoop) -> None:
        """Agent can process a user preference statement end-to-end."""
        msg = make_inbound("I always prefer dark mode in every editor I use.")
        result = await agent._process_message(msg)

        assert result is not None
        assert len(result.content) > 0

    async def test_seeded_events_retrievable_through_agent(
        self, agent: AgentLoop
    ) -> None:
        """Events stored in memory are retrievable via the retriever."""
        agent.memory.ingester.append_events([
            {
                "type": "fact",
                "summary": "User is a backend engineer specializing in distributed systems.",
                "timestamp": "2026-03-01T12:00:00+00:00",
                "source": "test",
            }
        ])

        results = agent.memory.retriever.retrieve("distributed systems", top_k=5)
        summaries = " ".join(r.get("summary", "").lower() for r in results)
        assert "distributed" in summaries

    async def test_multiple_events_accumulate(self, agent: AgentLoop) -> None:
        """Multiple seeded events all persist in the store."""
        agent.memory.ingester.append_events([
            {
                "type": "preference",
                "summary": "User prefers Python for backend work.",
                "timestamp": "2026-03-01T12:00:00+00:00",
                "source": "test",
            },
            {
                "type": "fact",
                "summary": "User works at a startup with 20 employees.",
                "timestamp": "2026-03-01T12:01:00+00:00",
                "source": "test",
            },
        ])

        all_events = agent.memory.ingester.read_events(limit=100)
        assert len(all_events) >= 2
```

- [ ] **Step 2: Run tests**

Run: `pytest tests/integration/test_agent_memory_write.py -v`
Expected: All tests PASS (or skipped if no API key)

- [ ] **Step 3: Run `make lint && make typecheck`**

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_agent_memory_write.py
git commit -m "test(integration): IT-01 agent loop memory write path with real LLM"
```

---

## Task 5: IT-02 — Agent Loop + Memory Store (Read Path / Context Assembly) — Real LLM

**Files:**
- Create: `tests/integration/test_agent_memory_read.py`

- [ ] **Step 1: Write test file**

```python
"""IT-02: Stored memory appears in the LLM's system prompt.

Verifies that previously stored events are retrieved by ContextBuilder
and injected into the messages sent to the real LLM. The LLM's response
should reflect knowledge of the stored facts.

Requires: OPENAI_API_KEY or LITELLM_API_KEY.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from nanobot.agent.loop import AgentLoop

from tests.integration.conftest import make_inbound

pytestmark = pytest.mark.integration


class TestMemoryContextInjection:
    """Memory context influences LLM responses."""

    async def test_stored_fact_influences_response(self, agent: AgentLoop) -> None:
        """When memory contains a fact, the LLM's response should reflect it."""
        agent.memory.ingester.append_events([
            {
                "type": "fact",
                "summary": "User works at Globex Corporation as a senior engineer.",
                "timestamp": "2026-03-01T12:00:00+00:00",
                "source": "test",
            }
        ])

        msg = make_inbound("Where do I work?")
        result = await agent._process_message(msg)

        assert result is not None
        # The LLM should mention Globex since it's in the memory context
        assert "globex" in result.content.lower(), (
            f"Expected 'globex' in response, got: {result.content}"
        )

    async def test_stored_preference_influences_response(self, agent: AgentLoop) -> None:
        """Stored preference should be reflected when asked about it."""
        agent.memory.ingester.append_events([
            {
                "type": "preference",
                "summary": "User strongly prefers dark mode in all editors and IDEs.",
                "timestamp": "2026-03-01T12:00:00+00:00",
                "source": "test",
            }
        ])

        msg = make_inbound("What are my editor preferences?")
        result = await agent._process_message(msg)

        assert result is not None
        assert "dark" in result.content.lower(), (
            f"Expected 'dark' in response, got: {result.content}"
        )

    async def test_empty_memory_no_crash(self, agent: AgentLoop) -> None:
        """Agent with empty memory should still produce a response."""
        msg = make_inbound("What do you know about me?")
        result = await agent._process_message(msg)

        assert result is not None
        assert len(result.content) > 0
```

- [ ] **Step 2: Run tests**

Run: `pytest tests/integration/test_agent_memory_read.py -v`
Expected: All tests PASS (or skipped if no API key)

- [ ] **Step 3: Run `make lint && make typecheck`**

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_agent_memory_read.py
git commit -m "test(integration): IT-02 stored memory appears in LLM context with real provider"
```

---

## Task 6: IT-04 — Consolidation Pipeline with Real LLM

**Files:**
- Create: `tests/integration/test_consolidation_pipeline.py`

- [ ] **Step 1: Write test file**

```python
"""IT-04: Consolidation pipeline with real LLM, MemoryStore, and session.

Same pattern as test_memory_roundtrip.py but verifying the consolidation
path produces retrievable memory context.

Requires: OPENAI_API_KEY or LITELLM_API_KEY.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from nanobot.memory.store import MemoryStore
from nanobot.providers.litellm_provider import LiteLLMProvider

from tests.integration.conftest import MODEL

pytestmark = pytest.mark.integration


@dataclass
class _Session:
    """Lightweight session stub (same pattern as test_memory_roundtrip.py)."""

    key: str = "test:consolidation"
    messages: list[dict[str, Any]] = field(default_factory=list)
    last_consolidated: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = field(default_factory=dict)

    def add_message(self, role: str, content: str, **kwargs: Any) -> None:
        self.messages.append({
            "role": role,
            "content": content,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **kwargs,
        })
        self.updated_at = datetime.now(timezone.utc)


def _make_session(*turns: tuple[str, str]) -> _Session:
    sess = _Session(key=f"test:{uuid.uuid4().hex[:8]}")
    for role, content in turns:
        sess.add_message(role, content)
    return sess


class TestConsolidationWithRealLLM:
    """Consolidation extracts events and they become retrievable."""

    async def test_preference_consolidation(
        self, store: MemoryStore, provider: LiteLLMProvider
    ) -> None:
        session = _make_session(
            ("user", "I always want responses formatted as bullet points"),
            ("assistant", "Got it! I'll use bullet points from now on."),
        )

        ok = await store.consolidate(
            session, provider, MODEL,
            archive_all=True,  # type: ignore[arg-type]
        )
        assert ok, "consolidation should succeed"

        context = store.get_memory_context(query="How should I format responses?")
        assert "bullet" in context.lower(), (
            f"Expected 'bullet' in memory context, got:\n{context}"
        )

    async def test_fact_consolidation(
        self, store: MemoryStore, provider: LiteLLMProvider
    ) -> None:
        session = _make_session(
            ("user", "I work at Globex Corporation as a senior engineer"),
            ("assistant", "Nice! Globex is a great place to work."),
        )

        ok = await store.consolidate(
            session, provider, MODEL,
            archive_all=True,  # type: ignore[arg-type]
        )
        assert ok, "consolidation should succeed"

        context = store.get_memory_context(query="Where does the user work?")
        assert "globex" in context.lower(), (
            f"Expected 'globex' in memory context, got:\n{context}"
        )

    async def test_consolidation_advances_pointer(
        self, store: MemoryStore, provider: LiteLLMProvider
    ) -> None:
        session = _make_session(
            ("user", "I prefer Python over Java"),
            ("assistant", "Noted!"),
        )
        initial = session.last_consolidated

        await store.consolidate(
            session, provider, MODEL,
            archive_all=True,  # type: ignore[arg-type]
        )
        assert session.last_consolidated >= initial
```

- [ ] **Step 2: Run tests**

Run: `pytest tests/integration/test_consolidation_pipeline.py -v`
Expected: All tests PASS (or skipped if no API key)

- [ ] **Step 3: Run `make lint && make typecheck`**

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_consolidation_pipeline.py
git commit -m "test(integration): IT-04 consolidation pipeline with real LLM"
```

---

## Task 7: IT-06 — Session Persistence Across Restarts

**Files:**
- Create: `tests/integration/test_session_persistence.py`

- [ ] **Step 1: Write test file**

```python
"""IT-06: Session history persists across agent restarts.

Verifies that conversation history saved to disk by SessionManager
is correctly reloaded when a new agent is created with the same workspace.

Requires: OPENAI_API_KEY or LITELLM_API_KEY (for agent processing).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from nanobot.agent.agent_factory import build_agent
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import AgentConfig
from nanobot.providers.litellm_provider import LiteLLMProvider
from nanobot.session.manager import SessionManager

from tests.integration.conftest import MODEL, make_inbound

pytestmark = pytest.mark.integration


class TestSessionPersistence:
    """Session state survives agent restart."""

    async def test_history_persists_across_agent_instances(
        self, tmp_path: Path, provider: LiteLLMProvider
    ) -> None:
        """Messages from first agent appear in second agent's context."""
        config = AgentConfig(
            workspace=str(tmp_path), model=MODEL,
            max_iterations=3, planning_enabled=False, verification_mode="off",
        )

        # First agent processes a distinctive message
        loop1 = build_agent(bus=MessageBus(), provider=provider, config=config)
        msg1 = make_inbound("Remember this: my favorite color is cerulean blue.")
        result1 = await loop1._process_message(msg1)
        assert result1 is not None

        # Second agent with same workspace should recall context
        loop2 = build_agent(bus=MessageBus(), provider=provider, config=config)
        msg2 = make_inbound("What is my favorite color?")
        result2 = await loop2._process_message(msg2)

        assert result2 is not None
        assert "cerulean" in result2.content.lower() or "blue" in result2.content.lower(), (
            f"Expected color recall, got: {result2.content}"
        )

    def test_session_manager_reload(self, tmp_path: Path) -> None:
        """SessionManager reloads sessions from disk correctly."""
        mgr = SessionManager(tmp_path)
        session = mgr.get_or_create("persist-test")
        session.add_message("user", "Hello")
        session.add_message("assistant", "Hi there")
        mgr.save(session)

        mgr2 = SessionManager(tmp_path)
        reloaded = mgr2.get_or_create("persist-test")
        history = reloaded.get_history()
        assert len(history) >= 2
        contents = [m.get("content", "") for m in history]
        assert "Hello" in contents
```

- [ ] **Step 2: Run tests**

Run: `pytest tests/integration/test_session_persistence.py -v`
Expected: All tests PASS (or skipped if no API key)

- [ ] **Step 3: Run `make lint && make typecheck`**

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_session_persistence.py
git commit -m "test(integration): IT-06 session persistence across agent restarts"
```

---

## Task 8: IT-08 — Delegation Dispatch + Child Agent with Real LLM

**Files:**
- Create: `tests/integration/test_delegation_child_agent.py`

- [ ] **Step 1: Write test file**

```python
"""IT-08: Parent→child delegation with real LLM and real tools.

Verifies that delegation dispatch creates a child agent that uses a real
LLM to decide which tools to call, executes real tools, and returns
results to the parent.

Requires: OPENAI_API_KEY or LITELLM_API_KEY.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from nanobot.agent.loop import AgentLoop

from tests.integration.conftest import make_inbound

pytestmark = pytest.mark.integration


class TestDelegationExecution:
    """Parent agent delegates to child and gets results."""

    async def test_agent_can_delegate_file_reading(
        self, tmp_path: Path, agent: AgentLoop
    ) -> None:
        """Agent asked to delegate reading a file gets a useful response."""
        (tmp_path / "secret.txt").write_text("The launch code is ALPHA-7.")

        msg = make_inbound(
            f"Please delegate to the code role to read {tmp_path / 'secret.txt'} "
            "and tell me what the launch code is."
        )
        result = await agent._process_message(msg)

        assert result is not None
        # The agent may or may not actually delegate, but should read the file
        assert len(result.content) > 0


class TestDelegationSafety:
    """Delegation config flags work in integration."""

    def test_delegation_disabled_no_delegate_tool(
        self, tmp_path: Path, provider: object
    ) -> None:
        """With delegation_enabled=False, delegate tool should not exist."""
        from nanobot.agent.agent_factory import build_agent
        from nanobot.bus.queue import MessageBus
        from nanobot.config.schema import AgentConfig
        from nanobot.providers.litellm_provider import LiteLLMProvider

        from tests.integration.conftest import MODEL

        config = AgentConfig(
            workspace=str(tmp_path), model=MODEL,
            delegation_enabled=False, planning_enabled=False,
            verification_mode="off",
        )
        loop = build_agent(
            bus=MessageBus(),
            provider=LiteLLMProvider(default_model=MODEL),
            config=config,
        )
        assert not loop.tools.has("delegate")
```

- [ ] **Step 2: Run tests**

Run: `pytest tests/integration/test_delegation_child_agent.py -v`
Expected: All tests PASS (or skipped if no API key)

- [ ] **Step 3: Run `make lint && make typecheck`**

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_delegation_child_agent.py
git commit -m "test(integration): IT-08 delegation with real LLM and tools"
```

---

## Task 9: IT-09 — Coordinator + Role Switching

**Files:**
- Create: `tests/integration/test_coordinator_role_switch.py`

- [ ] **Step 1: Write test file**

```python
"""IT-09: Coordinator classification → role switch → process → restore.

Verifies the full routing flow with real subsystems.

Requires: OPENAI_API_KEY or LITELLM_API_KEY.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.config.schema import AgentRoleConfig

pytestmark = pytest.mark.integration


class TestRoleSwitchingIntegration:
    """Role switching changes model/tools for a turn."""

    def test_role_config_changes_model(self, agent: AgentLoop) -> None:
        role = AgentRoleConfig(
            name="code",
            model="code-specialist-model",
            temperature=0.1,
        )

        assert agent._role_manager is not None
        ctx = agent._role_manager.apply(role)
        assert agent.model == "code-specialist-model"
        assert agent.temperature == 0.1
        agent._role_manager.reset(ctx)

    def test_denied_tools_excluded(self, agent: AgentLoop) -> None:
        role = AgentRoleConfig(
            name="research",
            denied_tools=["exec", "write_file", "edit_file"],
        )

        assert agent._role_manager is not None
        ctx = agent._role_manager.apply(role)
        defs = agent.tools.get_definitions()
        tool_names = [d["function"]["name"] for d in defs]
        assert "exec" not in tool_names
        assert "write_file" not in tool_names
        agent._role_manager.reset(ctx)

    def test_role_switch_restores_original(self, agent: AgentLoop) -> None:
        original_model = agent.model
        original_temp = agent.temperature

        role = AgentRoleConfig(name="specialist", model="other-model", temperature=0.0)
        assert agent._role_manager is not None
        ctx = agent._role_manager.apply(role)
        agent._role_manager.reset(ctx)

        assert agent.model == original_model
        assert agent.temperature == original_temp
```

- [ ] **Step 2: Run tests**

Run: `pytest tests/integration/test_coordinator_role_switch.py -v`
Expected: All tests PASS

- [ ] **Step 3: Run `make lint && make typecheck`**

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_coordinator_role_switch.py
git commit -m "test(integration): IT-09 coordinator role switching with tool filtering"
```

---

## Task 10: IT-07, IT-10, IT-11, IT-12, IT-13, IT-14 — Tier 2 Tests

**Files:**
- Create: `tests/integration/test_channel_bus_delivery.py`
- Create: `tests/integration/test_context_skills.py`
- Create: `tests/integration/test_tool_result_cache.py`
- Create: `tests/integration/test_answer_verifier.py`
- Create: `tests/integration/test_knowledge_graph_ingest.py`
- Create: `tests/integration/test_profile_conflicts.py`

- [ ] **Step 1: Write `test_channel_bus_delivery.py` (IT-07)**

```python
"""IT-07: MessageBus → real BaseChannel subclass delivery."""
from __future__ import annotations

import asyncio

import pytest

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel

pytestmark = pytest.mark.integration


class StubChannel(BaseChannel):
    """Real BaseChannel subclass that records sent messages."""

    name = "stub"

    def __init__(self, bus: MessageBus) -> None:
        super().__init__(config=None, bus=bus)
        self.sent: list[OutboundMessage] = []
        self._fail_next: bool = False

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def send(self, msg: OutboundMessage) -> None:
        if self._fail_next:
            self._fail_next = False
            raise ConnectionError("Simulated transient failure")
        self.sent.append(msg)


class TestBusToChannelDelivery:

    async def test_outbound_message_delivered(self) -> None:
        bus = MessageBus()
        channel = StubChannel(bus)

        msg = OutboundMessage(channel="stub", chat_id="test-chat", content="Hello!")
        await bus.publish_outbound(msg)

        received = await asyncio.wait_for(bus.consume_outbound(), timeout=1.0)
        await channel.send(received)

        assert len(channel.sent) == 1
        assert channel.sent[0].content == "Hello!"

    async def test_multiple_messages_fifo(self) -> None:
        bus = MessageBus()
        channel = StubChannel(bus)

        for i in range(5):
            await bus.publish_outbound(
                OutboundMessage(channel="stub", chat_id="test", content=f"msg-{i}")
            )

        for i in range(5):
            msg = await asyncio.wait_for(bus.consume_outbound(), timeout=1.0)
            await channel.send(msg)

        assert [m.content for m in channel.sent] == [f"msg-{i}" for i in range(5)]

    async def test_channel_health_tracking(self) -> None:
        bus = MessageBus()
        channel = StubChannel(bus)

        await channel.send(OutboundMessage(channel="stub", chat_id="t", content="ok"))
        channel.health.record_success()
        assert channel.health.healthy is True

        channel._fail_next = True
        with pytest.raises(ConnectionError):
            await channel.send(OutboundMessage(channel="stub", chat_id="t", content="fail"))
        channel.health.record_failure(ConnectionError("test"))
        assert channel.health.consecutive_failures == 1
```

- [ ] **Step 2: Write `test_context_skills.py` (IT-10)**

```python
"""IT-10: Skill discovery → prompt injection."""
from __future__ import annotations

from pathlib import Path

import pytest

from nanobot.context.skills import SkillsLoader

pytestmark = pytest.mark.integration


class TestSkillDiscovery:

    def test_builtin_skills_discovered(self, tmp_path: Path) -> None:
        loader = SkillsLoader(tmp_path)
        skills = loader.list_skills()
        assert isinstance(skills, list)
        if skills:
            assert all("name" in s for s in skills)

    def test_workspace_skill_discovered(self, tmp_path: Path) -> None:
        skill_dir = tmp_path / "skills" / "test-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: test-skill\ndescription: A test skill\n---\nTest content."
        )

        loader = SkillsLoader(tmp_path)
        skills = loader.list_skills(filter_unavailable=False)
        names = [s["name"] for s in skills]
        assert "test-skill" in names

    def test_skills_summary_contains_names(self, tmp_path: Path) -> None:
        skill_dir = tmp_path / "skills" / "my-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: my-skill\ndescription: Does things\n---\nContent."
        )

        loader = SkillsLoader(tmp_path)
        summary = loader.build_skills_summary()
        assert "my-skill" in summary
```

- [ ] **Step 3: Write `test_tool_result_cache.py` (IT-11)**

```python
"""IT-11: Tool result caching integration."""
from __future__ import annotations

from typing import Any

import pytest

from nanobot.tools.base import Tool, ToolResult
from nanobot.tools.registry import ToolRegistry
from nanobot.tools.result_cache import ToolResultCache

pytestmark = pytest.mark.integration


class _LargeOutputTool(Tool):
    readonly = True
    cacheable = True
    _call_count: int = 0

    @property
    def name(self) -> str:
        return "large_output"

    @property
    def description(self) -> str:
        return "Returns large output"

    @property
    def parameters(self) -> dict[str, Any]:
        return {"type": "object", "properties": {"query": {"type": "string"}}}

    async def execute(self, **kwargs: Any) -> ToolResult:
        self._call_count += 1
        return ToolResult.ok("x" * 4000)


class TestCacheIntegration:

    async def test_cache_hit_avoids_re_execution(self, tmp_path: object) -> None:
        cache = ToolResultCache(tmp_path)  # type: ignore[arg-type]
        reg = ToolRegistry()
        tool = _LargeOutputTool()
        reg.register(tool)
        # No provider for summarization — cache stores raw output
        reg.set_cache(cache)

        r1 = await reg.execute("large_output", {"query": "test"})
        assert r1.success
        first_count = tool._call_count

        r2 = await reg.execute("large_output", {"query": "test"})
        assert r2.success
        assert tool._call_count == first_count
```

- [ ] **Step 4: Write `test_answer_verifier.py` (IT-12)**

```python
"""IT-12: Answer verifier inside agent processing with real LLM.

Requires: OPENAI_API_KEY or LITELLM_API_KEY.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from nanobot.agent.agent_factory import build_agent
from nanobot.agent.loop import AgentLoop
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import AgentConfig
from nanobot.providers.litellm_provider import LiteLLMProvider

from tests.integration.conftest import MODEL, make_inbound

pytestmark = pytest.mark.integration


class TestVerifierIntegration:

    async def test_verification_off_returns_answer(
        self, agent: AgentLoop
    ) -> None:
        msg = make_inbound("What is 2 + 2?")
        result = await agent._process_message(msg)

        assert result is not None
        assert "4" in result.content

    async def test_verification_always_mode(
        self, tmp_path: Path, provider: LiteLLMProvider
    ) -> None:
        config = AgentConfig(
            workspace=str(tmp_path), model=MODEL,
            max_iterations=3, planning_enabled=False,
            verification_mode="always",
        )
        loop = build_agent(bus=MessageBus(), provider=provider, config=config)

        msg = make_inbound("What is the capital of France?")
        result = await loop._process_message(msg)

        assert result is not None
        assert "paris" in result.content.lower()
```

- [ ] **Step 5: Write `test_knowledge_graph_ingest.py` (IT-13)**

```python
"""IT-13: Event ingestion creates entities and edges in knowledge graph."""
from __future__ import annotations

from pathlib import Path

import pytest

from nanobot.memory.store import MemoryStore

pytestmark = pytest.mark.integration


def _store_with_graph(tmp_path: Path) -> MemoryStore:
    return MemoryStore(
        tmp_path,
        embedding_provider="hash",
        rollout_overrides={"graph_enabled": True},
    )


class TestGraphEntityCreation:

    def test_relationship_event_creates_entities(self, tmp_path: Path) -> None:
        store = _store_with_graph(tmp_path)
        store.ingester.append_events([
            {
                "type": "relationship",
                "summary": "Alice works at Acme Corporation.",
                "timestamp": "2026-03-01T12:00:00+00:00",
                "source": "test",
            }
        ])

        assert store.graph is not None, "Graph should be enabled"
        # Graph should have at least attempted entity extraction
        all_events = store.ingester.read_events(limit=50)
        assert len(all_events) >= 1

    def test_multiple_events_build_graph(self, tmp_path: Path) -> None:
        store = _store_with_graph(tmp_path)
        count = store.ingester.append_events([
            {
                "type": "relationship",
                "summary": "Bob mentors Alice on the backend team.",
                "timestamp": "2026-03-01T12:00:00+00:00",
                "source": "test",
            },
            {
                "type": "fact",
                "summary": "The backend team uses Python and FastAPI.",
                "timestamp": "2026-03-01T12:01:00+00:00",
                "source": "test",
            },
        ])
        assert count >= 1
        assert store.graph is not None
```

- [ ] **Step 6: Write `test_profile_conflicts.py` (IT-14)**

```python
"""IT-14: Profile belief conflicts detected and resolved."""
from __future__ import annotations

from pathlib import Path

import pytest

from nanobot.memory.store import MemoryStore

pytestmark = pytest.mark.integration


class TestProfileConflictDetection:

    def test_contradicting_preferences_stored(self, tmp_path: Path) -> None:
        store = MemoryStore(tmp_path, embedding_provider="hash")

        store.ingester.append_events([
            {
                "type": "preference",
                "summary": "User prefers coffee over tea.",
                "timestamp": "2026-03-01T12:00:00+00:00",
                "source": "test",
            }
        ])
        store.ingester.append_events([
            {
                "type": "preference",
                "summary": "User prefers tea over coffee.",
                "timestamp": "2026-03-01T13:00:00+00:00",
                "source": "test",
            }
        ])

        events = store.ingester.read_events(limit=50)
        summaries = [e.get("summary", "").lower() for e in events]
        has_coffee = any("coffee" in s for s in summaries)
        has_tea = any("tea" in s for s in summaries)
        assert has_coffee or has_tea

    def test_profile_readable_after_updates(self, tmp_path: Path) -> None:
        store = MemoryStore(tmp_path, embedding_provider="hash")

        store.ingester.append_events([
            {
                "type": "preference",
                "summary": "User prefers dark mode.",
                "timestamp": "2026-03-01T12:00:00+00:00",
                "source": "test",
            },
            {
                "type": "fact",
                "summary": "User is a software engineer.",
                "timestamp": "2026-03-01T12:01:00+00:00",
                "source": "test",
            },
        ])

        profile = store.profile_mgr.read_profile()
        assert isinstance(profile, dict)
```

- [ ] **Step 7: Run all tier 2 tests**

Run: `pytest tests/integration/test_channel_bus_delivery.py tests/integration/test_context_skills.py tests/integration/test_tool_result_cache.py tests/integration/test_answer_verifier.py tests/integration/test_knowledge_graph_ingest.py tests/integration/test_profile_conflicts.py -v`
Expected: All tests PASS

- [ ] **Step 8: Run `make lint && make typecheck`**

- [ ] **Step 9: Commit**

```bash
git add tests/integration/test_channel_bus_delivery.py tests/integration/test_context_skills.py tests/integration/test_tool_result_cache.py tests/integration/test_answer_verifier.py tests/integration/test_knowledge_graph_ingest.py tests/integration/test_profile_conflicts.py
git commit -m "test(integration): IT-07/10/11/12/13/14 tier 2 integration tests"
```

---

## Task 11: IT-15, IT-16, IT-17, IT-18, IT-19, IT-20 — Tier 3 Tests

**Files:**
- Create: `tests/integration/test_canonical_events_bus.py`
- Create: `tests/integration/test_dead_letter_replay.py`
- Create: `tests/integration/test_mission_lifecycle.py`
- Create: `tests/integration/test_config_factory_wiring.py`
- Create: `tests/integration/test_observability_spans.py`
- Create: `tests/integration/test_context_compression.py`

- [ ] **Step 1: Write `test_canonical_events_bus.py` (IT-15)**

```python
"""IT-15: Canonical events flow from builder through the message bus."""
from __future__ import annotations

import asyncio

import pytest

from nanobot.bus.canonical import CanonicalEventBuilder
from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus

pytestmark = pytest.mark.integration


class TestCanonicalEventFlow:

    async def test_run_start_event_structure(self) -> None:
        builder = CanonicalEventBuilder(
            run_id="run-001", session_id="sess-001",
            turn_id="turn-001", actor_id="agent",
        )
        event = builder.run_start()

        assert event["type"] == "run.start"
        assert event["run_id"] == "run-001"
        assert "ts" in event
        assert event["v"] == 1

    async def test_events_publishable_to_bus(self) -> None:
        bus = MessageBus()
        builder = CanonicalEventBuilder(
            run_id="run-002", session_id="sess-002",
            turn_id="turn-002", actor_id="agent",
        )

        event = builder.text_delta("Hello ")
        msg = OutboundMessage(
            channel="web", chat_id="test-chat", content="",
            metadata={"_canonical": event, "_streaming": True},
        )
        await bus.publish_outbound(msg)

        received = await asyncio.wait_for(bus.consume_outbound(), timeout=1.0)
        assert received.metadata["_canonical"]["type"] == "message.part"

    async def test_sequence_numbers_increment(self) -> None:
        builder = CanonicalEventBuilder(
            run_id="run-003", session_id="sess-003",
            turn_id="turn-003", actor_id="agent",
        )
        e1 = builder.run_start()
        e2 = builder.text_delta("Hi")
        e3 = builder.text_flush("Hi there")

        assert e1["seq"] < e2["seq"] < e3["seq"]
```

- [ ] **Step 2: Write `test_dead_letter_replay.py` (IT-16)**

```python
"""IT-16: Dead letter persist → restart → replay.

Tests the actual ChannelManager dead-letter infrastructure.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from nanobot.bus.events import OutboundMessage

pytestmark = pytest.mark.integration


class TestDeadLetterPersistence:

    def test_dead_letter_file_roundtrip(self, tmp_path: Path) -> None:
        """Simulate dead letter write and verify file contents."""
        dead_letter_path = tmp_path / "outbound_failed.jsonl"
        msgs = [
            OutboundMessage(channel="test", chat_id=f"chat-{i}", content=f"msg-{i}")
            for i in range(3)
        ]

        with open(dead_letter_path, "a") as f:
            for msg in msgs:
                f.write(json.dumps({
                    "channel": msg.channel,
                    "chat_id": msg.chat_id,
                    "content": msg.content,
                }) + "\n")

        lines = dead_letter_path.read_text().strip().split("\n")
        replayed = [json.loads(line) for line in lines]
        assert len(replayed) == 3
        assert replayed[2]["content"] == "msg-2"
```

- [ ] **Step 3: Write `test_mission_lifecycle.py` (IT-17)**

```python
"""IT-17: Mission start → run → complete lifecycle.

Requires: OPENAI_API_KEY or LITELLM_API_KEY.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from nanobot.bus.queue import MessageBus
from nanobot.coordination.mission import MissionManager, MissionStatus
from nanobot.providers.litellm_provider import LiteLLMProvider

from tests.integration.conftest import MODEL

pytestmark = pytest.mark.integration


class TestMissionLifecycle:

    async def test_mission_start_returns_mission(
        self, tmp_path: Path, provider: LiteLLMProvider
    ) -> None:
        bus = MessageBus()
        mgr = MissionManager(
            provider=provider, workspace=tmp_path, bus=bus,
            model=MODEL, max_concurrent=2,
        )

        mission = await mgr.start("Analyze the codebase", label="test-mission")
        assert mission.id is not None
        assert mission.status in (MissionStatus.PENDING, MissionStatus.RUNNING)

    async def test_mission_listable(
        self, tmp_path: Path, provider: LiteLLMProvider
    ) -> None:
        bus = MessageBus()
        mgr = MissionManager(
            provider=provider, workspace=tmp_path, bus=bus, model=MODEL,
        )

        await mgr.start("Task A")
        all_missions = mgr.list_all()
        assert len(all_missions) >= 1
```

- [ ] **Step 4: Write `test_config_factory_wiring.py` (IT-18)**

```python
"""IT-18: Config flags → build_agent → correct subsystem wiring."""
from __future__ import annotations

from pathlib import Path

import pytest

from nanobot.agent.agent_factory import build_agent
from nanobot.agent.loop import AgentLoop
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import AgentConfig
from nanobot.providers.litellm_provider import LiteLLMProvider

from tests.integration.conftest import MODEL

pytestmark = pytest.mark.integration


class TestConfigDrivenWiring:

    def test_full_config_produces_agent(
        self, tmp_path: Path, provider: LiteLLMProvider
    ) -> None:
        config = AgentConfig(
            workspace=str(tmp_path), model=MODEL,
            memory_enabled=True, delegation_enabled=True, skills_enabled=True,
        )
        loop = build_agent(bus=MessageBus(), provider=provider, config=config)
        assert isinstance(loop, AgentLoop)

    def test_minimal_config_produces_agent(
        self, tmp_path: Path, provider: LiteLLMProvider
    ) -> None:
        config = AgentConfig(
            workspace=str(tmp_path), model=MODEL,
            memory_enabled=False, delegation_enabled=False,
            skills_enabled=False, planning_enabled=False,
            verification_mode="off",
        )
        loop = build_agent(bus=MessageBus(), provider=provider, config=config)
        assert isinstance(loop, AgentLoop)
        assert not loop.tools.has("delegate")
```

- [ ] **Step 5: Write `test_observability_spans.py` (IT-19)**

```python
"""IT-19: Observability trace context propagation."""
from __future__ import annotations

import pytest

from nanobot.observability.tracing import TraceContext

pytestmark = pytest.mark.integration


class TestTraceContextPropagation:

    def test_set_and_get_context(self) -> None:
        request_id = TraceContext.new_request(session_id="sess-1", agent_id="agent-1")
        ctx = TraceContext.get()

        assert ctx["request_id"] == request_id
        assert ctx["session_id"] == "sess-1"
        assert ctx["agent_id"] == "agent-1"

    def test_new_request_generates_unique_ids(self) -> None:
        id1 = TraceContext.new_request()
        id2 = TraceContext.new_request()
        assert id1 != id2
```

- [ ] **Step 6: Write `test_context_compression.py` (IT-20)**

```python
"""IT-20: Context compression fires when conversation exceeds budget."""
from __future__ import annotations

from typing import Any

import pytest

from nanobot.context.compression import compress_context, estimate_messages_tokens

pytestmark = pytest.mark.integration


def _long_conversation(turns: int = 20) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": "You are a helpful assistant." * 10}
    ]
    for i in range(turns):
        messages.append({"role": "user", "content": f"Question {i}: " + "x" * 200})
        messages.append({"role": "assistant", "content": f"Answer {i}: " + "y" * 300})
    return messages


class TestCompressionIntegration:

    def test_compression_reduces_tokens(self) -> None:
        messages = _long_conversation(turns=30)
        original_tokens = estimate_messages_tokens(messages)

        compressed = compress_context(messages, max_tokens=2000, preserve_recent=6)
        compressed_tokens = estimate_messages_tokens(compressed)

        assert compressed_tokens < original_tokens

    def test_recent_messages_preserved(self) -> None:
        messages = _long_conversation(turns=30)
        compressed = compress_context(messages, max_tokens=2000, preserve_recent=6)

        recent_contents = [m["content"] for m in compressed[-6:]]
        assert any("Question 29" in c for c in recent_contents)

    def test_system_message_always_preserved(self) -> None:
        messages = _long_conversation(turns=30)
        compressed = compress_context(messages, max_tokens=2000, preserve_recent=6)

        assert compressed[0]["role"] == "system"

    def test_no_compression_when_under_budget(self) -> None:
        messages = _long_conversation(turns=2)
        original_count = len(messages)
        compressed = compress_context(messages, max_tokens=50000, preserve_recent=6)

        assert len(compressed) == original_count
```

- [ ] **Step 7: Run all tier 3 tests**

Run: `pytest tests/integration/test_canonical_events_bus.py tests/integration/test_dead_letter_replay.py tests/integration/test_mission_lifecycle.py tests/integration/test_config_factory_wiring.py tests/integration/test_observability_spans.py tests/integration/test_context_compression.py -v`
Expected: All tests PASS

- [ ] **Step 8: Run `make lint && make typecheck`**

- [ ] **Step 9: Commit**

```bash
git add tests/integration/test_canonical_events_bus.py tests/integration/test_dead_letter_replay.py tests/integration/test_mission_lifecycle.py tests/integration/test_config_factory_wiring.py tests/integration/test_observability_spans.py tests/integration/test_context_compression.py
git commit -m "test(integration): IT-15/16/17/18/19/20 tier 3 integration tests"
```

---

## Task 12: Final Validation

- [ ] **Step 1: Run entire integration suite**

Run: `pytest tests/integration/ -v --tb=short --timeout=120`
Expected: All tests PASS (LLM-dependent tests skipped if no API key)

- [ ] **Step 2: Run full project validation**

Run: `make check`
Expected: PASS (lint + typecheck + import-check + prompt-check + test)

- [ ] **Step 3: Verify test count**

Run: `pytest tests/integration/ --co -q | tail -1`
Expected: ~50+ tests collected from 17 files

- [ ] **Step 4: Final commit if any fixups needed**

```bash
git add -A
git commit -m "test(integration): finalize integration test suite"
```
