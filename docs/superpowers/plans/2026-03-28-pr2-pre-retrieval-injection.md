# PR 2: Pre-Retrieval Injection + File Watcher Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Auto-inject top-k memory chunks into every agent turn's context, and keep the index live when MEMORY.md or HISTORY.md changes on disk.

**Architecture:** A new `IndexService` lifecycle object wraps `MemoryIndex` + a `watchdog` file observer. `ContextBuilder.build_messages()` becomes `async` and accepts an optional `IndexService`; when present it queries the index with the user's message and prepends a `system` injection message. `AgentLoop` constructs `IndexService` instead of bare `MemoryIndex` and passes it through to `build_messages()`.

**Tech Stack:** Python 3.11+, asyncio, `watchdog>=3.0.0` (new optional dep under `[memory]`), existing `sqlite-vec` + BM25 search pipeline from PR 1.

---

## File Map

| File | Change |
|---|---|
| `nanobot/config/schema.py` | Add `inject_top_k: int = 3`, `watch_files: bool = True` to `MemoryIndexConfig` |
| `pyproject.toml` | Add `watchdog>=3.0.0` to `[memory]` extras |
| `nanobot/memory_index/service.py` | **New** — `IndexService` lifecycle: `start()`, `stop()`, `_start_watcher()` |
| `nanobot/agent/context.py` | `build_messages()` → `async def`; add `index: IndexService | None = None` param; inject results before last message |
| `nanobot/agent/memory.py` | `estimate_session_prompt_tokens()` → `async def`; `await self._build_messages(...)` at two call sites; update type annotation |
| `nanobot/agent/loop.py` | Store `_index_service` + `_index_service_started` flag; schedule `start()` in `run()`/`process_direct()`; `await build_messages()` at both call sites; stop watcher in `close_mcp()` |
| `tests/test_memory_index/test_service.py` | **New** — `IndexService` lifecycle + watcher tests |
| `tests/agent/test_context_injection.py` | **New** — injection happy/null/empty-results paths |
| `tests/agent/test_memory_index_integration.py` | Update existing tests to use `IndexService` |

---

## Task 1: Config Additions + watchdog Dependency

**Files:**
- Modify: `nanobot/config/schema.py:166-171`
- Modify: `pyproject.toml:67-69`
- Create: `tests/test_memory_index/test_service.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_memory_index/test_service.py`:
```python
from nanobot.config.schema import MemoryIndexConfig


def test_memory_index_config_defaults_include_injection_fields():
    cfg = MemoryIndexConfig()
    assert cfg.inject_top_k == 3
    assert cfg.watch_files is True


def test_memory_index_config_inject_top_k_can_be_zero():
    cfg = MemoryIndexConfig(inject_top_k=0)
    assert cfg.inject_top_k == 0


def test_memory_index_config_watch_files_can_be_disabled():
    cfg = MemoryIndexConfig(watch_files=False)
    assert cfg.watch_files is False
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_memory_index/test_service.py -v
```
Expected: `FAILED` — `MemoryIndexConfig` has no attribute `inject_top_k`.

- [ ] **Step 3: Add fields to `MemoryIndexConfig` in `nanobot/config/schema.py`**

```python
class MemoryIndexConfig(Base):
    """Semantic memory index configuration. Off by default."""

    enabled: bool = False
    embedding: MemoryIndexEmbeddingConfig = Field(default_factory=MemoryIndexEmbeddingConfig)
    query: MemoryIndexQueryConfig = Field(default_factory=MemoryIndexQueryConfig)
    inject_top_k: int = 3       # chunks auto-injected per turn; 0 = disabled
    watch_files: bool = True    # enable watchdog file watcher
```

- [ ] **Step 4: Add watchdog to `[memory]` extras in `pyproject.toml`**

```toml
memory = [
    "sqlite-vec>=0.1.0",
    "watchdog>=3.0.0",
]
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest tests/test_memory_index/test_service.py -v
```
Expected: `3 passed`.

- [ ] **Step 6: Install the new dep**

```bash
pip install "watchdog>=3.0.0"
```

- [ ] **Step 7: Commit**

```bash
git add nanobot/config/schema.py pyproject.toml tests/test_memory_index/test_service.py
git commit -m "feat(memory_index): add inject_top_k and watch_files config fields; add watchdog dep"
```

