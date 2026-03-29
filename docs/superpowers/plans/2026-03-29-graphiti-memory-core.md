# Graphiti Memory Lobe — Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `MemoryBackend` abstraction to nanobot core so the Graphiti memory plugin (Plan 2) can slot in and replace the flat-file memory system.

**Architecture:** `MemoryBackend` ABC lives in `nanobot/agent/memory.py`; `MemoryStore` implements it as the default (zero behavior change). `ContextBuilder.build_messages()` becomes async and injects retrieved context when a backend is active. `AgentLoop` discovers backends via the `nanobot.memory` entry-point group and dispatches per-turn consolidation when `backend.consolidates_per_turn` is True.

**Tech Stack:** Python 3.11+, `asyncio`, `importlib.metadata` (stdlib entry-point discovery). No new dependencies.

---

## File Map

| File | Change |
|---|---|
| `nanobot/config/schema.py` | Add `MemoryConfig(Base)` + `Config.memory` field |
| `nanobot/agent/memory.py` | Add `MemoryBackend` ABC; `MemoryStore` subclasses it; `MemoryConsolidator` gets `skip_llm` param + async `estimate_session_prompt_tokens` |
| `nanobot/agent/context.py` | `build_messages()` → async + `session_key` param + memory injection; `_get_identity()` backend-aware |
| `nanobot/agent/loop.py` | `memory_backend` param, tool registration, `await build_messages`, per-turn consolidation dispatch, deferred `backend.start()` |
| `nanobot/cli/commands.py` | Add `load_memory_backend(config)` call at both `AgentLoop` creation sites |
| `tests/agent/test_memory_backend.py` | **New** — `MemoryBackend` ABC contract, `MemoryStore` implementation |
| `tests/agent/test_context_memory_inject.py` | **New** — async `build_messages` with and without memory injection |
| `tests/agent/test_loop_memory_backend.py` | **New** — backend discovery fallback, `consolidates_per_turn` dispatch, tool registration |

---

## Task 1: `MemoryConfig` in `nanobot/config/schema.py`

**Files:**
- Modify: `nanobot/config/schema.py` (around line 152, before the `Config` class)

**Context:** `Config(BaseSettings)` currently has `agents`, `channels`, `providers`, `gateway`, `tools` fields. Add `memory` field. `MemoryConfig` needs `backend: str = "default"`.

- [ ] **Step 1: Write the failing tests**

Create `tests/agent/test_memory_backend.py` (config section only for now):
```python
def test_memory_config_defaults():
    from nanobot.config.schema import MemoryConfig

    cfg = MemoryConfig()
    assert cfg.backend == "default"


def test_memory_config_backend_can_be_set():
    from nanobot.config.schema import MemoryConfig

    cfg = MemoryConfig(backend="graphiti")
    assert cfg.backend == "graphiti"


def test_config_has_memory_field():
    from nanobot.config.schema import Config

    cfg = Config()
    assert cfg.memory.backend == "default"
```

- [ ] **Step 2: Run — verify FAILED**

```bash
pytest tests/agent/test_memory_backend.py -v -k "memory_config or config_has_memory"
```
Expected: `FAILED` — `cannot import name 'MemoryConfig'`

- [ ] **Step 3: Add `MemoryConfig` and `Config.memory` field**

In `nanobot/config/schema.py`, insert before the `Config` class (after `ToolsConfig`):
```python
class MemoryConfig(Base):
    """Memory backend configuration."""

    backend: str = "default"
```

Then add to `Config`:
```python
class Config(BaseSettings):
    """Root configuration for nanobot."""

    agents: AgentsConfig = Field(default_factory=AgentsConfig)
    channels: ChannelsConfig = Field(default_factory=ChannelsConfig)
    providers: ProvidersConfig = Field(default_factory=ProvidersConfig)
    gateway: GatewayConfig = Field(default_factory=GatewayConfig)
    tools: ToolsConfig = Field(default_factory=ToolsConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
```

- [ ] **Step 4: Run — verify PASSED**

```bash
pytest tests/agent/test_memory_backend.py -v -k "memory_config or config_has_memory"
```

- [ ] **Step 5: Run full suite — no regressions**

```bash
pytest --tb=short -q
```
Expected: 647 passed (644 + 3 new), 1 skipped.

- [ ] **Commit**

```
feat(config): add MemoryConfig with backend field
```

---

## Task 2: `MemoryBackend` ABC + `MemoryStore` implementation

**Files:**
- Modify: `nanobot/agent/memory.py`
- Modify: `tests/agent/test_memory_backend.py` (add to existing file)

**Context:** `MemoryStore` currently starts at line 75 with no base class. We add `MemoryBackend` ABC before it, then make `MemoryStore` subclass it. `MemoryBackend.consolidate()` and `retrieve()` are abstract. The default `consolidates_per_turn` is `False`; `get_tools()` returns `[]`; `start()`/`stop()` are no-ops.

