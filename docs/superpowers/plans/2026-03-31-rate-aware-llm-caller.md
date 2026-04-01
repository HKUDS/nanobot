# Rate-Aware LLM Caller Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent Anthropic 429 rate limit errors by tracking prompt tokens in a rolling 60-second window and sleeping when approaching 80% of the 50k tokens/minute limit.

**Architecture:** A standalone `RateLimiter` class in `providers/rate_limiter.py` injected into `StreamingLLMCaller` via the composition root. Before each LLM call, the caller checks the window; after each call, it records the token count.

**Tech Stack:** Python stdlib only (asyncio, collections.deque, time, dataclasses). No new dependencies.

---

## File Structure

| File | Role |
|------|------|
| `nanobot/providers/rate_limiter.py` | **New.** Rolling-window token tracker with async sleep. |
| `nanobot/providers/__init__.py` | **Modify.** Add `RateLimiter` to exports. |
| `nanobot/agent/streaming.py` | **Modify.** Accept optional `RateLimiter`, call before/after LLM. |
| `nanobot/agent/agent_factory.py` | **Modify.** Construct `RateLimiter` for Anthropic models. |
| `tests/test_rate_limiter.py` | **New.** Unit tests for `RateLimiter`. |
| `tests/test_streaming.py` | **Modify.** Test `StreamingLLMCaller` with rate limiter. |

---

### Task 1: RateLimiter — tests and implementation

**Files:**
- Create: `nanobot/providers/rate_limiter.py`
- Create: `tests/test_rate_limiter.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_rate_limiter.py`:

```python
"""Tests for the rolling-window rate limiter."""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from nanobot.providers.rate_limiter import RateLimiter


class TestRateLimiter:
    def test_window_total_empty(self):
        rl = RateLimiter(tokens_per_minute=50_000)
        assert rl.window_total() == 0

    def test_record_increases_total(self):
        rl = RateLimiter(tokens_per_minute=50_000)
        rl.record(10_000)
        assert rl.window_total() == 10_000

    def test_multiple_records_sum(self):
        rl = RateLimiter(tokens_per_minute=50_000)
        rl.record(10_000)
        rl.record(15_000)
        assert rl.window_total() == 25_000

    def test_old_entries_pruned(self):
        rl = RateLimiter(tokens_per_minute=50_000)
        # Manually inject an old entry
        import time

        old_time = time.monotonic() - 61.0
        from nanobot.providers.rate_limiter import TokenRecord

        rl._window.append(TokenRecord(timestamp=old_time, tokens=30_000))
        rl.record(5_000)
        # Old entry should be pruned
        assert rl.window_total() == 5_000

    @pytest.mark.asyncio
    async def test_wait_if_needed_under_threshold_no_sleep(self):
        rl = RateLimiter(tokens_per_minute=50_000, threshold=0.80)
        rl.record(30_000)  # 60% — under 80% threshold
        with patch("asyncio.sleep", new_callable=lambda: _async_mock) as mock_sleep:
            waited = await rl.wait_if_needed()
        assert waited == 0.0
        mock_sleep.assert_not_called()

    @pytest.mark.asyncio
    async def test_wait_if_needed_over_threshold_sleeps(self):
        rl = RateLimiter(tokens_per_minute=50_000, threshold=0.80)
        rl.record(45_000)  # 90% — over 80% threshold
        with patch("asyncio.sleep", new_callable=lambda: _async_mock) as mock_sleep:
            waited = await rl.wait_if_needed()
        assert waited > 0.0
        mock_sleep.assert_called_once()
        # Sleep duration should be clamped between 1 and 15 seconds
        sleep_arg = mock_sleep.call_args[0][0]
        assert 1.0 <= sleep_arg <= 15.0

    @pytest.mark.asyncio
    async def test_wait_if_needed_empty_window_no_sleep(self):
        rl = RateLimiter(tokens_per_minute=50_000)
        with patch("asyncio.sleep", new_callable=lambda: _async_mock) as mock_sleep:
            waited = await rl.wait_if_needed()
        assert waited == 0.0
        mock_sleep.assert_not_called()

    def test_threshold_boundary_exact(self):
        rl = RateLimiter(tokens_per_minute=100, threshold=0.80)
        rl.record(79)  # just under 80%
        assert rl.window_total() == 79
        # Should not trigger (tested via wait_if_needed in async tests)

    def test_default_threshold(self):
        rl = RateLimiter(tokens_per_minute=50_000)
        assert rl._threshold == 0.80


def _async_mock():
    """Create a mock that returns a coroutine."""
    from unittest.mock import AsyncMock

    return AsyncMock()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_rate_limiter.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'nanobot.providers.rate_limiter'`

- [ ] **Step 3: Write the implementation**

Create `nanobot/providers/rate_limiter.py`:

```python
"""Rolling-window rate limiter for LLM API calls.

Tracks prompt tokens sent within a 60-second window and introduces
async delays when approaching the provider's rate limit.  Currently
used for Anthropic's 50k input tokens/minute limit.

Designed for deletion: if the rate limit is increased or becomes
irrelevant, remove this file and the optional ``rate_limiter``
parameter from ``StreamingLLMCaller``.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass

from loguru import logger


@dataclass(slots=True)
class TokenRecord:
    """A single token-usage entry in the rolling window."""

    timestamp: float
    tokens: int


_WINDOW_SECONDS: float = 60.0


class RateLimiter:
    """Rolling-window token rate limiter.

    Tracks prompt tokens sent within the last 60 seconds.  When the
    total approaches ``threshold`` fraction of ``tokens_per_minute``,
    ``wait_if_needed()`` sleeps until enough old entries expire.

    Args:
        tokens_per_minute: The provider's rate limit.
        threshold: Fraction (0-1) at which to start sleeping.
    """

    def __init__(self, tokens_per_minute: int, threshold: float = 0.80) -> None:
        self._limit = tokens_per_minute
        self._threshold = threshold
        self._window: deque[TokenRecord] = deque()

    def _prune(self, now: float) -> None:
        """Remove entries older than 60 seconds."""
        cutoff = now - _WINDOW_SECONDS
        while self._window and self._window[0].timestamp < cutoff:
            self._window.popleft()

    def window_total(self) -> int:
        """Current token count in the rolling window."""
        self._prune(time.monotonic())
        return sum(r.tokens for r in self._window)

    async def wait_if_needed(self) -> float:
        """Sleep if approaching rate limit.  Returns seconds waited."""
        now = time.monotonic()
        self._prune(now)
        total = sum(r.tokens for r in self._window)
        if total < self._limit * self._threshold:
            return 0.0

        # Wait until the oldest entry expires from the window
        sleep_time = self._window[0].timestamp + _WINDOW_SECONDS - now + 0.5
        sleep_time = max(1.0, min(sleep_time, 15.0))
        logger.info(
            "Rate limiter: {}k/{}k tokens in window, sleeping {:.1f}s",
            total // 1000,
            self._limit // 1000,
            sleep_time,
        )
        await asyncio.sleep(sleep_time)
        return sleep_time

    def record(self, tokens: int) -> None:
        """Record tokens sent in the current call."""
        if tokens > 0:
            self._window.append(TokenRecord(time.monotonic(), tokens))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_rate_limiter.py -v`
Expected: All 9 tests PASS

- [ ] **Step 5: Run lint and typecheck**

Run: `make lint && make typecheck`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add nanobot/providers/rate_limiter.py tests/test_rate_limiter.py
git commit -m "feat(providers): add rolling-window rate limiter for Anthropic token limits"
```

---

### Task 2: Export RateLimiter from providers package

**Files:**
- Modify: `nanobot/providers/__init__.py`

- [ ] **Step 1: Add export**

In `nanobot/providers/__init__.py`, add the import and update `__all__`:

```python
from nanobot.providers.rate_limiter import RateLimiter

# Add "RateLimiter" to the __all__ list
```

The full file should read:

```python
"""LLM provider abstraction module."""

from __future__ import annotations

from nanobot.providers.base import LLMProvider, LLMResponse, StreamChunk
from nanobot.providers.litellm_provider import LiteLLMProvider
from nanobot.providers.rate_limiter import RateLimiter

__all__ = ["LLMProvider", "LLMResponse", "StreamChunk", "LiteLLMProvider", "RateLimiter"]

try:
    from nanobot.providers.openai_codex_provider import OpenAICodexProvider  # noqa: F401

    __all__.append("OpenAICodexProvider")
except ImportError:
    # Optional OAuth dependency may not be installed.
    pass
```

- [ ] **Step 2: Run lint and typecheck**

Run: `make lint && make typecheck`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add nanobot/providers/__init__.py
git commit -m "chore(providers): export RateLimiter from providers package"
```

---

### Task 3: Integrate RateLimiter into StreamingLLMCaller

**Files:**
- Modify: `nanobot/agent/streaming.py` (lines 56-70 constructor, lines 72-115 call method)
- Modify: `tests/test_streaming.py`

- [ ] **Step 1: Write the failing integration test**

Add to `tests/test_streaming.py`:

```python
from nanobot.providers.rate_limiter import RateLimiter


class TestStreamingWithRateLimiter:
    @pytest.mark.asyncio
    async def test_rate_limiter_called_before_and_after(self):
        """Rate limiter is consulted before the call and records tokens after."""
        provider = FakeStreamProvider()
        rl = RateLimiter(tokens_per_minute=50_000)
        caller = StreamingLLMCaller(
            provider=provider, model="test", temperature=0.1,
            max_tokens=100, rate_limiter=rl,
        )
        messages = [{"role": "user", "content": "hello"}]
        await caller.call(messages, tools=None, on_progress=None)
        # Provider was called (no rate limit hit since window is empty)
        assert provider._chat_calls == 1

    @pytest.mark.asyncio
    async def test_rate_limiter_none_works(self):
        """StreamingLLMCaller works fine without a rate limiter."""
        provider = FakeStreamProvider()
        caller = StreamingLLMCaller(
            provider=provider, model="test", temperature=0.1,
            max_tokens=100,
        )
        messages = [{"role": "user", "content": "hello"}]
        await caller.call(messages, tools=None, on_progress=None)
        assert provider._chat_calls == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_streaming.py::TestStreamingWithRateLimiter -v`
Expected: FAIL with `TypeError: StreamingLLMCaller.__init__() got an unexpected keyword argument 'rate_limiter'`

- [ ] **Step 3: Modify StreamingLLMCaller**

In `nanobot/agent/streaming.py`, make these changes:

Add to the imports at the top (under the TYPE_CHECKING block):

```python
if TYPE_CHECKING:
    from nanobot.providers.base import LLMProvider, LLMResponse
    from nanobot.providers.rate_limiter import RateLimiter
```

Modify `StreamingLLMCaller.__init__`:

```python
class StreamingLLMCaller:
    """Handles LLM calls with optional streaming and progress flushing."""

    def __init__(
        self,
        *,
        provider: LLMProvider,
        model: str,
        temperature: float,
        max_tokens: int,
        rate_limiter: RateLimiter | None = None,
    ) -> None:
        self.provider = provider
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self._rate_limiter = rate_limiter
```

In the `call` method, add rate limiter calls. At the very start of the method body (before `t0 = time.monotonic()`):

```python
        if self._rate_limiter:
            waited = await self._rate_limiter.wait_if_needed()
            if waited > 0:
                bind_trace().info("Rate limiter delayed LLM call by {:.1f}s", waited)
```

After each return path that has a response with usage data, record the tokens. There are two return paths:

**Non-streaming path** (around line 115, before `return resp`):

```python
            if self._rate_limiter:
                self._rate_limiter.record(resp.usage.get("prompt_tokens", 0))
            return resp
```

**Streaming path** (around line 182, before `return LLMResponse(...)`):

```python
        if self._rate_limiter:
            self._rate_limiter.record(usage.get("prompt_tokens", 0))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_streaming.py -v`
Expected: All tests PASS (both new and existing)

- [ ] **Step 5: Run lint and typecheck**

Run: `make lint && make typecheck`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add nanobot/agent/streaming.py tests/test_streaming.py
git commit -m "feat(agent): integrate rate limiter into StreamingLLMCaller"
```

---

### Task 4: Wire RateLimiter in agent_factory.py

**Files:**
- Modify: `nanobot/agent/agent_factory.py` (around line 301, the `StreamingLLMCaller` construction)

- [ ] **Step 1: Add construction logic**

In `nanobot/agent/agent_factory.py`, in the `build_agent()` function, find the section that constructs `StreamingLLMCaller` (around line 301). Add the rate limiter construction just before it:

```python
    # 8.5 Construct RateLimiter for Anthropic models
    from nanobot.providers.rate_limiter import RateLimiter as _RateLimiter

    _rate_limiter: _RateLimiter | None = None
    if "anthropic/" in model or "claude" in model.lower():
        _rate_limiter = _RateLimiter(tokens_per_minute=50_000)

    # 9. Construct StreamingLLMCaller
    llm_caller = StreamingLLMCaller(
        provider=provider,
        model=model,
        temperature=temperature,
        max_tokens=config.max_tokens,
        rate_limiter=_rate_limiter,
    )
```

- [ ] **Step 2: Run lint and typecheck**

Run: `make lint && make typecheck`
Expected: PASS

- [ ] **Step 3: Run full check suite**

Run: `make check`
Expected: PASS (lint + typecheck + import-check + structure-check + prompt-check + phase-todo-check + doc-check)

- [ ] **Step 4: Run unit tests**

Run: `make test`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add nanobot/agent/agent_factory.py
git commit -m "feat(agent): wire rate limiter for Anthropic models in factory"
```

---

### Task 5: Final validation

- [ ] **Step 1: Run make check**

Run: `make check`
Expected: PASS

- [ ] **Step 2: Run make pre-push**

Run: `make pre-push`
Expected: PASS (full CI: check + tests with coverage + integration + merge-readiness)

- [ ] **Step 3: Verify import boundaries**

Run: `make import-check`
Expected: No violations. `providers/rate_limiter.py` imports only stdlib. `agent/streaming.py` imports from `providers/` under TYPE_CHECKING (allowed).

- [ ] **Step 4: Verify structure check**

Run: `make structure-check`
Expected: No new violations. `providers/` has 8 files (under 15 limit).
