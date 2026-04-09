# Code Review Fixes Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 8 issues identified in code review — security, correctness, readability, architecture.

**Architecture:** Surgical fixes to existing files. No new files. No new dependencies. The biggest refactor is replacing the 6-tuple return from `_run_agent_loop` with `AgentRunResult` dataclass passthrough.

**Tech Stack:** Python 3.12, anthropic SDK, asyncio

---

## Chunk 1: Security & Correctness Fixes

### Task 1: OAuth credentials file permission (0o600)

**Files:**
- Modify: `nanobot/providers/oauth_store.py:62-64`

- [ ] **Step 1: Add os import and chmod after write**

In `oauth_store.py`, method `save()`, add `os.chmod` after writing:

```python
import os  # add to top-level imports

def save(self, creds: OAuthCredentials) -> None:
    """Persist credentials to the nanobot store file."""
    self._store_path.parent.mkdir(parents=True, exist_ok=True)
    data = asdict(creds)
    self._store_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.chmod(self._store_path, 0o600)
    logger.debug("OAuth credentials saved to {}", self._store_path)
```

- [ ] **Step 2: Run existing tests**

Run: `cd /root/git_code/nanobot && source .venv/bin/activate && pytest tests/providers/test_oauth_store.py -v`
Expected: All PASS

- [ ] **Step 3: Commit**

```bash
git add nanobot/providers/oauth_store.py
git commit -m "fix(oauth): set 0o600 permission on credentials file"
```

---

### Task 2: Update auth_token in-place instead of recreating client

**Files:**
- Modify: `nanobot/providers/anthropic_provider.py:126-139` (_update_oauth_client)
- Modify: `nanobot/providers/anthropic_provider.py:140-170` (_ensure_valid_token)

- [ ] **Step 1: Replace `_update_oauth_client` — just set `auth_token`**

Replace the entire `_update_oauth_client` method:

```python
def _update_oauth_token(self, new_access_token: str) -> None:
    """Update the OAuth token on the existing client (no reconnect)."""
    self._client.auth_token = new_access_token
    logger.debug("AnthropicProvider: OAuth token updated in-place")
```

- [ ] **Step 2: Update `_ensure_valid_token` to call new method name**

In `_ensure_valid_token`, change:
```python
self._update_oauth_client(new_creds.access_token)
```
to:
```python
self._update_oauth_token(new_creds.access_token)
```

- [ ] **Step 3: Update test that mocks `_update_oauth_client`**

In `tests/providers/test_anthropic_token_refresh.py`, change:
```python
provider._update_oauth_client = MagicMock()
```
to:
```python
provider._update_oauth_token = MagicMock()
```

And the assertion:
```python
provider._update_oauth_client.assert_called_once_with("sk-ant-oat01-new")
```
to:
```python
provider._update_oauth_token.assert_called_once_with("sk-ant-oat01-new")
```

- [ ] **Step 4: Run tests**

Run: `cd /root/git_code/nanobot && source .venv/bin/activate && pytest tests/providers/test_anthropic_token_refresh.py tests/providers/test_anthropic_oauth.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add nanobot/providers/anthropic_provider.py tests/providers/test_anthropic_token_refresh.py
git commit -m "fix(oauth): update auth_token in-place instead of recreating client"
```

---

### Task 3: Fix double margin subtraction in token expiry

**Files:**
- Modify: `nanobot/providers/oauth_store.py:130-134` (refresh_anthropic_token return)
- Modify: `nanobot/providers/anthropic_provider.py:148` (_ensure_valid_token margin check)

The issue: `refresh_anthropic_token` subtracts `_REFRESH_MARGIN_MS` (5 min) from `expires_at_ms`, then `_ensure_valid_token` subtracts another `margin_ms` (5 min). Total = 10 min early refresh.

Fix: Remove the margin from `oauth_store.py` — let `_ensure_valid_token` be the single place that applies margin.

- [ ] **Step 1: Remove margin subtraction from `refresh_anthropic_token`**

In `oauth_store.py`, change the return in `refresh_anthropic_token`:

```python
    now_ms = int(time.time() * 1000)
    return OAuthCredentials(
        access_token=data["access_token"],
        refresh_token=data["refresh_token"],
        expires_at_ms=now_ms + int(data["expires_in"]) * 1000,
    )
```