For `MemoryStore`:
- `consolidates_per_turn = False`
- `get_tools()` → `[]`
- `start(provider)` → no-op (file-based, no async init needed)
- `stop()` → no-op
- `consolidate(messages, session_key)` → no-op (MemoryConsolidator handles consolidation for the MemoryStore path; this method is only called by AgentLoop for per-turn backends)
- `retrieve(query, session_key, top_k=5)` → returns `self.get_memory_context()` (ignores query, returns full MEMORY.md — preserves current behavior as the default)

- [ ] **Step 1: Write the failing tests**

Add to `tests/agent/test_memory_backend.py`:
```python
import pytest
from pathlib import Path
from unittest.mock import MagicMock


def test_memory_backend_abc_cannot_be_instantiated_directly():
    from nanobot.agent.memory import MemoryBackend

    with pytest.raises(TypeError):
        MemoryBackend()


def test_memory_store_is_memory_backend(tmp_path):
    from nanobot.agent.memory import MemoryBackend, MemoryStore

    store = MemoryStore(tmp_path)
    assert isinstance(store, MemoryBackend)


def test_memory_store_consolidates_per_turn_is_false(tmp_path):
    from nanobot.agent.memory import MemoryStore

    store = MemoryStore(tmp_path)
    assert store.consolidates_per_turn is False


def test_memory_store_get_tools_returns_empty_list(tmp_path):
    from nanobot.agent.memory import MemoryStore

    store = MemoryStore(tmp_path)
    assert store.get_tools() == []


async def test_memory_store_retrieve_returns_memory_context(tmp_path):
    from nanobot.agent.memory import MemoryStore

    store = MemoryStore(tmp_path)
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    (memory_dir / "MEMORY.md").write_text("I like coffee")

    result = await store.retrieve("anything", "telegram:123")
    assert "I like coffee" in result


async def test_memory_store_retrieve_returns_empty_string_when_no_file(tmp_path):
    from nanobot.agent.memory import MemoryStore

    store = MemoryStore(tmp_path)
    result = await store.retrieve("anything", "telegram:123")
    assert result == ""


async def test_memory_store_consolidate_is_noop(tmp_path):
    from nanobot.agent.memory import MemoryStore

    store = MemoryStore(tmp_path)
    # Should not raise and should not create any files
    await store.consolidate([{"role": "user", "content": "hello"}], "telegram:123")
    assert not (tmp_path / "memory" / "MEMORY.md").exists()
```

- [ ] **Step 2: Run — verify FAILED**

```bash
pytest tests/agent/test_memory_backend.py -v -k "backend_abc or is_memory_backend or consolidates_per_turn or get_tools or store_retrieve or store_consolidate"
```
Expected: `FAILED` — `cannot import name 'MemoryBackend'`

- [ ] **Step 3: Add `MemoryBackend` ABC to `nanobot/agent/memory.py`**

Add these imports at the top of the file (after existing imports):
```python
from abc import ABC, abstractmethod
```

Insert the `MemoryBackend` class before the `MemoryStore` class (around line 75):
```python
class MemoryBackend(ABC):
    """Abstract base class for nanobot memory backends.

    Backends are discovered via the ``nanobot.memory`` entry-point group.
    The default backend is ``MemoryStore`` (flat-file MEMORY.md).
    """

    @property
    def consolidates_per_turn(self) -> bool:
        """True if this backend captures facts after every turn.

        When True, AgentLoop fires ``consolidate()`` as a background task
        after each turn, and MemoryConsolidator skips its LLM archival step.
        When False (default), MemoryConsolidator governs consolidation under
        token-pressure.
        """
        return False

    def get_tools(self) -> list:
        """Return extra Tool instances to register in AgentLoop. Default: none."""
        return []

    async def start(self, provider: Any) -> None:
        """Lifecycle: called once at agent startup (after the event loop is running)."""

    async def stop(self) -> None:
        """Lifecycle: called on graceful shutdown."""

    @abstractmethod
    async def consolidate(self, messages: list[dict], session_key: str) -> None:
        """Post-turn: extract and store facts from the completed turn's messages."""

    @abstractmethod
    async def retrieve(self, query: str, session_key: str, top_k: int = 5) -> str:
        """Pre-turn: return a formatted context block of relevant memories, or '' if none."""
```

- [ ] **Step 4: Make `MemoryStore` subclass `MemoryBackend`**

Change the `MemoryStore` class definition and add the four required methods. The existing methods (`read_long_term`, `write_long_term`, etc.) are unchanged.

Change:
```python
class MemoryStore:
    """Two-layer memory: MEMORY.md (long-term facts) + HISTORY.md (grep-searchable log)."""
```
To:
```python
class MemoryStore(MemoryBackend):
    """Two-layer memory: MEMORY.md (long-term facts) + HISTORY.md (grep-searchable log)."""
```

Add these four methods at the end of the `MemoryStore` class (after the existing `_raw_archive` method):
```python
    # --- MemoryBackend interface ---

    async def consolidate(self, messages: list[dict], session_key: str) -> None:
        """No-op: MemoryConsolidator handles consolidation for the MemoryStore path."""

    async def retrieve(self, query: str, session_key: str, top_k: int = 5) -> str:
        """Return full MEMORY.md content (query-independent, preserves current behaviour)."""
        return self.get_memory_context()
```

