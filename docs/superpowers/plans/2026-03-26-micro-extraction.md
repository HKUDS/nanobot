# Micro-Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add per-turn lightweight memory extraction so short sessions (< 50 messages) persist learned facts to the memory database.

**Architecture:** A standalone `MicroExtractor` class in `nanobot/memory/write/` calls `gpt-4o-mini` asynchronously after each agent turn to extract memory events. Events flow through the existing `EventIngester` pipeline (dedup, embed, graph). Feature-gated, opt-in.

**Tech Stack:** Python 3.10+, asyncio, pytest, pytest-asyncio

**Spec:** `docs/superpowers/specs/2026-03-26-micro-extraction-design.md`

---

### Task 1: Add config fields

**Files:**
- Modify: `nanobot/config/schema.py:291-295` (after `skills_enabled`)
- Test: `tests/test_micro_extraction.py` (create)

- [ ] **Step 1: Write the test for config fields**

Create `tests/test_micro_extraction.py`:

```python
"""Tests for micro-extraction (per-turn memory extraction)."""

from __future__ import annotations


def test_config_defaults():
    """Micro-extraction config fields exist with correct defaults."""
    from nanobot.config.schema import AgentConfig

    config = AgentConfig()
    assert config.micro_extraction_enabled is False
    assert config.micro_extraction_model is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_micro_extraction.py -v`
Expected: FAIL — `micro_extraction_enabled` does not exist on AgentConfig.

- [ ] **Step 3: Add config fields**

In `nanobot/config/schema.py`, add after the `streaming_enabled` field (around line 295):

```python
    # Micro-extraction: per-turn lightweight memory extraction
    micro_extraction_enabled: bool = False  # Feature gate (opt-in)
    micro_extraction_model: str | None = None  # None = "gpt-4o-mini"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_micro_extraction.py -v`
Expected: PASS

- [ ] **Step 5: Run lint and typecheck**

Run: `make lint && make typecheck`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add nanobot/config/schema.py tests/test_micro_extraction.py
git commit -m "feat: add micro_extraction config fields"
```

---

### Task 2: Create extraction prompt and tool schema

**Files:**
- Create: `nanobot/templates/prompts/micro_extract.md`
- Modify: `nanobot/memory/write/micro_extractor.py` (create with constants only)
- Test: `tests/test_micro_extraction.py` (add schema tests)

- [ ] **Step 1: Write schema tests**

Append to `tests/test_micro_extraction.py`:

```python
from nanobot.memory.write.micro_extractor import _MICRO_EXTRACT_TOOL


def test_tool_schema_has_required_fields():
    """Tool schema requires events array."""
    schema = _MICRO_EXTRACT_TOOL[0]["function"]["parameters"]
    assert "events" in schema["properties"]
    assert "events" in schema["required"]


def test_tool_schema_event_types():
    """Event type enum has all 6 valid types."""
    items = _MICRO_EXTRACT_TOOL[0]["function"]["parameters"]["properties"]["events"]["items"]
    expected = {"preference", "fact", "task", "decision", "constraint", "relationship"}
    assert set(items["properties"]["type"]["enum"]) == expected