Remove the `_REFRESH_MARGIN_MS` constant (it's no longer used).

- [ ] **Step 2: Run tests**

Run: `cd /root/git_code/nanobot && source .venv/bin/activate && pytest tests/providers/ -v`
Expected: All PASS

- [ ] **Step 3: Commit**

```bash
git add nanobot/providers/oauth_store.py
git commit -m "fix(oauth): remove double margin subtraction from token expiry"
```

---

### Task 4: Session clear() preserves runtime metadata

**Files:**
- Modify: `nanobot/session/manager.py:95-100`

- [ ] **Step 1: Preserve runtime in clear()**

```python
def clear(self) -> None:
    """Clear all messages and reset session to initial state."""
    self.messages = []
    runtime = self.metadata.get("runtime")
    self.metadata = {}
    if runtime:
        self.metadata["runtime"] = runtime
    self.last_consolidated = 0
    self.updated_at = datetime.now()
```

- [ ] **Step 2: Verify manually (no existing test for this)**

This is a 3-line change with clear semantics. No test needed beyond existing suite.

Run: `cd /root/git_code/nanobot && source .venv/bin/activate && pytest tests/ -v --timeout=10 2>&1 | tail -20`
Expected: No regressions

- [ ] **Step 3: Commit**

```bash
git add nanobot/session/manager.py
git commit -m "fix(session): preserve runtime metadata on /new clear"
```

---

## Chunk 2: Readability & Architecture

### Task 5: Clean up runner.py timing variables

**Files:**
- Modify: `nanobot/agent/runner.py:68-73`

- [ ] **Step 1: Move `import time` to top-level, rename variables**

At top of `runner.py`, add:
```python
import time
```

In `run()` method, change:
```python
    async def run(self, spec: AgentRunSpec) -> AgentRunResult:
        import time as _time
        _t0 = _time.monotonic()
        _llm_ms = 0
```
to:
```python
    async def run(self, spec: AgentRunSpec) -> AgentRunResult:
        t0 = time.monotonic()
        llm_total_ms = 0
```

And every reference:
- `_time.monotonic()` → `time.monotonic()`
- `_llm_ms` → `llm_total_ms`
- `_t0` → `t0`
- `_llm_t0` → `llm_t0`
- `_elapsed_ms` → `elapsed_ms`

- [ ] **Step 2: Run tests**

Run: `cd /root/git_code/nanobot && source .venv/bin/activate && pytest tests/ -v --timeout=10 2>&1 | tail -20`
Expected: All PASS

- [ ] **Step 3: Commit**

```bash
git add nanobot/agent/runner.py
git commit -m "refactor(runner): clean up timing variable names and imports"
```

---

### Task 6: Replace 6-tuple return with AgentRunResult passthrough

**Files:**
- Modify: `nanobot/agent/loop.py:228` (_run_agent_loop return type)
- Modify: `nanobot/agent/loop.py:292` (return statement)
- Modify: `nanobot/agent/loop.py:444` (system message caller)
- Modify: `nanobot/agent/loop.py:506` (normal message caller)
- Modify: `nanobot/agent/loop.py:586` (_save_turn signature)

This is the biggest change. `_run_agent_loop` currently returns a 6-tuple; it should return `AgentRunResult` directly.

- [ ] **Step 1: Change `_run_agent_loop` return type and return statement**

Change signature:
```python
    async def _run_agent_loop(
        self,
        initial_messages: list[dict],
        on_progress: Callable[..., Awaitable[None]] | None = None,
        on_stream: Callable[[str], Awaitable[None]] | None = None,
        on_stream_end: Callable[..., Awaitable[None]] | None = None,
        *,
        channel: str = "cli",
        chat_id: str = "direct",
        message_id: str | None = None,
    ) -> AgentRunResult:
```

Change the return at end of method (around line 292):
```python
        return result
```

Remove the intermediate unpacking — just return the `AgentRunResult` from `self.runner.run()` after doing the logging.

- [ ] **Step 2: Update system message caller (around line 444)**

Change:
```python
            final_content, _, all_msgs, turn_usage, elapsed, llm_elapsed = await self._run_agent_loop(
                messages, channel=channel, chat_id=chat_id,
                message_id=msg.metadata.get("message_id"),
            )
            self._save_turn(session, all_msgs, 1 + len(history), usage=turn_usage,
                            elapsed_ms=elapsed, llm_elapsed_ms=llm_elapsed,
                            sender_id=msg.sender_id,
                            sender_name=msg.metadata.get("sender_name"))
```
to:
```python
            result = await self._run_agent_loop(
                messages, channel=channel, chat_id=chat_id,
                message_id=msg.metadata.get("message_id"),
            )
            self._save_turn(session, result, 1 + len(history),
                            sender_id=msg.sender_id,
                            sender_name=msg.metadata.get("sender_name"))
```

And update the `OutboundMessage` to use `result.final_content`.

- [ ] **Step 3: Update normal message caller (around line 506)**

Same pattern — replace tuple unpacking with `result = await self._run_agent_loop(...)` and update all references:
- `final_content` → `result.final_content`
- `all_msgs` → `result.messages`

- [ ] **Step 4: Update `_save_turn` to accept `AgentRunResult`**

Change signature:
```python
    def _save_turn(self, session: Session, result: AgentRunResult, skip: int,
                   sender_id: str | None = None,
                   sender_name: str | None = None) -> None:
```

Inside the method, replace:
- `messages` → `result.messages`
- `usage` → `result.usage`
- `elapsed_ms` → `result.elapsed_ms`
- `llm_elapsed_ms` → `result.llm_elapsed_ms`

Remove the `usage`, `elapsed_ms`, `llm_elapsed_ms` parameters.

- [ ] **Step 5: Add import for AgentRunResult at top of loop.py**

```python
from nanobot.agent.runner import AgentRunResult, AgentRunSpec
```

- [ ] **Step 6: Run full test suite**

Run: `cd /root/git_code/nanobot && source .venv/bin/activate && pytest tests/ -v --timeout=10 2>&1 | tail -30`
Expected: All PASS

- [ ] **Step 7: Commit**

```bash
git add nanobot/agent/loop.py
git commit -m "refactor(loop): return AgentRunResult instead of 6-tuple from _run_agent_loop"
```

---

### Task 7: Cache TTS provider instance in TTSService

**Files:**
- Modify: `nanobot/tts/service.py`

- [ ] **Step 1: Create provider once in `__init__`, reuse in `synthesize`**

```python
class TTSService:
    """TTS service: decides whether to trigger, calls provider, manages temp files."""

    def __init__(self, config: TTSConfig):
        self.config = config
        self._provider = create_provider(config)
        self._temp_dir = Path(tempfile.gettempdir()) / "nanobot_tts"
        self._temp_dir.mkdir(exist_ok=True)

    def should_trigger(self, session_tts: bool = False, skill_meta: dict[str, Any] | None = None) -> bool:
        """Check if TTS should be triggered for this response."""
        if not self.config.enabled:
            return False
        if session_tts:
            return True
        if skill_meta and skill_meta.get("tts"):
            return True
        return False

    async def synthesize(self, text: str, voice: str | None = None) -> Path | None:
        """Generate audio. Returns file path on success, None on failure (never blocks text)."""
        if not text or not text.strip():
            return None

        if len(text) > self.config.max_text_length:
            text = text[:self.config.max_text_length]

        output_path = self._temp_dir / f"tts_{uuid.uuid4().hex[:8]}.mp3"

        try:
            provider = self._provider
            # Voice override requires a different provider instance
            if voice and voice != self.config.voice:
                provider = create_provider(self.config, voice_override=voice)

            result = await provider.synthesize(text, output_path)
            logger.info("TTS generated: {} ({} bytes)", result.name, result.stat().st_size)
            return result
        except TTSError as e:
            logger.error("TTS synthesis failed: {}", e)
            return None
        except Exception as e:
            logger.error("Unexpected TTS error: {}", e)
            return None
```

- [ ] **Step 2: Run tests (if any TTS tests exist)**

Run: `cd /root/git_code/nanobot && source .venv/bin/activate && pytest tests/ -v --timeout=10 2>&1 | tail -20`
Expected: No regressions

- [ ] **Step 3: Commit**

```bash
git add nanobot/tts/service.py
git commit -m "perf(tts): cache provider instance, only recreate on voice override"
```

---

## Summary

| Task | Issue | Severity | Files |
|------|-------|----------|-------|
| 1 | OAuth file permission 0o600 | Critical | oauth_store.py |
| 2 | Update auth_token in-place | Critical | anthropic_provider.py, test |
| 3 | Double margin subtraction | Minor | oauth_store.py |
| 4 | Session clear() preserves runtime | Important | session/manager.py |
| 5 | Runner timing readability | Minor | runner.py |
| 6 | 6-tuple → AgentRunResult | Architecture | loop.py |
| 7 | Cache TTS provider | Important | tts/service.py |