- [ ] **Step 5: Run — verify PASSED**

```bash
pytest tests/agent/test_memory_backend.py -v
```

- [ ] **Step 6: Run full suite — no regressions**

```bash
pytest --tb=short -q
```
Expected: 654 passed (644 + 10 new), 1 skipped.

- [ ] **Commit**

```
feat(agent): add MemoryBackend ABC; MemoryStore implements it
```

---

## Task 3: Async `build_messages` with memory injection

**Files:**
- Modify: `nanobot/agent/context.py`
- Create: `tests/agent/test_context_memory_inject.py`

**Context:** `ContextBuilder.__init__` currently creates `self.memory = MemoryStore(workspace)`. After this task it accepts `memory_backend: MemoryBackend | None = None` instead. `build_messages()` becomes async and, when a backend and session_key are provided, injects a system-role block of retrieved context before the conversation history. `build_system_prompt()` removes its MEMORY.md injection call (injection moves to `build_messages()`). `_get_identity()` is backend-aware: shows MEMORY.md workspace tip when no backend, shows tool surface description when a per-turn backend is active.

The memory injection block format (inserted as a `{"role": "system", "content": ...}` entry before history):
```
[Memory — {n} relevant facts]
• fact one (2026-01-10)
• fact two (2026-01-09)
```

When `retrieve()` returns `""` (empty), no block is inserted.

`build_messages()` signature after change:
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
    session_key: str | None = None,   # NEW — if set with memory_backend, triggers retrieval
) -> list[dict[str, Any]]:
```

- [ ] **Step 1: Write the failing tests**

Create `tests/agent/test_context_memory_inject.py`:
```python
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
import pytest

from nanobot.agent.context import ContextBuilder


def _make_workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "workspace"
    ws.mkdir()
    return ws


async def test_build_messages_returns_list(tmp_path):
    ws = _make_workspace(tmp_path)
    ctx = ContextBuilder(ws)
    result = await ctx.build_messages(history=[], current_message="hi")
    assert isinstance(result, list)
    assert result[-1]["role"] == "user"


async def test_build_messages_no_backend_no_injection(tmp_path):
    ws = _make_workspace(tmp_path)
    ctx = ContextBuilder(ws)
    result = await ctx.build_messages(
        history=[], current_message="hi", session_key="telegram:123"
    )
    # Without a backend there is no memory block
    roles = [m["role"] for m in result]
    assert roles.count("system") == 1  # only the main system prompt


async def test_build_messages_with_backend_injects_memory_block(tmp_path):
    ws = _make_workspace(tmp_path)
    mock_backend = MagicMock()
    mock_backend.retrieve = AsyncMock(return_value="[Memory — 1 relevant facts]\n• you like tea (2026-01-01)")
    ctx = ContextBuilder(ws, memory_backend=mock_backend)

    result = await ctx.build_messages(
        history=[], current_message="hi", session_key="telegram:123"
    )

    memory_blocks = [m for m in result if m.get("role") == "system" and "Memory" in (m.get("content") or "")]
    assert len(memory_blocks) == 1
    mock_backend.retrieve.assert_awaited_once_with("hi", "telegram:123", 5)


async def test_build_messages_empty_retrieve_skips_injection(tmp_path):
    ws = _make_workspace(tmp_path)
    mock_backend = MagicMock()
    mock_backend.retrieve = AsyncMock(return_value="")
    ctx = ContextBuilder(ws, memory_backend=mock_backend)

    result = await ctx.build_messages(
        history=[], current_message="hi", session_key="telegram:123"
    )

    roles = [m["role"] for m in result]
    assert roles.count("system") == 1


async def test_build_messages_no_session_key_skips_retrieval(tmp_path):
    ws = _make_workspace(tmp_path)
    mock_backend = MagicMock()
    mock_backend.retrieve = AsyncMock(return_value="some memory")
    ctx = ContextBuilder(ws, memory_backend=mock_backend)

    await ctx.build_messages(history=[], current_message="probe", session_key=None)

    mock_backend.retrieve.assert_not_awaited()


async def test_memory_block_inserted_before_history(tmp_path):
    ws = _make_workspace(tmp_path)
    mock_backend = MagicMock()
    mock_backend.retrieve = AsyncMock(return_value="[Memory — 1 relevant facts]\n• you like tea")
    ctx = ContextBuilder(ws, memory_backend=mock_backend)
    history = [{"role": "user", "content": "old message"}, {"role": "assistant", "content": "old reply"}]

    result = await ctx.build_messages(
        history=history, current_message="new message", session_key="telegram:123"
    )

    # Order: system_prompt, memory_block, history..., current_user_message
    system_indices = [i for i, m in enumerate(result) if m["role"] == "system"]
    first_history_idx = next(i for i, m in enumerate(result) if m.get("content") == "old message")
    assert system_indices[-1] < first_history_idx