def test_tool_schema_event_required_fields():
    """Each event requires type and summary."""
    items = _MICRO_EXTRACT_TOOL[0]["function"]["parameters"]["properties"]["events"]["items"]
    assert set(items["required"]) == {"type", "summary"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_micro_extraction.py -v`
Expected: FAIL — `micro_extractor` module does not exist.

- [ ] **Step 3: Create the prompt template**

Create `nanobot/templates/prompts/micro_extract.md`:

```markdown
You are a memory extraction agent. Analyze this conversation exchange and extract any facts, preferences, decisions, corrections, or relationships worth remembering across sessions.

Return ONLY items that would be valuable in future conversations. Skip:
- Greetings, acknowledgments, small talk
- Transient task details (tool outputs, intermediate steps)
- Information the assistant already knows from its training

If nothing is worth remembering, call the tool with an empty events array.
```

- [ ] **Step 4: Create micro_extractor.py with constants**

Create `nanobot/memory/write/micro_extractor.py`:

```python
"""Lightweight per-turn memory extraction.

Extracts structured memory events from individual conversation turns
using a cheap model (default: gpt-4o-mini). Events flow through the
existing EventIngester pipeline for deduplication, embedding, and
graph ingestion.

This is a best-effort optimization — full consolidation remains the
authoritative memory pipeline. See the design spec at
``docs/superpowers/specs/2026-03-26-micro-extraction-design.md``.
"""

from __future__ import annotations

from typing import Any

_MICRO_EXTRACT_TOOL: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "save_events",
            "description": (
                "Save extracted memory events. "
                "Return empty array if nothing worth remembering."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "events": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "type": {
                                    "type": "string",
                                    "enum": [
                                        "preference",
                                        "fact",
                                        "task",
                                        "decision",
                                        "constraint",
                                        "relationship",
                                    ],
                                },
                                "summary": {"type": "string"},
                                "entities": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                                "confidence": {"type": "number"},
                            },
                            "required": ["type", "summary"],
                        },
                    },
                },
                "required": ["events"],
            },
        },
    }
]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_micro_extraction.py -v`
Expected: PASS

- [ ] **Step 6: Update prompt manifest**

Run: `python scripts/check_prompt_manifest.py --update`

- [ ] **Step 7: Run lint and typecheck**

Run: `make lint && make typecheck`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add nanobot/templates/prompts/micro_extract.md nanobot/memory/write/micro_extractor.py tests/test_micro_extraction.py prompts_manifest.json
git commit -m "feat: add micro-extraction prompt template and tool schema"
```

---

### Task 3: Implement MicroExtractor class

**Files:**
- Modify: `nanobot/memory/write/micro_extractor.py` (add class)
- Test: `tests/test_micro_extraction.py` (add class tests)

- [ ] **Step 1: Write unit tests for MicroExtractor**

Append to `tests/test_micro_extraction.py`:

```python
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot.memory.write.micro_extractor import MicroExtractor


def _make_tool_response(events: list[dict]) -> MagicMock:
    """Create a mock LLM response with a save_events tool call."""
    tc = MagicMock()
    tc.name = "save_events"
    tc.arguments = {"events": events}
    resp = MagicMock()
    resp.tool_calls = [tc]
    resp.content = None
    return resp


def _make_text_response(text: str) -> MagicMock:
    """Create a mock LLM response with no tool calls."""
    resp = MagicMock()
    resp.tool_calls = []
    resp.content = text
    return resp


class TestMicroExtractor:
    """Tests for MicroExtractor."""

    def setup_method(self):
        self.provider = AsyncMock()
        self.ingester = MagicMock()
        self.ingester.append_events = MagicMock(return_value=2)

    def _make_extractor(self, *, enabled: bool = True) -> MicroExtractor:
        return MicroExtractor(
            provider=self.provider,
            ingester=self.ingester,
            model="test-model",
            enabled=enabled,
        )

    @pytest.mark.asyncio
    async def test_submit_when_disabled_does_nothing(self):
        ext = self._make_extractor(enabled=False)
        await ext.submit("hello", "hi there")
        await asyncio.sleep(0.05)  # let any tasks run
        self.provider.chat.assert_not_called()

    @pytest.mark.asyncio
    async def test_submit_extracts_and_ingests_events(self):
        events = [
            {"type": "fact", "summary": "User works on DS10540"},
            {"type": "relationship", "summary": "Alice is the project lead"},
        ]
        self.provider.chat = AsyncMock(return_value=_make_tool_response(events))
        ext = self._make_extractor()
        await ext.submit("I work on DS10540 with Alice", "Got it!")
        await asyncio.sleep(0.1)  # let background task complete
        self.ingester.append_events.assert_called_once()
        written = self.ingester.append_events.call_args[0][0]
        assert len(written) == 2
        assert written[0]["summary"] == "User works on DS10540"

    @pytest.mark.asyncio
    async def test_submit_empty_events_skips_ingestion(self):
        self.provider.chat = AsyncMock(return_value=_make_tool_response([]))
        ext = self._make_extractor()
        await ext.submit("ok thanks", "You're welcome!")
        await asyncio.sleep(0.1)
        self.ingester.append_events.assert_not_called()

    @pytest.mark.asyncio
    async def test_submit_no_tool_call_skips_ingestion(self):
        self.provider.chat = AsyncMock(return_value=_make_text_response("Nothing to save."))
        ext = self._make_extractor()
        await ext.submit("ok thanks", "You're welcome!")
        await asyncio.sleep(0.1)
        self.ingester.append_events.assert_not_called()

    @pytest.mark.asyncio
    async def test_submit_is_nonblocking(self):
        """submit() returns immediately without waiting for extraction."""
        async def slow_chat(**kwargs):
            await asyncio.sleep(10)
            return _make_tool_response([])

        self.provider.chat = slow_chat
        ext = self._make_extractor()
        await ext.submit("test", "test")
        # If submit blocked, we'd never reach this line within the test timeout
        assert len(ext._pending_tasks) == 1

    @pytest.mark.asyncio
    async def test_submit_failure_logs_warning(self):
        self.provider.chat = AsyncMock(side_effect=RuntimeError("API down"))
        ext = self._make_extractor()
        await ext.submit("test", "test")
        await asyncio.sleep(0.1)
        # No exception propagated — task completed silently
        self.ingester.append_events.assert_not_called()

    @pytest.mark.asyncio
    async def test_submit_ingestion_failure_logs_warning(self):
        self.provider.chat = AsyncMock(
            return_value=_make_tool_response([{"type": "fact", "summary": "test"}])
        )
        self.ingester.append_events = MagicMock(side_effect=RuntimeError("DB error"))
        ext = self._make_extractor()
        await ext.submit("test", "test")
        await asyncio.sleep(0.1)
        # No exception propagated
        self.ingester.append_events.assert_called_once()

    @pytest.mark.asyncio
    async def test_submit_parses_string_arguments(self):
        """LLM may return tool arguments as a JSON string instead of dict."""
        events = [{"type": "fact", "summary": "User likes Python"}]
        tc = MagicMock()
        tc.name = "save_events"
        tc.arguments = json.dumps({"events": events})  # string, not dict
        resp = MagicMock()
        resp.tool_calls = [tc]
        resp.content = None
        self.provider.chat = AsyncMock(return_value=resp)
        ext = self._make_extractor()
        await ext.submit("I like Python", "Noted!")
        await asyncio.sleep(0.1)
        self.ingester.append_events.assert_called_once()
        written = self.ingester.append_events.call_args[0][0]
        assert written[0]["summary"] == "User likes Python"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_micro_extraction.py::TestMicroExtractor -v`
Expected: FAIL — `MicroExtractor` class does not exist.

- [ ] **Step 3: Implement MicroExtractor class**

Add to `nanobot/memory/write/micro_extractor.py` (after the `_MICRO_EXTRACT_TOOL` constant):

```python
import asyncio
import json

from loguru import logger

from nanobot.context.prompt_loader import prompts

if TYPE_CHECKING:
    from nanobot.memory.write.ingester import EventIngester
    from nanobot.providers.base import LLMProvider


class MicroExtractor:
    """Lightweight per-turn memory extraction.

    After each agent turn, extracts structured memory events from the
    user message + assistant response. Runs asynchronously in the
    background. Events are written to the same SQLite events table
    used by full consolidation.
    """

    def __init__(
        self,
        *,
        provider: LLMProvider,
        ingester: EventIngester,
        model: str = "gpt-4o-mini",
        enabled: bool = False,
    ) -> None:
        self._provider = provider
        self._ingester = ingester
        self._model = model
        self._enabled = enabled
        self._pending_tasks: set[asyncio.Task[None]] = set()

    async def submit(self, user_message: str, assistant_message: str) -> None:
        """Submit a turn for background extraction. Returns immediately."""
        if not self._enabled:
            return
        task = asyncio.create_task(
            self._extract_and_ingest(user_message, assistant_message)
        )
        self._pending_tasks.add(task)
        task.add_done_callback(self._pending_tasks.discard)

    async def _extract_and_ingest(
        self, user_message: str, assistant_message: str
    ) -> None:
        """Call LLM to extract events, then ingest them."""
        try:
            prompt = prompts.get("micro_extract")
            messages = [
                {"role": "system", "content": prompt},
                {"role": "user", "content": user_message},
                {"role": "assistant", "content": assistant_message},
            ]
            response = await self._provider.chat(
                messages=messages,
                model=self._model,
                tools=_MICRO_EXTRACT_TOOL,
                temperature=0.0,
                max_tokens=500,
            )
            events = self._parse_events(response)
            if not events:
                return
            await asyncio.to_thread(self._ingester.append_events, events)
            logger.info("Micro-extraction: {} event(s) ingested", len(events))
        except Exception:  # crash-barrier: best-effort background extraction
            logger.warning("Micro-extraction failed (will be caught by consolidation)")

    @staticmethod
    def _parse_events(response: Any) -> list[dict[str, Any]]:
        """Extract events list from LLM tool call response."""
        if not response.tool_calls:
            return []
        tc = response.tool_calls[0]
        args = tc.arguments
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except (json.JSONDecodeError, TypeError):
                return []
        if not isinstance(args, dict):
            return []
        events = args.get("events", [])
        if not isinstance(events, list):
            return []
        return [e for e in events if isinstance(e, dict) and e.get("type") and e.get("summary")]
```

