# LLM Trace Hook Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Record every LLM request/response as JSONL trace files, one file per session_key, for debugging and cost analysis.

**Architecture:** A new `TraceHook` (subclass of `AgentHook`) captures full request context in `before_iteration` and writes the complete trace entry in `after_iteration`. Injected via existing `hooks=` parameter on `AgentLoop`. Config-driven enable/disable via new `TraceConfig` in schema.

**Tech Stack:** Python dataclass, asyncio.to_thread for non-blocking file I/O, Pydantic config model.

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `nanobot/agent/trace.py` | **Create** | `TraceHook` class (~60 lines) |
| `nanobot/config/schema.py` | **Modify** | Add `TraceConfig` + wire into `Config` |
| `nanobot/agent/loop.py` | **Modify** | Set `trace_hook.session_key` before runner.run() |
| `nanobot/cli/commands.py` | **Modify** | Create TraceHook and inject via `hooks=` |

---

## Chunk 1: TraceConfig + TraceHook + Wiring

### Task 1: Add TraceConfig to config schema

**Files:**
- Modify: `nanobot/config/schema.py`

- [ ] **Step 1: Add TraceConfig class after ExecToolConfig**

```python
class TraceConfig(Base):
    """LLM request/response trace logging."""

    enabled: bool = True
```

- [ ] **Step 2: Add trace field to Config**

In the `Config` class, add after `tts`:

```python
    trace: TraceConfig = Field(default_factory=TraceConfig)
```

- [ ] **Step 3: Verify syntax**

Run: `python3 -c "import ast; ast.parse(open('nanobot/config/schema.py').read()); print('OK')"`
Expected: OK

- [ ] **Step 4: Commit**

```bash
git add nanobot/config/schema.py
git commit -m "feat(config): add TraceConfig for LLM request logging"
```

---

### Task 2: Create TraceHook

**Files:**
- Create: `nanobot/agent/trace.py`

- [ ] **Step 1: Write TraceHook implementation**

```python
"""LLM request/response trace logger.

Appends one JSONL line per LLM call to {traces_dir}/{session_key}.jsonl.
Injected as an AgentHook — zero coupling to provider or runner internals.
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.agent.hook import AgentHook, AgentHookContext
from nanobot.utils.helpers import safe_filename


class TraceHook(AgentHook):
    """Record every LLM call as a JSONL trace entry."""

    __slots__ = ("_traces_dir", "_session_key", "_call_t0", "_call_kwargs")

    def __init__(self, traces_dir: Path) -> None:
        self._traces_dir = traces_dir
        self._traces_dir.mkdir(parents=True, exist_ok=True)
        self._session_key: str = "unknown"
        self._call_t0: float = 0
        self._call_kwargs: dict[str, Any] = {}

    @property
    def session_key(self) -> str:
        return self._session_key

    @session_key.setter
    def session_key(self, value: str) -> None:
        self._session_key = value

    async def before_iteration(self, context: AgentHookContext) -> None:
        """Snapshot request state and start timer."""
        self._call_t0 = time.monotonic()
        self._call_kwargs = {
            "message_count": len(context.messages),
            "messages": self._sanitize_messages(context.messages),
        }

    async def after_iteration(self, context: AgentHookContext) -> None:
        """Build trace entry and append to file."""
        from datetime import datetime, timezone

        elapsed_ms = int((time.monotonic() - self._call_t0) * 1000)
        resp = context.response

        entry: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "session_key": self._session_key,
            "iteration": context.iteration,
            "request": self._call_kwargs,
            "response": {
                "content": (resp.content or "")[:2000] if resp else None,
                "tool_calls": [
                    {"name": tc.name, "arguments": tc.arguments}
                    for tc in (context.tool_calls or [])
                ],
                "finish_reason": resp.finish_reason if resp else None,
                "usage": dict(context.usage),
            },
            "elapsed_ms": elapsed_ms,
        }

        path = self._traces_dir / f"{safe_filename(self._session_key.replace(':', '_'))}.jsonl"
        line = json.dumps(entry, ensure_ascii=False, default=str)
        try:
            await asyncio.to_thread(self._append_line, path, line)
        except Exception:
            logger.warning("Failed to write trace entry to {}", path)

    @staticmethod
    def _append_line(path: Path, line: str) -> None:
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")

    @staticmethod
    def _sanitize_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Replace base64 image payloads with placeholders."""
        out: list[dict[str, Any]] = []
        for msg in messages:
            content = msg.get("content")
            if isinstance(content, list):
                sanitized: list[dict[str, Any]] = []
                for block in content:
                    if (
                        isinstance(block, dict)
                        and block.get("type") == "image_url"
                        and isinstance(block.get("image_url"), dict)
                        and str(block["image_url"].get("url", "")).startswith("data:")
                    ):
                        path = (block.get("_meta") or {}).get("path", "")
                        sanitized.append({"type": "text", "text": f"[image: {path}]" if path else "[image]"})
                    else:
                        sanitized.append(block)
                out.append({**msg, "content": sanitized})
            else:
                out.append(msg)
        return out
```