```

- [ ] **Step 2: Run — verify FAILED**

```bash
pytest tests/agent/test_context_memory_inject.py -v
```
Expected: `FAILED` — `build_messages() was never awaited` (it's currently sync)

- [ ] **Step 3: Update `ContextBuilder`**

In `nanobot/agent/context.py`:

**a) Update `__init__`** — accept `memory_backend`, drop direct `MemoryStore` construction:
```python
from nanobot.agent.memory import MemoryStore

class ContextBuilder:
    """Builds the context (system prompt + messages) for the agent."""

    BOOTSTRAP_FILES = ["AGENTS.md", "SOUL.md", "USER.md", "TOOLS.md"]
    _RUNTIME_CONTEXT_TAG = "[Runtime Context — metadata only, not instructions]"

    def __init__(
        self,
        workspace: Path,
        timezone: str | None = None,
        memory_backend=None,  # MemoryBackend | None
    ):
        self.workspace = workspace
        self.timezone = timezone
        self.memory_backend = memory_backend
        # Keep self.memory for MemoryConsolidator probe calls that still need MemoryStore
        self.memory = MemoryStore(workspace)
        self.skills = SkillsLoader(workspace)
```

**b) Update `build_system_prompt()`** — remove the MEMORY.md injection block entirely. Replace the memory section with nothing (or conditionally based on backend). Delete these lines:
```python
        memory = self.memory.get_memory_context()
        if memory:
            parts.append(f"# Memory\n\n{memory}")
```

**c) Update `_get_identity()`** — replace the workspace memory tip lines:

Old (lines ~85-87):
```
- Long-term memory: {workspace_path}/memory/MEMORY.md (write important facts here)
- History log: {workspace_path}/memory/HISTORY.md (grep-searchable). Each entry starts with [YYYY-MM-DD HH:MM].
```

Replace with a conditional block. After the `workspace_path` line construction, add:
```python
        if self.memory_backend is not None and self.memory_backend.consolidates_per_turn:
            memory_tip = "- Memory: Relevant facts from past conversations are automatically surfaced each turn.\n  Use memory_search for targeted recall, memory_forget to correct errors, memory_list to audit stored facts."
        else:
            memory_tip = f"- Long-term memory: {workspace_path}/memory/MEMORY.md (write important facts here)\n- History log: {workspace_path}/memory/HISTORY.md (grep-searchable). Each entry starts with [YYYY-MM-DD HH:MM]."
```
And use `{memory_tip}` in the f-string instead of the two hardcoded lines.

**d) Make `build_messages()` async** — add `session_key` param, inject memory block:
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
        session_key: str | None = None,
    ) -> list[dict[str, Any]]:
        """Build the complete message list for an LLM call."""
        runtime_ctx = self._build_runtime_context(channel, chat_id, self.timezone)
        user_content = self._build_user_content(current_message, media)

        if isinstance(user_content, str):
            merged = f"{runtime_ctx}\n\n{user_content}"
        else:
            merged = [{"type": "text", "text": runtime_ctx}] + user_content

        memory_block: list[dict[str, Any]] = []
        if self.memory_backend is not None and session_key is not None:
            retrieved = await self.memory_backend.retrieve(current_message, session_key, 5)
            if retrieved:
                memory_block = [{"role": "system", "content": retrieved}]

        return [
            {"role": "system", "content": self.build_system_prompt(skill_names)},
            *memory_block,
            *history,
            {"role": current_role, "content": merged},
        ]
```

- [ ] **Step 4: Run — verify PASSED**

```bash
pytest tests/agent/test_context_memory_inject.py -v
```

- [ ] **Step 5: Fix any broken existing tests**

Some existing tests call `self.context.build_messages(...)` without `await`. Run:
```bash
pytest tests/ --tb=short -q 2>&1 | grep FAILED
```
For each failure caused by `build_messages` being async, add `await` to the call site in the test. The test file `tests/agent/test_context_prompt_cache.py` may need updating if it calls `build_messages` directly.

- [ ] **Step 6: Run full suite — no regressions**

```bash
pytest --tb=short -q
```
Expected: 660 passed (644 + 16 new), 1 skipped.

- [ ] **Commit**

```
feat(agent): make build_messages async; inject memory backend context block
```

---

## Task 4: `MemoryConsolidator` — `skip_llm` gating + async estimate

**Files:**
- Modify: `nanobot/agent/memory.py`
- Modify: `tests/agent/test_memory_backend.py` (add consolidator tests)

**Context:** Two changes to `MemoryConsolidator`:

1. `maybe_consolidate_by_tokens(session, skip_llm=False)` — when `skip_llm=True`, the loop drops old messages without calling `consolidate_messages()`. This is used when a per-turn backend (Graphiti) is active, since it already captured facts.