Also update the imports at the top of the file — add `TYPE_CHECKING` guard:

```python
from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Any

from loguru import logger

from nanobot.context.prompt_loader import prompts

if TYPE_CHECKING:
    from nanobot.memory.write.ingester import EventIngester
    from nanobot.providers.base import LLMProvider
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_micro_extraction.py -v`
Expected: PASS

- [ ] **Step 5: Run lint and typecheck**

Run: `make lint && make typecheck`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add nanobot/memory/write/micro_extractor.py tests/test_micro_extraction.py
git commit -m "feat: implement MicroExtractor class with async background extraction"
```

---

### Task 4: Wire MicroExtractor into agent factory and message processor

**Files:**
- Modify: `nanobot/agent/agent_components.py:97-110` (add field to `_ProcessorServices`)
- Modify: `nanobot/agent/agent_factory.py` (construct and pass MicroExtractor)
- Modify: `nanobot/agent/message_processor.py:39-69` (receive and store) and `~404` (call submit)
Note: `MicroExtractor` is imported directly from its module (`nanobot.memory.write.micro_extractor`), matching the existing pattern — other classes in `memory/write/` are not exported from `__init__.py`.

Note: There are two `_save_turn` call sites in `_process_message`. The system-message path (line ~209) is intentionally excluded — it handles internal routing, not user-facing exchanges.

- [ ] **Step 1: Add MicroExtractor to _ProcessorServices**

In `nanobot/agent/agent_components.py`, add the import and field:

Under `TYPE_CHECKING` imports, add:
```python
    from nanobot.memory.write.micro_extractor import MicroExtractor
```

In `_ProcessorServices` (after `span_module`):
```python
    micro_extractor: MicroExtractor | None = None
```

- [ ] **Step 2: Update MessageProcessor to receive and use MicroExtractor**

In `nanobot/agent/message_processor.py`, in `__init__`:
```python
        self._micro_extractor = services.micro_extractor
```

After `self.sessions.save(session)` (~line 405), add:
```python
            # Micro-extraction: per-turn memory extraction (async, non-blocking)
            if self._micro_extractor is not None and final_content:
                await self._micro_extractor.submit(
                    user_message=msg.content,
                    assistant_message=final_content,
                )
```

- [ ] **Step 3: Construct MicroExtractor in agent_factory.py**

In `build_agent()`, after constructing the memory store and before constructing `_ProcessorServices`, add:

```python
    # 12.6 Construct MicroExtractor (per-turn memory extraction)
    from nanobot.memory.write.micro_extractor import MicroExtractor

    _micro_extractor: MicroExtractor | None = None
    if config.micro_extraction_enabled:
        _micro_extractor = MicroExtractor(
            provider=provider,
            ingester=memory.ingester,
            model=config.micro_extraction_model or "gpt-4o-mini",
            enabled=True,
        )
```

Pass it to `_ProcessorServices`:
```python
    services = _ProcessorServices(
        ...
        micro_extractor=_micro_extractor,
    )