- [ ] **Step 2: Verify syntax**

Run: `python3 -c "import ast; ast.parse(open('nanobot/agent/trace.py').read()); print('OK')"`
Expected: OK

- [ ] **Step 3: Commit**

```bash
git add nanobot/agent/trace.py
git commit -m "feat(agent): add TraceHook for LLM request/response logging"
```

---

### Task 3: Wire TraceHook into AgentLoop

**Files:**
- Modify: `nanobot/agent/loop.py` (~3 lines)
- Modify: `nanobot/cli/commands.py` (~8 lines)

- [ ] **Step 1: Set session_key in _run_agent_loop**

In `nanobot/agent/loop.py`, inside `_run_agent_loop`, before `result = await self.runner.run(...)`, add:

```python
        # Set session_key on trace hooks for file routing
        for h in self._extra_hooks:
            if hasattr(h, "session_key"):
                h.session_key = f"{channel}:{chat_id}"
```

- [ ] **Step 2: Create and inject TraceHook in gateway entry (cli/commands.py)**

In the gateway `_run_gateway` function, after `provider = _make_provider(config)`, add:

```python
    # LLM trace logging
    hooks: list = []
    if config.trace.enabled:
        from nanobot.agent.trace import TraceHook
        hooks.append(TraceHook(traces_dir=config.workspace_path / "traces"))
```

Then pass `hooks=hooks` to `AgentLoop(...)`.

- [ ] **Step 3: Same for CLI chat entry**

In the `_run_chat` function, same pattern — create TraceHook and pass to AgentLoop `hooks=`.

- [ ] **Step 4: Verify syntax on both files**

Run: `python3 -c "import ast; ast.parse(open('nanobot/agent/loop.py').read()); ast.parse(open('nanobot/cli/commands.py').read()); print('OK')"`
Expected: OK

- [ ] **Step 5: Commit**

```bash
git add nanobot/agent/loop.py nanobot/cli/commands.py
git commit -m "feat(agent): wire TraceHook into gateway and CLI entry points"
```

---

### Task 4: Manual smoke test

- [ ] **Step 1: Touch config to restart nanobot**

```bash
touch ~/.nanobot/config.json
```

- [ ] **Step 2: Send a test message and verify trace file**

After sending a message, check:

```bash
ls ~/.nanobot/workspace/traces/
cat ~/.nanobot/workspace/traces/discord_*.jsonl | python3 -m json.tool | head -30
```

Expected: JSONL file exists with request messages, response content, usage, elapsed_ms.

- [ ] **Step 3: Verify images are sanitized**

Check that no `data:image/` payloads appear in trace files:

```bash
grep -c "data:image" ~/.nanobot/workspace/traces/*.jsonl
```

Expected: 0 matches

- [ ] **Step 4: Verify disable works**

Add `"trace": {"enabled": false}` to config.json, touch config, send message, verify no new trace entries.

- [ ] **Step 5: Final commit with push**

```bash
git push origin HEAD
```