2. `estimate_session_prompt_tokens(session)` becomes `async` because `self._build_messages(...)` is now a coroutine (it's `ContextBuilder.build_messages` which is now async). The `_build_messages` type hint is updated accordingly.

The `_build_messages` probe call does NOT pass `session_key`, so it defaults to `None` — no memory retrieval happens during token estimation.

- [ ] **Step 1: Write the failing tests**

Add to `tests/agent/test_memory_backend.py`:
```python
async def test_consolidator_skip_llm_drops_messages_without_llm_call(tmp_path):
    from unittest.mock import AsyncMock, MagicMock, patch
    from nanobot.agent.memory import MemoryConsolidator, MemoryStore
    from nanobot.agent.context import ContextBuilder
    from nanobot.session.manager import SessionManager
    from nanobot.providers.base import GenerationSettings

    provider = MagicMock()
    provider.generation = GenerationSettings(max_tokens=0)
    provider.estimate_prompt_tokens = MagicMock(return_value=(50, "test"))

    ws = tmp_path / "workspace"
    ws.mkdir()
    ctx = ContextBuilder(ws)
    sessions = SessionManager(ws)

    consolidator = MemoryConsolidator(
        workspace=ws,
        provider=provider,
        model="test-model",
        sessions=sessions,
        context_window_tokens=200,
        build_messages=ctx.build_messages,
        get_tool_definitions=MagicMock(return_value=[]),
    )
    consolidator.consolidate_messages = AsyncMock(return_value=True)
    consolidator._SAFETY_BUFFER = 0

    session = sessions.get_or_create("telegram:123")
    session.messages = [
        {"role": "user", "content": "u1", "timestamp": "2026-01-01T00:00:00"},
        {"role": "assistant", "content": "a1", "timestamp": "2026-01-01T00:00:01"},
        {"role": "user", "content": "u2", "timestamp": "2026-01-01T00:00:02"},
        {"role": "assistant", "content": "a2", "timestamp": "2026-01-01T00:00:03"},
    ]

    await consolidator.maybe_consolidate_by_tokens(session, skip_llm=True)

    # LLM consolidation must NOT have been called
    consolidator.consolidate_messages.assert_not_awaited()
    # But session must have been pruned (last_consolidated advanced)
    assert session.last_consolidated > 0


async def test_consolidator_skip_llm_false_still_calls_llm(tmp_path):
    from unittest.mock import AsyncMock, MagicMock
    from nanobot.agent.memory import MemoryConsolidator
    from nanobot.agent.context import ContextBuilder
    from nanobot.session.manager import SessionManager
    from nanobot.providers.base import GenerationSettings

    provider = MagicMock()
    provider.generation = GenerationSettings(max_tokens=0)
    provider.estimate_prompt_tokens = MagicMock(return_value=(1000, "test"))

    ws = tmp_path / "workspace"
    ws.mkdir()
    ctx = ContextBuilder(ws)
    sessions = SessionManager(ws)

    consolidator = MemoryConsolidator(
        workspace=ws,
        provider=provider,
        model="test-model",
        sessions=sessions,
        context_window_tokens=200,
        build_messages=ctx.build_messages,
        get_tool_definitions=MagicMock(return_value=[]),
    )
    consolidator.consolidate_messages = AsyncMock(return_value=True)
    consolidator._SAFETY_BUFFER = 0

    session = sessions.get_or_create("telegram:123")
    session.messages = [
        {"role": "user", "content": "u1", "timestamp": "2026-01-01T00:00:00"},
        {"role": "assistant", "content": "a1", "timestamp": "2026-01-01T00:00:01"},
        {"role": "user", "content": "u2", "timestamp": "2026-01-01T00:00:02"},
        {"role": "assistant", "content": "a2", "timestamp": "2026-01-01T00:00:03"},
    ]

    await consolidator.maybe_consolidate_by_tokens(session, skip_llm=False)

    consolidator.consolidate_messages.assert_awaited()
```

- [ ] **Step 2: Run — verify FAILED**

```bash
pytest tests/agent/test_memory_backend.py -v -k "skip_llm"
```
Expected: `FAILED` — `maybe_consolidate_by_tokens() got unexpected keyword argument 'skip_llm'`

- [ ] **Step 3: Update `MemoryConsolidator` in `nanobot/agent/memory.py`**

**a) Update `_build_messages` type hint** in `MemoryConsolidator.__init__`:
```python
from typing import Awaitable

# Change line 236:
build_messages: Callable[..., Awaitable[list[dict[str, Any]]]],
```

**b) Make `estimate_session_prompt_tokens` async**:
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
            # session_key intentionally omitted → no memory retrieval during probe
        )
        return estimate_prompt_tokens_chain(
            self.provider,
            self.model,
            probe_messages,
            self._get_tool_definitions(),
        )