```

- [ ] **Step 4: Run lint and typecheck**

Run: `make lint && make typecheck`
Expected: PASS

- [ ] **Step 5: Run full test suite**

Run: `make test`
Expected: PASS — no regressions (micro-extraction is disabled by default).

- [ ] **Step 6: Commit**

```bash
git add nanobot/agent/agent_components.py nanobot/agent/agent_factory.py nanobot/agent/message_processor.py
git commit -m "feat: wire MicroExtractor into agent factory and message processor"
```

---

### Task 5: Integration test with real LLM

**Files:**
- Create: `tests/integration/test_micro_extraction.py`

- [ ] **Step 1: Write integration test**

Create `tests/integration/test_micro_extraction.py`:

```python
"""Integration test for micro-extraction with real LLM."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from nanobot.memory.store import MemoryStore
from nanobot.memory.write.micro_extractor import MicroExtractor


@pytest.mark.skipif(
    not os.environ.get("OPENAI_API_KEY"),
    reason="OPENAI_API_KEY not set — skipping LLM integration test",
)
@pytest.mark.asyncio
async def test_micro_extraction_real_llm(tmp_path: Path) -> None:
    """Micro-extraction produces valid events from a realistic exchange."""
    from nanobot.providers.openai import OpenAIProvider

    provider = OpenAIProvider(api_key=os.environ["OPENAI_API_KEY"])
    store = MemoryStore(tmp_path)

    extractor = MicroExtractor(
        provider=provider,
        ingester=store.ingester,
        model="gpt-4o-mini",
        enabled=True,
    )

    await extractor.submit(
        user_message="I always work on the DS10540 project with Alice. We use PostgreSQL for the database.",
        assistant_message="Got it! I'll remember that you work on DS10540 with Alice and that the project uses PostgreSQL.",
    )

    # Wait for background task to complete deterministically
    if extractor._pending_tasks:
        await asyncio.gather(*extractor._pending_tasks, return_exceptions=True)

    # Verify events were ingested into the database
    events = store.ingester.read_events(limit=20)
    assert len(events) > 0, "Expected at least one event to be extracted"

    # Check that extracted events contain relevant content
    summaries = " ".join(e.get("summary", "") for e in events).lower()
    assert any(
        term in summaries for term in ["ds10540", "alice", "postgresql"]
    ), f"Expected relevant entities in summaries, got: {summaries}"
```

- [ ] **Step 2: Run integration test**

Run: `python -m pytest tests/integration/test_micro_extraction.py -v`
Expected: PASS (if OPENAI_API_KEY is set), SKIP (if not).

- [ ] **Step 3: Run full validation**

Run: `make check`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_micro_extraction.py
git commit -m "test: add real-LLM integration test for micro-extraction"
```

---

### Task 6: Update prompt manifest and documentation

**Files:**
- Modify: `prompts_manifest.json` (auto-updated)
- Modify: `docs/memory-system-reference.md` (add micro-extraction section)

- [ ] **Step 1: Update prompt manifest**

Run: `python scripts/check_prompt_manifest.py --update`

- [ ] **Step 2: Add micro-extraction to memory reference doc**

Add a section to `docs/memory-system-reference.md` under the Configuration Parameters table:

```markdown
## Micro-Extraction (Per-Turn)

When `micro_extraction_enabled: true`, a lightweight extraction runs after every agent turn:

1. User message + assistant response sent to `gpt-4o-mini` (configurable via `micro_extraction_model`)
2. Model extracts structured events (facts, preferences, decisions, etc.) or returns empty array
3. Events ingested via `EventIngester` — dedup, embed, graph all happen automatically
4. Runs as async background task — zero latency impact on response

This ensures short sessions (< 50 messages) persist learned information. Full consolidation
remains the authoritative pipeline for profile updates, history, and snapshot rebuilds.

| Config Field | Default | Purpose |
|---|---|---|
| `micro_extraction_enabled` | `false` | Feature gate |
| `micro_extraction_model` | `null` (= gpt-4o-mini) | Model for extraction |
```

- [ ] **Step 3: Run lint**

Run: `make lint && make typecheck`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add prompts_manifest.json docs/memory-system-reference.md
git commit -m "docs: update memory reference and prompt manifest for micro-extraction"
```