---

## Task 2: IndexService — Lifecycle (start / stop)

**Files:**
- Create: `nanobot/memory_index/service.py`
- Modify: `tests/test_memory_index/test_service.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_memory_index/test_service.py`:
```python
async def test_index_service_start_indexes_memory_file(tmp_path):
    from nanobot.memory_index.service import IndexService

    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    (memory_dir / "MEMORY.md").write_text("## Facts\n\nUser likes Python programming.\n")

    cfg = MemoryIndexConfig()
    cfg.watch_files = False  # disable watcher — not tested here
    service = IndexService(tmp_path, cfg)
    await service.start()

    results = await service.index.search("Python programming", top_k=1)
    assert len(results) >= 1
    assert "Python" in results[0].text

    await service.stop()


async def test_index_service_stop_is_idempotent(tmp_path):
    from nanobot.memory_index.service import IndexService

    cfg = MemoryIndexConfig()
    cfg.watch_files = False
    service = IndexService(tmp_path, cfg)
    await service.start()
    await service.stop()
    await service.stop()  # must not raise


async def test_index_service_stop_without_start_is_safe(tmp_path):
    from nanobot.memory_index.service import IndexService

    cfg = MemoryIndexConfig()
    cfg.watch_files = False
    service = IndexService(tmp_path, cfg)
    await service.stop()  # must not raise — observer is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_memory_index/test_service.py -v
```
Expected: `FAILED` — `ImportError: cannot import name 'IndexService'`.

- [ ] **Step 3: Create `nanobot/memory_index/service.py`**

```python
"""IndexService — lifecycle wrapper around MemoryIndex with optional file watcher."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from nanobot.config.schema import MemoryIndexConfig
    from nanobot.memory_index.search import SearchResult


class IndexService:
    """Lifecycle object that owns MemoryIndex and an optional watchdog file observer."""

    def __init__(self, workspace: Path, cfg: MemoryIndexConfig) -> None:
        from nanobot.memory_index.index import MemoryIndex

        self.index = MemoryIndex(workspace, cfg)
        self._cfg = cfg
        self._observer = None

    async def start(self) -> None:
        """Index memory files at startup; optionally start the file watcher."""
        await self.index.startup_index()
        if self._cfg.watch_files:
            self._start_watcher()

    async def stop(self) -> None:
        """Stop the file watcher if running."""
        if self._observer is not None:
            self._observer.stop()
            self._observer.join()
            self._observer = None

    def _start_watcher(self) -> None:
        """Start a watchdog observer that re-indexes on MEMORY.md / HISTORY.md changes."""
        import asyncio

        from watchdog.events import FileSystemEventHandler
        from watchdog.observers import Observer

        loop = asyncio.get_event_loop()
        index = self.index
        memory_dir = self.index.memory_dir

        class _MemoryFileHandler(FileSystemEventHandler):
            def on_modified(self, event) -> None:
                if not event.is_directory:
                    p = Path(event.src_path)
                    if p.name in ("MEMORY.md", "HISTORY.md"):
                        asyncio.run_coroutine_threadsafe(index._index_file(p), loop)

            def on_created(self, event) -> None:
                self.on_modified(event)

        observer = Observer()
        observer.schedule(_MemoryFileHandler(), str(memory_dir), recursive=False)
        observer.start()
        self._observer = observer
        logger.info("Memory file watcher started for {}", memory_dir)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_memory_index/test_service.py::test_index_service_start_indexes_memory_file tests/test_memory_index/test_service.py::test_index_service_stop_is_idempotent tests/test_memory_index/test_service.py::test_index_service_stop_without_start_is_safe -v
```
Expected: `3 passed`.

- [ ] **Step 5: Commit**

```bash
git add nanobot/memory_index/service.py tests/test_memory_index/test_service.py
git commit -m "feat(memory_index): add IndexService lifecycle (start/stop)"
```

---

## Task 3: IndexService — File Watcher

**Files:**
- Modify: `tests/test_memory_index/test_service.py`