```

**c) Add `skip_llm` parameter to `maybe_consolidate_by_tokens`** and `await` the now-async estimate:
```python
    async def maybe_consolidate_by_tokens(
        self, session: Session, skip_llm: bool = False
    ) -> None:
        """Loop: archive old messages until prompt fits within safe budget."""
        if not session.messages or self.context_window_tokens <= 0:
            return

        lock = self.get_lock(session.key)
        async with lock:
            budget = self.context_window_tokens - self.max_completion_tokens - self._SAFETY_BUFFER
            target = budget // 2
            estimated, source = await self.estimate_session_prompt_tokens(session)  # now awaited
            if estimated <= 0:
                return
            if estimated < budget:
                logger.debug(
                    "Token consolidation idle {}: {}/{} via {}",
                    session.key,
                    estimated,
                    self.context_window_tokens,
                    source,
                )
                return

            for round_num in range(self._MAX_CONSOLIDATION_ROUNDS):
                if estimated <= target:
                    return

                boundary = self.pick_consolidation_boundary(session, max(1, estimated - target))
                if boundary is None:
                    logger.debug(
                        "Token consolidation: no safe boundary for {} (round {})",
                        session.key,
                        round_num,
                    )
                    return

                end_idx = boundary[0]
                chunk = session.messages[session.last_consolidated:end_idx]
                if not chunk:
                    return

                logger.info(
                    "Token consolidation round {} for {}: {}/{} via {}, chunk={} msgs",
                    round_num,
                    session.key,
                    estimated,
                    self.context_window_tokens,
                    source,
                    len(chunk),
                )

                if not skip_llm:
                    if not await self.consolidate_messages(chunk):
                        return

                session.last_consolidated = end_idx
                self.sessions.save(session)

                estimated, source = await self.estimate_session_prompt_tokens(session)  # now awaited
                if estimated <= 0:
                    return
```

- [ ] **Step 4: Run — verify PASSED**

```bash
pytest tests/agent/test_memory_backend.py -v -k "skip_llm"
```

- [ ] **Step 5: Fix any broken existing consolidation tests**

The existing consolidation tests in `tests/agent/test_loop_consolidation_tokens.py` pass `build_messages=self.context.build_messages`. Since `build_messages` is now async, and `estimate_session_prompt_tokens` now `await`s it, this should work. Run:
```bash
pytest tests/agent/test_loop_consolidation_tokens.py -v
```
If any test fails due to `MagicMock` not being awaitable, replace `MagicMock` with `AsyncMock` for `build_messages` in those tests, or update the `_make_loop` helper to pass `ctx.build_messages` directly.

- [ ] **Step 6: Run full suite — no regressions**

```bash
pytest --tb=short -q
```
Expected: 662 passed (644 + 18 new), 1 skipped.

- [ ] **Commit**

```
feat(agent): gate MemoryConsolidator LLM call via skip_llm; async estimate_session_prompt_tokens
```

---

## Task 5: `AgentLoop` wiring

**Files:**
- Modify: `nanobot/agent/loop.py`
- Create: `tests/agent/test_loop_memory_backend.py`

**Context:** `AgentLoop.__init__` gets a new optional `memory_backend: MemoryBackend | None = None` parameter. When None, it defaults to `MemoryStore(workspace)`. It passes the backend to `ContextBuilder`, registers `backend.get_tools()`, and stores a reference.

`run()` and `process_direct()` both call `await self.memory_backend.start(self.provider)` before processing (deferred init — same pattern used in the QMD branch for `startup_index()`). A `_backend_started` flag prevents double-start.

`_process_message()` changes:
1. `self.context.build_messages(...)` becomes `await self.context.build_messages(..., session_key=key)`
2. Post-turn: when `backend.consolidates_per_turn`, fire `backend.consolidate(turn_messages, key)` as background task
3. `maybe_consolidate_by_tokens(session)` → `maybe_consolidate_by_tokens(session, skip_llm=self.memory_backend.consolidates_per_turn)`

The `turn_messages` to consolidate are the new messages added in this turn: `all_msgs[1 + len(history):]` (everything after the initial system prompt + history).

- [ ] **Step 1: Write the failing tests**

Create `tests/agent/test_loop_memory_backend.py`:
```python
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.agent.memory import MemoryBackend, MemoryStore
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import LLMResponse, GenerationSettings


def _make_loop(tmp_path, memory_backend=None):
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    provider.generation = GenerationSettings(max_tokens=0)
    provider.estimate_prompt_tokens.return_value = (50, "test")
    provider.chat_with_retry = AsyncMock(return_value=LLMResponse(content="ok", tool_calls=[]))
    provider.chat_stream_with_retry = AsyncMock(return_value=LLMResponse(content="ok", tool_calls=[]))

    return AgentLoop(
        bus=MessageBus(),
        provider=provider,
        workspace=tmp_path,
        model="test-model",
        memory_backend=memory_backend,
    )


def test_agent_loop_defaults_to_memory_store_backend(tmp_path):
    loop = _make_loop(tmp_path)
    assert isinstance(loop.memory_backend, MemoryStore)


def test_agent_loop_accepts_custom_backend(tmp_path):
    class FakeBackend(MemoryBackend):
        async def consolidate(self, messages, session_key): pass
        async def retrieve(self, query, session_key, top_k=5): return ""

    backend = FakeBackend()
    loop = _make_loop(tmp_path, memory_backend=backend)
    assert loop.memory_backend is backend