The `_start_watcher()` implementation already exists from Task 2. This task adds tests for it.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_memory_index/test_service.py`:
```python
def test_start_watcher_creates_and_starts_observer(tmp_path):
    """_start_watcher() schedules an Observer on the memory directory."""
    from unittest.mock import MagicMock, patch

    from nanobot.memory_index.service import IndexService

    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()

    cfg = MemoryIndexConfig()
    cfg.watch_files = False  # prevent auto-start in .start()
    service = IndexService(tmp_path, cfg)

    mock_observer = MagicMock()
    with patch("nanobot.memory_index.service.Observer", return_value=mock_observer):
        service._start_watcher()

    mock_observer.schedule.assert_called_once()
    # Second positional arg to schedule is the watched directory path
    _handler, watched_dir, *_ = mock_observer.schedule.call_args[0]
    assert watched_dir == str(tmp_path / "memory")
    mock_observer.start.assert_called_once()
    assert service._observer is mock_observer


def test_stop_stops_and_joins_observer(tmp_path):
    """stop() calls observer.stop() and observer.join()."""
    import asyncio
    from unittest.mock import MagicMock, patch

    from nanobot.memory_index.service import IndexService

    cfg = MemoryIndexConfig()
    cfg.watch_files = False
    service = IndexService(tmp_path, cfg)

    mock_observer = MagicMock()
    service._observer = mock_observer

    asyncio.get_event_loop().run_until_complete(service.stop())

    mock_observer.stop.assert_called_once()
    mock_observer.join.assert_called_once()
    assert service._observer is None