def test_agent_loop_registers_backend_tools(tmp_path):
    from nanobot.agent.tools.base import Tool

    class FakeTool(Tool):
        @property
        def name(self): return "fake_tool"
        @property
        def description(self): return "fake"
        @property
        def parameters(self): return {"type": "object", "properties": {}}
        async def execute(self, **kwargs): return "ok"

    class FakeBackend(MemoryBackend):
        def get_tools(self): return [FakeTool()]
        async def consolidate(self, messages, session_key): pass
        async def retrieve(self, query, session_key, top_k=5): return ""

    loop = _make_loop(tmp_path, memory_backend=FakeBackend())
    assert loop.tools.get("fake_tool") is not None


async def test_agent_loop_calls_backend_start_before_first_message(tmp_path):
    class FakeBackend(MemoryBackend):
        started = False
        async def start(self, provider): self.started = True
        async def consolidate(self, messages, session_key): pass
        async def retrieve(self, query, session_key, top_k=5): return ""

    backend = FakeBackend()
    loop = _make_loop(tmp_path, memory_backend=backend)
    await loop.process_direct("hello", session_key="cli:test")
    assert backend.started is True


async def test_per_turn_backend_consolidate_called_after_message(tmp_path):
    class FakeBackend(MemoryBackend):
        consolidate_calls = []
        @property
        def consolidates_per_turn(self): return True
        async def start(self, provider): pass
        async def consolidate(self, messages, session_key):
            self.consolidate_calls.append(session_key)
        async def retrieve(self, query, session_key, top_k=5): return ""

    backend = FakeBackend()
    loop = _make_loop(tmp_path, memory_backend=backend)
    await loop.process_direct("hello", session_key="telegram:123")
    # Allow background task to complete
    import asyncio
    await asyncio.sleep(0)
    assert "telegram:123" in backend.consolidate_calls
```

- [ ] **Step 2: Run — verify FAILED**

```bash
pytest tests/agent/test_loop_memory_backend.py -v
```
Expected: `FAILED` — `AgentLoop.__init__() got unexpected keyword argument 'memory_backend'`

- [ ] **Step 3: Update `nanobot/agent/loop.py`**

**a) Add import** at the top (with TYPE_CHECKING):
```python
if TYPE_CHECKING:
    from nanobot.config.schema import ChannelsConfig, ExecToolConfig, WebSearchConfig
    from nanobot.cron.service import CronService
    from nanobot.agent.memory import MemoryBackend
```

**b) Add `memory_backend` parameter to `__init__`**:
```python
    def __init__(
        self,
        bus: MessageBus,
        provider: LLMProvider,
        workspace: Path,
        model: str | None = None,
        max_iterations: int = 40,
        context_window_tokens: int = 65_536,
        web_search_config: WebSearchConfig | None = None,
        web_proxy: str | None = None,
        exec_config: ExecToolConfig | None = None,
        cron_service: CronService | None = None,
        restrict_to_workspace: bool = False,
        session_manager: SessionManager | None = None,
        mcp_servers: dict | None = None,
        channels_config: ChannelsConfig | None = None,
        timezone: str | None = None,
        memory_backend: MemoryBackend | None = None,  # NEW
    ):
```

**c) Set `self.memory_backend`** early in `__init__` (after `self.workspace = workspace`):
```python
        from nanobot.agent.memory import MemoryStore
        self.memory_backend = memory_backend if memory_backend is not None else MemoryStore(workspace)
        self._backend_started = False
```

**d) Pass `memory_backend` to `ContextBuilder`**:
```python
        self.context = ContextBuilder(workspace, timezone=timezone, memory_backend=self.memory_backend)
```

**e) Register backend tools** in `_register_default_tools()`, after the existing tool registrations:
```python
        for tool in self.memory_backend.get_tools():
            self.tools.register(tool)
```

**f) Add deferred `_start_backend()` method**:
```python
    async def _start_backend(self) -> None:
        """Start the memory backend once (deferred to avoid event-loop issues at __init__)."""
        if not self._backend_started:
            await self.memory_backend.start(self.provider)
            self._backend_started = True
```

**g) Call `_start_backend()` in `run()`**, after `await self._connect_mcp()`:
```python
    async def run(self) -> None:
        self._running = True
        await self._connect_mcp()
        await self._start_backend()   # NEW
        logger.info("Agent loop started")
        ...
```

**h) Call `_start_backend()` in `process_direct()`**, after `await self._connect_mcp()`:
```python
    async def process_direct(self, content, ...):
        await self._connect_mcp()
        await self._start_backend()   # NEW
        msg = InboundMessage(...)
        return await self._process_message(...)
```

**i) Update both `build_messages` call sites** in `_process_message()` to be `await`ed and pass `session_key`:

Replace (line ~409):
```python
            messages = self.context.build_messages(
                history=history,
                current_message=msg.content, channel=channel, chat_id=chat_id,
                current_role=current_role,
            )
```
With:
```python
            messages = await self.context.build_messages(
                history=history,
                current_message=msg.content, channel=channel, chat_id=chat_id,
                current_role=current_role,
                session_key=key,
            )