def test_watcher_only_triggers_for_memory_files(tmp_path):
    """Handler on_modified only schedules re-index for MEMORY.md and HISTORY.md."""
    import asyncio
    from unittest.mock import MagicMock, patch

    from nanobot.memory_index.service import IndexService
    from watchdog.events import FileModifiedEvent

    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()

    cfg = MemoryIndexConfig()
    cfg.watch_files = False
    service = IndexService(tmp_path, cfg)

    scheduled = []

    def fake_run_threadsafe(coro, loop):
        # Close the coroutine to avoid ResourceWarning
        coro.close()
        scheduled.append(True)

    captured_handler = None

    def capture_schedule(handler, path, recursive=False):
        nonlocal captured_handler
        captured_handler = handler

    mock_observer = MagicMock()
    mock_observer.schedule.side_effect = capture_schedule

    with patch("nanobot.memory_index.service.Observer", return_value=mock_observer), \
         patch("asyncio.run_coroutine_threadsafe", side_effect=fake_run_threadsafe):
        service._start_watcher()

    assert captured_handler is not None

    # Trigger on MEMORY.md — should schedule
    captured_handler.on_modified(FileModifiedEvent(str(memory_dir / "MEMORY.md")))
    assert len(scheduled) == 1

    # Trigger on HISTORY.md — should schedule
    captured_handler.on_modified(FileModifiedEvent(str(memory_dir / "HISTORY.md")))
    assert len(scheduled) == 2

    # Trigger on unrelated file — should NOT schedule
    captured_handler.on_modified(FileModifiedEvent(str(memory_dir / "notes.txt")))
    assert len(scheduled) == 2  # still 2
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_memory_index/test_service.py::test_start_watcher_creates_and_starts_observer tests/test_memory_index/test_service.py::test_stop_stops_and_joins_observer tests/test_memory_index/test_service.py::test_watcher_only_triggers_for_memory_files -v
```
Expected: `FAILED` — `ImportError` or attribute errors because `nanobot.memory_index.service.Observer` isn't patchable at the right path.

If the import patch path is wrong, adjust it: `watchdog.observers.Observer`. Check that `service.py` imports `Observer` inside `_start_watcher` so the patch path must match the call site. Since `_start_watcher` does `from watchdog.observers import Observer`, the correct patch path is `nanobot.memory_index.service.Observer`.

- [ ] **Step 3: Run the full test_service.py to verify all tests pass**

```bash
pytest tests/test_memory_index/test_service.py -v
```
Expected: `9 passed`.

- [ ] **Step 4: Commit**

```bash
git add tests/test_memory_index/test_service.py
git commit -m "test(memory_index): add IndexService watcher tests"
```

---

## Task 4: `build_messages()` → async + Pre-Retrieval Injection

**Files:**
- Modify: `nanobot/agent/context.py`
- Modify: `nanobot/agent/memory.py`
- Create: `tests/agent/test_context_injection.py`

**What changes:**
- `build_messages()` becomes `async def` and gains an `index: IndexService | None = None` parameter.
- When `index` is provided and `index._cfg.inject_top_k > 0`, the method awaits `index.index.search(current_message, top_k=...)` and inserts the results as a `system` message just before the last (user) message.
- `MemoryConsolidator.estimate_session_prompt_tokens()` becomes `async` because it calls `build_messages`. Its two callers inside `maybe_consolidate_by_tokens()` get `await`.

- [ ] **Step 1: Write the failing tests**

Create `tests/agent/test_context_injection.py`:
```python
"""Tests for pre-retrieval injection in build_messages()."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.memory_index.search import SearchResult


def _make_result(text: str) -> SearchResult:
    return SearchResult(text=text, source="MEMORY.md", start_line=1, end_line=2, score=0.9)


async def test_build_messages_injects_results_when_index_provided(tmp_path):
    from nanobot.agent.context import ContextBuilder

    ctx = ContextBuilder(tmp_path, memory_index_enabled=True)

    mock_service = MagicMock()
    mock_service._cfg.inject_top_k = 3
    mock_service.index.search = AsyncMock(return_value=[_make_result("User prefers dark mode.")])

    messages = await ctx.build_messages(
        history=[],
        current_message="What theme do I like?",
        index=mock_service,
    )

    injected = [m for m in messages if m["role"] == "system" and "Relevant memory" in m.get("content", "")]
    assert len(injected) == 1
    assert "dark mode" in injected[0]["content"]


async def test_injection_message_is_inserted_before_user_message(tmp_path):
    from nanobot.agent.context import ContextBuilder

    ctx = ContextBuilder(tmp_path, memory_index_enabled=True)

    mock_service = MagicMock()
    mock_service._cfg.inject_top_k = 3
    mock_service.index.search = AsyncMock(return_value=[_make_result("Some fact.")])

    messages = await ctx.build_messages(
        history=[],
        current_message="hello",
        index=mock_service,
    )

    # Injection must come before the last (user) message
    roles = [m["role"] for m in messages]
    injection_idx = next(
        i for i, m in enumerate(messages)
        if m["role"] == "system" and "Relevant memory" in m.get("content", "")
    )
    assert injection_idx == len(messages) - 2  # second-to-last


async def test_injection_includes_source_and_line_range(tmp_path):
    from nanobot.agent.context import ContextBuilder

    ctx = ContextBuilder(tmp_path, memory_index_enabled=True)

    result = SearchResult(
        text="User likes coffee.",
        source="MEMORY.md",
        start_line=5,
        end_line=7,
        score=0.8,
    )
    mock_service = MagicMock()
    mock_service._cfg.inject_top_k = 3
    mock_service.index.search = AsyncMock(return_value=[result])

    messages = await ctx.build_messages(
        history=[],
        current_message="What do I drink?",
        index=mock_service,
    )

    injected = [m for m in messages if m["role"] == "system" and "Relevant memory" in m.get("content", "")]
    assert "[MEMORY.md L5–7]" in injected[0]["content"]
    assert "User likes coffee." in injected[0]["content"]


async def test_no_injection_when_index_is_none(tmp_path):
    from nanobot.agent.context import ContextBuilder

    ctx = ContextBuilder(tmp_path, memory_index_enabled=False)

    messages = await ctx.build_messages(
        history=[],
        current_message="hello",
        index=None,
    )

    injected = [m for m in messages if m["role"] == "system" and "Relevant memory" in m.get("content", "")]
    assert len(injected) == 0


async def test_no_injection_when_empty_results(tmp_path):
    from nanobot.agent.context import ContextBuilder

    ctx = ContextBuilder(tmp_path, memory_index_enabled=True)

    mock_service = MagicMock()
    mock_service._cfg.inject_top_k = 3
    mock_service.index.search = AsyncMock(return_value=[])

    messages = await ctx.build_messages(
        history=[],
        current_message="anything",
        index=mock_service,
    )

    injected = [m for m in messages if m["role"] == "system" and "Relevant memory" in m.get("content", "")]
    assert len(injected) == 0


async def test_no_injection_when_inject_top_k_is_zero(tmp_path):
    from nanobot.agent.context import ContextBuilder

    ctx = ContextBuilder(tmp_path, memory_index_enabled=True)

    mock_service = MagicMock()
    mock_service._cfg.inject_top_k = 0
    mock_service.index.search = AsyncMock(return_value=[_make_result("Should not appear.")])

    messages = await ctx.build_messages(
        history=[],
        current_message="anything",
        index=mock_service,
    )

    mock_service.index.search.assert_not_called()
    injected = [m for m in messages if m["role"] == "system" and "Relevant memory" in m.get("content", "")]
    assert len(injected) == 0


async def test_estimate_session_prompt_tokens_is_async(tmp_path):
    """MemoryConsolidator.estimate_session_prompt_tokens() must be awaitable."""
    import asyncio
    from unittest.mock import MagicMock

    from nanobot.agent.memory import MemoryConsolidator

    async def fake_build(**kwargs):
        return [{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}]

    consolidator = MemoryConsolidator(
        workspace=tmp_path,
        provider=MagicMock(),
        model="test-model",
        sessions=MagicMock(),
        context_window_tokens=8192,
        build_messages=fake_build,
        get_tool_definitions=lambda: [],
    )

    mock_session = MagicMock()
    mock_session.messages = [{"role": "user", "content": "hi"}]
    mock_session.key = "cli:test"
    mock_session.get_history.return_value = []

    tokens, source = await consolidator.estimate_session_prompt_tokens(mock_session)
    assert isinstance(tokens, int)
    assert isinstance(source, str)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/agent/test_context_injection.py -v
```
Expected: `FAILED` — `build_messages()` is not a coroutine / `index` param does not exist.

- [ ] **Step 3: Make `build_messages()` async in `nanobot/agent/context.py`**

Add `from __future__ import annotations` and a `TYPE_CHECKING` guard at the top of the file:

```python
"""Context builder for assembling agent prompts."""

from __future__ import annotations

import base64
import mimetypes
import platform
from pathlib import Path
from typing import TYPE_CHECKING, Any

from nanobot.agent.memory import MemoryStore
from nanobot.agent.skills import SkillsLoader
from nanobot.utils.helpers import build_assistant_message, current_time_str, detect_image_mime

if TYPE_CHECKING:
    from nanobot.memory_index.service import IndexService
```

Change the `build_messages` signature and body (replace the existing method starting at line 135):

```python
    async def build_messages(
        self,
        history: list[dict[str, Any]],
        current_message: str,
        skill_names: list[str] | None = None,
        media: list[str] | None = None,
        channel: str | None = None,
        chat_id: str | None = None,
        current_role: str = "user",
        index: IndexService | None = None,
    ) -> list[dict[str, Any]]:
        """Build the complete message list for an LLM call."""
        runtime_ctx = self._build_runtime_context(channel, chat_id, self.timezone)
        user_content = self._build_user_content(current_message, media)

        # Merge runtime context and user content into a single user message
        # to avoid consecutive same-role messages that some providers reject.
        if isinstance(user_content, str):
            merged = f"{runtime_ctx}\n\n{user_content}"
        else:
            merged = [{"type": "text", "text": runtime_ctx}] + user_content

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": self.build_system_prompt(skill_names)},
            *history,
            {"role": current_role, "content": merged},
        ]

        if index is not None and index._cfg.inject_top_k > 0:
            results = await index.index.search(current_message, top_k=index._cfg.inject_top_k)
            if results:
                injection = "Relevant memory:\n\n" + "\n\n---\n\n".join(
                    f"[{r.source} L{r.start_line}–{r.end_line}]\n{r.text}" for r in results
                )
                messages.insert(-1, {"role": "system", "content": injection})

        return messages
```

- [ ] **Step 4: Make `estimate_session_prompt_tokens()` async in `nanobot/agent/memory.py`**

Add `Awaitable` to the import at the top of `memory.py`:
```python
from typing import TYPE_CHECKING, Any, Awaitable, Callable
```

Update the type annotation for `build_messages` in `MemoryConsolidator.__init__`:
```python
        build_messages: Callable[..., Awaitable[list[dict[str, Any]]]],
```

Change `estimate_session_prompt_tokens` from `def` to `async def` and add `await`:
```python
    async def estimate_session_prompt_tokens(self, session: Session) -> tuple[int, str]:
        """Estimate current prompt size for the normal session history view."""
        history = session.get_history(max_messages=0)
        channel, chat_id = (session.key.split(":", 1) if ":" in session.key else (None, None))
        probe_messages = await self._build_messages(
            history=history,
            current_message="[token-probe]",
            channel=channel,
            chat_id=chat_id,
        )
        return estimate_prompt_tokens_chain(
            self.provider,
            self.model,
            probe_messages,
            self._get_tool_definitions(),
        )
```

Update both callers inside `maybe_consolidate_by_tokens()` (currently lines 319 and 364) to use `await`:
```python
            estimated, source = await self.estimate_session_prompt_tokens(session)
```
(There are two occurrences — both need `await`.)

- [ ] **Step 5: Run the injection tests**

```bash
pytest tests/agent/test_context_injection.py -v
```
Expected: `7 passed`.

- [ ] **Step 6: Run full test suite to check for regressions**

```bash
pytest --tb=short -q
```
Expected: all existing tests still pass. Pay attention to any test that calls `build_messages()` synchronously — they now need `await`.

If any test in `tests/agent/` calls `ctx.build_messages(...)` without `await`, fix those tests by making them async and adding `await`.

- [ ] **Step 7: Commit**

```bash
git add nanobot/agent/context.py nanobot/agent/memory.py tests/agent/test_context_injection.py
git commit -m "feat(agent): make build_messages async; add pre-retrieval injection via IndexService"
```

---

## Task 5: `loop.py` Wiring — IndexService + Await build_messages

**Files:**
- Modify: `nanobot/agent/loop.py`
- Modify: `tests/agent/test_memory_index_integration.py`

**What changes:**
- Replace `self._memory_index: MemoryIndex | None` with `self._index_service: IndexService | None` and add `self._index_service_started: bool = False`.
- `_register_default_tools()` creates `IndexService` and stores it in `self._index_service`; passes `service.index` to `MemorySearchTool`.
- `run()` and `process_direct()` schedule `self._index_service.start()` as a background task (guarded by `_index_service_started`).
- Both `build_messages()` call sites in `_process_message()` become `await ctx.build_messages(..., index=self._index_service)`.
- `close_mcp()` calls `await self._index_service.stop()` to clean up the watcher thread.

- [ ] **Step 1: Write the failing tests**

Replace the full contents of `tests/agent/test_memory_index_integration.py` with:
```python
from unittest.mock import MagicMock


def test_context_builder_shows_pointer_note_when_enabled(tmp_path):
    from nanobot.agent.context import ContextBuilder

    ctx = ContextBuilder(tmp_path, memory_index_enabled=True)
    prompt = ctx.build_system_prompt()
    assert "memory_search" in prompt
    assert "tool" in prompt.lower()
    # Full MEMORY.md content should NOT be inlined
    assert "Long-term Memory" not in prompt


def test_context_builder_loads_memory_file_when_disabled(tmp_path):
    from nanobot.agent.context import ContextBuilder

    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    (memory_dir / "MEMORY.md").write_text("## Facts\n\nUser loves coffee.\n")
    ctx = ContextBuilder(tmp_path, memory_index_enabled=False)
    prompt = ctx.build_system_prompt()
    assert "User loves coffee" in prompt


async def test_agent_loop_creates_index_service_when_enabled(tmp_path):
    """AgentLoop._index_service is an IndexService instance when memory_index is enabled."""
    from nanobot.agent.loop import AgentLoop
    from nanobot.bus.queue import MessageBus
    from nanobot.config.schema import MemoryIndexConfig
    from nanobot.memory_index.service import IndexService

    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"

    cfg = MemoryIndexConfig()
    cfg.enabled = True
    cfg.watch_files = False

    loop = AgentLoop(
        bus=MessageBus(),
        provider=provider,
        workspace=tmp_path,
        memory_index_config=cfg,
    )

    assert isinstance(loop._index_service, IndexService)
    assert loop.tools.get("memory_search") is not None


def test_agent_loop_does_not_register_tool_when_disabled(tmp_path):
    from nanobot.agent.loop import AgentLoop
    from nanobot.bus.queue import MessageBus
    from nanobot.config.schema import MemoryIndexConfig

    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"

    loop = AgentLoop(
        bus=MessageBus(),
        provider=provider,
        workspace=tmp_path,
        memory_index_config=MemoryIndexConfig(),  # enabled=False
    )
    assert loop.tools.get("memory_search") is None
    assert loop._index_service is None


async def test_agent_loop_start_schedules_index_service_start(tmp_path):
    """run() schedules IndexService.start() as a background task exactly once."""
    import asyncio
    from unittest.mock import AsyncMock, patch

    from nanobot.agent.loop import AgentLoop
    from nanobot.bus.queue import MessageBus
    from nanobot.config.schema import MemoryIndexConfig

    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"

    cfg = MemoryIndexConfig()
    cfg.enabled = True
    cfg.watch_files = False

    loop = AgentLoop(
        bus=MessageBus(),
        provider=provider,
        workspace=tmp_path,
        memory_index_config=cfg,
    )
    loop._running = False  # prevent run() from looping

    start_calls = []

    async def fake_start():
        start_calls.append(1)

    loop._index_service.start = fake_start

    with patch.object(loop, "_connect_mcp", new_callable=AsyncMock):
        # run() exits immediately because _running=False and queue is empty
        try:
            await asyncio.wait_for(loop.run(), timeout=0.5)
        except asyncio.TimeoutError:
            pass

    # Drain background tasks so fake_start actually runs
    if loop._background_tasks:
        await asyncio.gather(*loop._background_tasks, return_exceptions=True)

    assert len(start_calls) == 1


async def test_agent_loop_start_schedules_only_once(tmp_path):
    """Calling process_direct() twice does not schedule IndexService.start() twice."""
    import asyncio
    from unittest.mock import AsyncMock

    from nanobot.agent.loop import AgentLoop
    from nanobot.bus.queue import MessageBus
    from nanobot.config.schema import MemoryIndexConfig

    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    provider.chat_with_retry = AsyncMock(return_value=MagicMock(
        has_tool_calls=False,
        content="Hi",
        finish_reason="stop",
        tool_calls=[],
        usage={},
        reasoning_content=None,
        thinking_blocks=None,
    ))

    cfg = MemoryIndexConfig()
    cfg.enabled = True
    cfg.watch_files = False

    loop = AgentLoop(
        bus=MessageBus(),
        provider=provider,
        workspace=tmp_path,
        memory_index_config=cfg,
    )

    start_calls = []

    async def fake_start():
        start_calls.append(1)

    loop._index_service.start = fake_start

    await loop.process_direct("hello")
    await loop.process_direct("world")

    if loop._background_tasks:
        await asyncio.gather(*loop._background_tasks, return_exceptions=True)

    assert len(start_calls) == 1  # only once, not twice
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/agent/test_memory_index_integration.py -v
```
Expected: `FAILED` — `AgentLoop` has no `_index_service` attribute (still uses `_memory_index`).

- [ ] **Step 3: Update `nanobot/agent/loop.py`**

**3a.** Update the `TYPE_CHECKING` block (replace `from nanobot.memory_index import MemoryIndex` with `IndexService`):
```python
if TYPE_CHECKING:
    from nanobot.config.schema import (
        ChannelsConfig,
        ExecToolConfig,
        MemoryIndexConfig,
        WebSearchConfig,
    )
    from nanobot.cron.service import CronService
    from nanobot.memory_index.service import IndexService
```

**3b.** In `__init__`, replace `self._memory_index: MemoryIndex | None = None` with two new attributes. Find this line:
```python
        self._running = False
        self._memory_index: MemoryIndex | None = None
        self._mcp_servers = mcp_servers or {}
```
Replace with:
```python
        self._running = False
        self._index_service: IndexService | None = None
        self._index_service_started: bool = False
        self._mcp_servers = mcp_servers or {}
```

**3c.** In `_register_default_tools()`, replace the `memory_index_config` block:
```python
        if self.memory_index_config and self.memory_index_config.enabled:
            from nanobot.agent.tools.memory_search import MemorySearchTool
            from nanobot.memory_index.service import IndexService

            self._index_service = IndexService(self.workspace, self.memory_index_config)
            self.tools.register(MemorySearchTool(self._index_service.index))
            # start() is scheduled in run()/process_direct() once the event loop is running
```

**3d.** In `run()`, replace the `_memory_index` startup block:
```python
        if self._index_service is not None and not self._index_service_started:
            self._index_service_started = True
            self._schedule_background(self._index_service.start())
```

**3e.** In `process_direct()`, replace the `_memory_index` startup block:
```python
        if self._index_service is not None and not self._index_service_started:
            self._index_service_started = True
            self._schedule_background(self._index_service.start())
```

**3f.** In `_process_message()`, find the **system message path** call site (around line 510):
```python
            messages = self.context.build_messages(
                history=history,
                current_message=msg.content,
                channel=channel,
                chat_id=chat_id,
                current_role=current_role,
            )
```
Replace with:
```python
            messages = await self.context.build_messages(
                history=history,
                current_message=msg.content,
                channel=channel,
                chat_id=chat_id,
                current_role=current_role,
                index=self._index_service,
            )
```

**3g.** Find the **regular message path** call site (around line 552):
```python
        initial_messages = self.context.build_messages(
            history=history,
            current_message=msg.content,
            media=msg.media if msg.media else None,
            channel=msg.channel,
            chat_id=msg.chat_id,
        )
```
Replace with:
```python
        initial_messages = await self.context.build_messages(
            history=history,
            current_message=msg.content,
            media=msg.media if msg.media else None,
            channel=msg.channel,
            chat_id=msg.chat_id,
            index=self._index_service,
        )
```

**3h.** In `close_mcp()`, add watcher cleanup before the MCP stack cleanup:
```python
    async def close_mcp(self) -> None:
        """Drain pending background tasks, stop file watcher, then close MCP connections."""
        if self._background_tasks:
            await asyncio.gather(*self._background_tasks, return_exceptions=True)
            self._background_tasks.clear()
        if self._index_service is not None:
            await self._index_service.stop()
        if self._mcp_stack:
            try:
                await self._mcp_stack.aclose()
            except (RuntimeError, BaseExceptionGroup):
                pass
            self._mcp_stack = None
```

- [ ] **Step 4: Run the integration tests**

```bash
pytest tests/agent/test_memory_index_integration.py -v
```
Expected: `6 passed`.

- [ ] **Step 5: Run full test suite**

```bash
pytest --tb=short -q
```
Expected: all tests pass, 0 regressions. If any test calls `context.build_messages(...)` synchronously, update it to be async and add `await`.

- [ ] **Step 6: Lint**

```bash
ruff check nanobot/
```
Expected: no errors. Fix any `F401` (unused import) if the old `MemoryIndex` import lingers.

- [ ] **Step 7: Commit**

```bash
git add nanobot/agent/loop.py tests/agent/test_memory_index_integration.py
git commit -m "feat(agent): wire IndexService into AgentLoop; pre-retrieval injection on every turn"
```

---

## Self-Review Checklist

**Spec coverage:**

| Spec requirement | Covered by |
|---|---|
| Auto-inject top-k chunks every agent turn | Task 4 (`build_messages` injection) + Task 5 (both call sites) |
| Live updates on MEMORY.md / HISTORY.md change | Task 3 (file watcher), Task 2 (`_start_watcher()`) |
| `IndexService` lifecycle object | Task 2 |
| `inject_top_k: int = 3` config field | Task 1 |
| `watch_files: bool = True` config field | Task 1 |
| `watchdog>=3.0.0` added to `[memory]` extras | Task 1 |
| `build_messages()` → `async def` | Task 4 |
| `_process_message` awaits `build_messages()` | Task 5 |
| Explicit `memory_search` tool still registered | Task 5 (`MemorySearchTool(self._index_service.index)`) |

**Testing checklist:**

- [x] `IndexService.start()` / `stop()` lifecycle
- [x] File change event triggers re-index (watchdog mock)
- [x] `build_messages()` injects results when index has matches
- [x] `build_messages()` is unchanged when `index=None` or `inject_top_k=0`
- [x] No injection when index returns empty results
- [x] `_process_message` correctly awaits `build_messages()`
- [x] `IndexService.start()` scheduled only once (double-scheduling guard)
- [x] `MemoryConsolidator.estimate_session_prompt_tokens()` is async

**Type consistency check:**

- `IndexService._cfg` is `MemoryIndexConfig` — used as `index._cfg.inject_top_k` ✓
- `IndexService.index` is `MemoryIndex` — used as `index.index.search(...)` ✓
- `MemorySearchTool(self._index_service.index)` — matches existing `MemorySearchTool(MemoryIndex)` constructor ✓
- `build_messages(..., index: IndexService | None = None)` — all call sites pass a keyword arg or omit it ✓