```

Replace (line ~444):
```python
        initial_messages = self.context.build_messages(
            history=history,
            current_message=msg.content,
            media=msg.media if msg.media else None,
            channel=msg.channel, chat_id=msg.chat_id,
        )
```
With:
```python
        initial_messages = await self.context.build_messages(
            history=history,
            current_message=msg.content,
            media=msg.media if msg.media else None,
            channel=msg.channel, chat_id=msg.chat_id,
            session_key=key,
        )
```

**j) Fire per-turn consolidation and update `maybe_consolidate_by_tokens` call**:

After `self._save_turn(session, all_msgs, 1 + len(history))`, add per-turn consolidation dispatch. Replace (line ~473):
```python
        self._schedule_background(self.memory_consolidator.maybe_consolidate_by_tokens(session))
```
With:
```python
        if self.memory_backend.consolidates_per_turn:
            turn_messages = all_msgs[1 + len(history):]
            self._schedule_background(
                self.memory_backend.consolidate(turn_messages, key)
            )
        self._schedule_background(
            self.memory_consolidator.maybe_consolidate_by_tokens(
                session, skip_llm=self.memory_backend.consolidates_per_turn
            )
        )
```

Do the same for the system-message path (line ~420):
```python
        self._schedule_background(self.memory_consolidator.maybe_consolidate_by_tokens(session))
```
→
```python
        if self.memory_backend.consolidates_per_turn:
            turn_messages = all_msgs[1 + len(history):]
            self._schedule_background(
                self.memory_backend.consolidate(turn_messages, key)
            )
        self._schedule_background(
            self.memory_consolidator.maybe_consolidate_by_tokens(
                session, skip_llm=self.memory_backend.consolidates_per_turn
            )
        )
```

- [ ] **Step 4: Run — verify PASSED**

```bash
pytest tests/agent/test_loop_memory_backend.py -v
```

- [ ] **Step 5: Run full suite — no regressions**

```bash
pytest --tb=short -q
```
Expected: 667 passed (644 + 23 new), 1 skipped.

- [ ] **Commit**

```
feat(agent): wire MemoryBackend into AgentLoop; per-turn consolidation dispatch
```

---

## Task 6: CLI wiring — `load_memory_backend` utility

**Files:**
- Modify: `nanobot/agent/loop.py` (add `load_memory_backend` function)
- Modify: `nanobot/cli/commands.py` (two AgentLoop creation sites)

**Context:** A standalone function `load_memory_backend(config)` discovers installed `nanobot.memory` entry-points and returns the appropriate backend. It reads `config.memory.backend` to select which entry-point to load. If `"default"` or no matching entry-point, returns `MemoryStore(config.workspace_path)`.

- [ ] **Step 1: Add `load_memory_backend` to `nanobot/agent/loop.py`**

Add after the imports, before the `AgentLoop` class:
```python
def load_memory_backend(config: Any) -> "MemoryBackend":
    """Discover and instantiate the configured memory backend from installed entry-points.

    Falls back to the built-in MemoryStore when:
    - ``config.memory.backend`` is ``"default"``
    - No matching entry-point is registered
    """
    from importlib.metadata import entry_points
    from nanobot.agent.memory import MemoryStore

    backend_name = getattr(getattr(config, "memory", None), "backend", "default")
    if backend_name == "default":
        return MemoryStore(config.workspace_path)

    for ep in entry_points(group="nanobot.memory"):
        if ep.name == backend_name:
            backend_cls = ep.load()
            return backend_cls(config)

    logger.warning(
        "Memory backend '{}' not found in nanobot.memory entry-points; "
        "falling back to default MemoryStore",
        backend_name,
    )
    return MemoryStore(config.workspace_path)
```

- [ ] **Step 2: Update both `AgentLoop` creation sites in `nanobot/cli/commands.py`**

Import at the top of the affected function (or at the file level if already imported):
```python
from nanobot.agent.loop import AgentLoop, load_memory_backend
```

For both `AgentLoop(...)` calls (lines ~537 and ~743), add `memory_backend=load_memory_backend(config)`:

```python
    agent = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=config.workspace_path,
        ...
        memory_backend=load_memory_backend(config),   # NEW
    )
```

- [ ] **Step 3: Run full suite — no regressions**

```bash
pytest --tb=short -q
```
Expected: still 667 passed, 1 skipped (no new tests in this task).

- [ ] **Commit**

```
feat(agent): add load_memory_backend entry-point discovery; wire into CLI
```

---

## Self-Review Checklist (done inline above)

- **Spec coverage:** ✓ MemoryBackend ABC (Task 2), MemoryStore impl (Task 2), async build_messages (Task 3), memory injection (Task 3), identity update (Task 3), consolidates_per_turn gating (Task 4), AgentLoop wiring (Task 5), entry-point discovery (Task 6), config field (Task 1)
- **No placeholders:** All steps contain complete code
- **Type consistency:** `MemoryBackend` used consistently; `skip_llm: bool` matches call sites; `session_key: str | None = None` matches all call sites
- **Call site coverage:** All three `build_messages` call sites updated (loop.py:409, loop.py:444, memory.py:284 probe via async chain)
