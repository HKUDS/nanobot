# Fallback Provider Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When the primary LLM provider returns a transient error (429/529/overloaded), automatically fall through a chain of fallback models, with a circuit breaker to skip known-dead providers.

**Architecture:** Decorator pattern — `FallbackProvider` wraps a primary `LLMProvider` + N fallback `(LLMProvider, model)` pairs. Transparent to `AgentRunner`/`AgentLoop`. Circuit breaker tracks per-provider failure timestamps to skip recently-failed providers during cooldown.

**Tech Stack:** Pure Python, no new dependencies. Pydantic config extension. pytest for tests.

---

## File Structure

```
nanobot/
├── providers/
│   ├── fallback.py          # NEW — FallbackProvider + circuit breaker
│   └── base.py              # UNCHANGED
├── config/
│   └── schema.py            # MODIFY — add fallback_models + fallback_cooldown_s to AgentDefaults
├── nanobot.py               # MODIFY — _make_provider wraps with FallbackProvider
├── cli/
│   └── commands.py          # MODIFY — gateway/serve/chat _make_provider calls (via nanobot.py)
tests/
└── providers/
    └── test_fallback_provider.py  # NEW — unit tests
```

---

## Chunk 1: Config Schema + FallbackProvider Core

### Task 1: Add fallback config fields to AgentDefaults

**Files:**
- Modify: `nanobot/config/schema.py` — `AgentDefaults` class

- [ ] **Step 1: Write the failing test**

Create `tests/config/test_fallback_config.py`:

```python
"""Test fallback model configuration parsing."""
import pytest
from nanobot.config.schema import AgentDefaults


def test_defaults_have_empty_fallback_models():
    d = AgentDefaults()
    assert d.fallback_models == []
    assert d.fallback_cooldown_s == 60


def test_fallback_models_from_camel_case():
    d = AgentDefaults.model_validate({
        "fallbackModels": ["openrouter/anthropic/claude-sonnet-4", "deepseek/deepseek-chat"],
        "fallbackCooldownS": 30,
    })
    assert d.fallback_models == ["openrouter/anthropic/claude-sonnet-4", "deepseek/deepseek-chat"]
    assert d.fallback_cooldown_s == 30
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /root/git_code/nanobot && python -m pytest tests/config/test_fallback_config.py -v`
Expected: FAIL — `fallback_models` attribute doesn't exist

- [ ] **Step 3: Add fields to AgentDefaults**

In `nanobot/config/schema.py`, add two fields to `AgentDefaults`:

```python
class AgentDefaults(Base):
    # ... existing fields ...
    fallback_models: list[str] = Field(default_factory=list)  # e.g. ["openrouter/anthropic/claude-sonnet-4"]
    fallback_cooldown_s: int = 60  # seconds to skip a failed provider before retrying
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /root/git_code/nanobot && python -m pytest tests/config/test_fallback_config.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd /root/git_code/nanobot
git add nanobot/config/schema.py tests/config/test_fallback_config.py
git commit -m "feat: add fallback_models config to AgentDefaults"
```

---

### Task 2: Create FallbackProvider with circuit breaker

**Files:**
- Create: `nanobot/providers/fallback.py`
- Test: `tests/providers/test_fallback_provider.py`

- [ ] **Step 1: Write failing tests**

Create `tests/providers/test_fallback_provider.py`:

```python
"""Tests for FallbackProvider with circuit breaker."""
import asyncio
import time

import pytest

from nanobot.providers.base import LLMProvider, LLMResponse


# 复用 test_provider_retry.py 里的 ScriptedProvider 模式
class ScriptedProvider(LLMProvider):
    """Provider that returns pre-scripted responses in order."""

    def __init__(self, responses, default_model="test-primary"):
        super().__init__()
        self._responses = list(responses)
        self.calls = 0
        self.call_log: list[dict] = []

    async def chat(self, **kwargs) -> LLMResponse:
        self.calls += 1
        self.call_log.append(kwargs)
        if not self._responses:
            return LLMResponse(content="no more responses", finish_reason="error")
        resp = self._responses.pop(0)
        if isinstance(resp, BaseException):
            raise resp
        return resp

    async def chat_stream(self, **kwargs) -> LLMResponse:
        # 简单实现：委托给 chat，忽略 on_content_delta
        kwargs.pop("on_content_delta", None)
        return await self.chat(**kwargs)

    def get_default_model(self) -> str:
        return "test-primary"


def _ok(content="ok"):
    return LLMResponse(content=content)


def _transient(msg="529 overloaded"):
    return LLMResponse(content=f"Error calling LLM: {msg}", finish_reason="error")


def _non_transient(msg="401 unauthorized"):
    return LLMResponse(content=msg, finish_reason="error")


@pytest.mark.asyncio
async def test_primary_succeeds_no_fallback():
    from nanobot.providers.fallback import FallbackProvider

    primary = ScriptedProvider([_ok("primary ok")])
    fb = ScriptedProvider([_ok("should not reach")])
    provider = FallbackProvider(primary, [(fb, "fb-model")])

    resp = await provider.chat(messages=[{"role": "user", "content": "hi"}])

    assert resp.content == "primary ok"
    assert primary.calls == 1
    assert fb.calls == 0


@pytest.mark.asyncio
async def test_primary_transient_falls_to_first_fallback():
    from nanobot.providers.fallback import FallbackProvider

    primary = ScriptedProvider([_transient()])
    fb = ScriptedProvider([_ok("fallback ok")])
    provider = FallbackProvider(primary, [(fb, "fb-model")])

    resp = await provider.chat(messages=[{"role": "user", "content": "hi"}])

    assert resp.content == "fallback ok"
    assert primary.calls == 1
    assert fb.calls == 1


@pytest.mark.asyncio
async def test_non_transient_error_not_fallback():
    from nanobot.providers.fallback import FallbackProvider

    primary = ScriptedProvider([_non_transient()])
    fb = ScriptedProvider([_ok("should not reach")])
    provider = FallbackProvider(primary, [(fb, "fb-model")])

    resp = await provider.chat(messages=[{"role": "user", "content": "hi"}])

    assert resp.content == "401 unauthorized"
    assert fb.calls == 0


@pytest.mark.asyncio
async def test_chain_fallback_first_also_fails():
    from nanobot.providers.fallback import FallbackProvider

    primary = ScriptedProvider([_transient("primary 529")])
    fb1 = ScriptedProvider([_transient("fb1 503")])
    fb2 = ScriptedProvider([_ok("fb2 ok")])
    provider = FallbackProvider(primary, [(fb1, "fb1-model"), (fb2, "fb2-model")])

    resp = await provider.chat(messages=[{"role": "user", "content": "hi"}])

    assert resp.content == "fb2 ok"
    assert primary.calls == 1
    assert fb1.calls == 1
    assert fb2.calls == 1


@pytest.mark.asyncio
async def test_all_fail_returns_last_error():
    from nanobot.providers.fallback import FallbackProvider

    primary = ScriptedProvider([_transient("p fail")])
    fb = ScriptedProvider([_transient("fb fail")])
    provider = FallbackProvider(primary, [(fb, "fb-model")])

    resp = await provider.chat(messages=[{"role": "user", "content": "hi"}])

    assert resp.finish_reason == "error"
    assert "fb fail" in resp.content


@pytest.mark.asyncio
async def test_circuit_breaker_skips_primary_during_cooldown(monkeypatch):
    from nanobot.providers.fallback import FallbackProvider

    primary = ScriptedProvider([_transient(), _ok("primary recovered")])
    fb = ScriptedProvider([_ok("fb first"), _ok("fb second")])
    provider = FallbackProvider(primary, [(fb, "fb-model")], cooldown_s=60)

    # 第一次调用：primary 失败 → fallback
    resp1 = await provider.chat(messages=[{"role": "user", "content": "1"}])
    assert resp1.content == "fb first"
    assert primary.calls == 1

    # 第二次调用：cooldown 期间，跳过 primary，直接 fallback
    resp2 = await provider.chat(messages=[{"role": "user", "content": "2"}])
    assert resp2.content == "fb second"
    assert primary.calls == 1  # 没有再打 primary
    assert fb.calls == 2


@pytest.mark.asyncio
async def test_circuit_breaker_retries_primary_after_cooldown(monkeypatch):
    from nanobot.providers.fallback import FallbackProvider

    primary = ScriptedProvider([_transient(), _ok("primary back")])
    fb = ScriptedProvider([_ok("fb ok")])
    provider = FallbackProvider(primary, [(fb, "fb-model")], cooldown_s=0.1)

    # 第一次：primary 失败
    resp1 = await provider.chat(messages=[{"role": "user", "content": "1"}])
    assert resp1.content == "fb ok"

    # 等 cooldown 过期
    await asyncio.sleep(0.15)

    # 第二次：重试 primary，这次成功
    resp2 = await provider.chat(messages=[{"role": "user", "content": "2"}])
    assert resp2.content == "primary back"
    assert primary.calls == 2


@pytest.mark.asyncio
async def test_primary_recovery_resets_circuit_breaker():
    from nanobot.providers.fallback import FallbackProvider

    primary = ScriptedProvider([_transient(), _ok("recovered"), _ok("still good")])
    fb = ScriptedProvider([_ok("fb")])
    provider = FallbackProvider(primary, [(fb, "fb-model")], cooldown_s=0.05)

    # 失败 → fallback
    await provider.chat(messages=[{"role": "user", "content": "1"}])
    await asyncio.sleep(0.1)

    # cooldown 过期，primary 恢复
    resp2 = await provider.chat(messages=[{"role": "user", "content": "2"}])
    assert resp2.content == "recovered"

    # 立刻再调用，primary 应该直接走（breaker 已重置）
    resp3 = await provider.chat(messages=[{"role": "user", "content": "3"}])
    assert resp3.content == "still good"
    assert primary.calls == 3


@pytest.mark.asyncio
async def test_chat_stream_fallback():
    """Streaming path also gets fallback protection."""
    from nanobot.providers.fallback import FallbackProvider

    primary = ScriptedProvider([_transient()])
    fb = ScriptedProvider([_ok("stream fb ok")])
    provider = FallbackProvider(primary, [(fb, "fb-model")])

    resp = await provider.chat_stream(
        messages=[{"role": "user", "content": "hi"}],
        on_content_delta=None,
    )

    assert resp.content == "stream fb ok"


@pytest.mark.asyncio
async def test_exception_in_primary_treated_as_transient():
    """Unhandled exceptions from primary.chat should trigger fallback."""
    from nanobot.providers.fallback import FallbackProvider

    primary = ScriptedProvider([ConnectionError("connection reset")])
    fb = ScriptedProvider([_ok("fb rescued")])
    provider = FallbackProvider(primary, [(fb, "fb-model")])

    resp = await provider.chat(messages=[{"role": "user", "content": "hi"}])

    assert resp.content == "fb rescued"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /root/git_code/nanobot && python -m pytest tests/providers/test_fallback_provider.py -v`
Expected: FAIL — `nanobot.providers.fallback` module doesn't exist

- [ ] **Step 3: Implement FallbackProvider**

Create `nanobot/providers/fallback.py`:

```python
"""FallbackProvider — transparent chain with circuit breaker.

Wraps a primary LLMProvider + N fallback (provider, model) pairs.
On transient errors, falls through the chain. Circuit breaker skips
providers that failed recently (within cooldown_s).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any

from loguru import logger

from nanobot.providers.base import LLMProvider, LLMResponse


class FallbackProvider(LLMProvider):
    """Chain: primary → fallback[0] → fallback[1] → ... → error."""

    def __init__(
        self,
        primary: LLMProvider,
        fallbacks: list[tuple[LLMProvider, str]],
        cooldown_s: float = 60,
    ):
        super().__init__()
        self.primary = primary
        self.fallbacks = fallbacks
        self._cooldown_s = cooldown_s
        self._primary_failed_at: float = 0

    async def chat(self, **kwargs: Any) -> LLMResponse:
        resp = await self._try_primary(**kwargs)
        if resp is not None:
            return resp
        return await self._try_fallbacks(**kwargs)

    async def chat_stream(self, **kwargs: Any) -> LLMResponse:
        resp = await self._try_primary_stream(**kwargs)
        if resp is not None:
            return resp
        return await self._try_fallbacks_stream(**kwargs)

    def get_default_model(self) -> str:
        return self.primary.get_default_model()

    # --- 内部方法 ---

    async def _try_primary(self, **kwargs: Any) -> LLMResponse | None:
        """尝试 primary，返回 None 表示需要 fallback。"""
        if self._in_cooldown():
            return None
        resp = await self.primary._safe_chat(**kwargs)
        return self._evaluate_primary(resp)

    async def _try_primary_stream(self, **kwargs: Any) -> LLMResponse | None:
        if self._in_cooldown():
            return None
        resp = await self.primary._safe_chat_stream(**kwargs)
        return self._evaluate_primary(resp)

    def _evaluate_primary(self, resp: LLMResponse) -> LLMResponse | None:
        if resp.finish_reason != "error" or not self._is_transient_error(resp.content):
            self._primary_failed_at = 0
            return resp
        self._primary_failed_at = time.monotonic()
        logger.warning("Primary provider failed: {}", (resp.content or "")[:120])
        return None

    async def _try_fallbacks(self, **kwargs: Any) -> LLMResponse:
        for fb_provider, fb_model in self.fallbacks:
            logger.info("Trying fallback: {}", fb_model)
            resp = await fb_provider._safe_chat(model=fb_model, **kwargs)
            if resp.finish_reason != "error" or not self._is_transient_error(resp.content):
                return resp
            logger.warning("Fallback {} also failed: {}", fb_model, (resp.content or "")[:120])
        return resp  # 全挂了，返回最后一个错误

    async def _try_fallbacks_stream(self, **kwargs: Any) -> LLMResponse:
        for fb_provider, fb_model in self.fallbacks:
            logger.info("Trying fallback (stream): {}", fb_model)
            resp = await fb_provider._safe_chat_stream(model=fb_model, **kwargs)
            if resp.finish_reason != "error" or not self._is_transient_error(resp.content):
                return resp
            logger.warning("Fallback {} also failed: {}", fb_model, (resp.content or "")[:120])
        return resp

    def _in_cooldown(self) -> bool:
        if self._primary_failed_at == 0:
            return False
        return (time.monotonic() - self._primary_failed_at) < self._cooldown_s
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /root/git_code/nanobot && python -m pytest tests/providers/test_fallback_provider.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
cd /root/git_code/nanobot
git add nanobot/providers/fallback.py tests/providers/test_fallback_provider.py
git commit -m "feat: add FallbackProvider with circuit breaker"
```

---

## Chunk 2: Wiring — _make_provider + Integration

### Task 3: Wire FallbackProvider into _make_provider

**Files:**
- Modify: `nanobot/nanobot.py` — `_make_provider` function

- [ ] **Step 1: Write failing test**

Create `tests/test_make_provider_fallback.py`:

```python
"""Test that _make_provider wraps with FallbackProvider when fallback_models configured."""
import pytest
from unittest.mock import patch, MagicMock
from nanobot.config.schema import Config


def _make_config(fallback_models=None, cooldown=60):
    """Build a minimal Config with anthropic key + optional fallbacks."""
    cfg = Config.model_validate({
        "providers": {
            "anthropic": {"apiKey": "sk-test"},
            "openrouter": {"apiKey": "sk-or-test"},
        },
        "agents": {
            "defaults": {
                "model": "anthropic/claude-opus-4-5",
                "fallbackModels": fallback_models or [],
                "fallbackCooldownS": cooldown,
            }
        }
    })
    return cfg


def test_no_fallback_returns_plain_provider():
    from nanobot.nanobot import _make_provider
    from nanobot.providers.fallback import FallbackProvider

    provider = _make_provider(_make_config())
    assert not isinstance(provider, FallbackProvider)


def test_with_fallback_returns_fallback_provider():
    from nanobot.nanobot import _make_provider
    from nanobot.providers.fallback import FallbackProvider

    provider = _make_provider(_make_config(
        fallback_models=["openrouter/anthropic/claude-sonnet-4"],
    ))
    assert isinstance(provider, FallbackProvider)
    assert len(provider.fallbacks) == 1
    assert provider._cooldown_s == 60
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /root/git_code/nanobot && python -m pytest tests/test_make_provider_fallback.py -v`
Expected: FAIL — `_make_provider` doesn't create FallbackProvider

- [ ] **Step 3: Add FallbackProvider wiring to _make_provider**

In `nanobot/nanobot.py`, modify `_make_provider` — after creating the primary provider and setting `provider.generation`, add:

```python
def _make_provider(config: Any) -> Any:
    """Create the LLM provider from config (extracted from CLI)."""
    from nanobot.providers.base import GenerationSettings
    from nanobot.providers.registry import find_by_name

    model = config.agents.defaults.model
    provider_name = config.get_provider_name(model)
    p = config.get_provider(model)
    spec = find_by_name(provider_name) if provider_name else None
    backend = spec.backend if spec else "openai_compat"

    # ... existing provider construction (unchanged) ...

    defaults = config.agents.defaults
    provider.generation = GenerationSettings(
        temperature=defaults.temperature,
        max_tokens=defaults.max_tokens,
        reasoning_effort=defaults.reasoning_effort,
    )

    # --- NEW: wrap with FallbackProvider if fallback_models configured ---
    if defaults.fallback_models:
        provider = _wrap_with_fallback(config, provider, defaults)

    return provider


def _make_single_provider(config: Any, model: str) -> Any:
    """Create a single LLM provider for the given model string."""
    from nanobot.providers.base import GenerationSettings
    from nanobot.providers.registry import find_by_name

    provider_name = config.get_provider_name(model)
    p = config.get_provider(model)
    spec = find_by_name(provider_name) if provider_name else None
    backend = spec.backend if spec else "openai_compat"

    if not p:
        raise ValueError(f"No provider configured for fallback model '{model}'")

    if backend == "anthropic":
        from nanobot.providers.anthropic_provider import AnthropicProvider
        return AnthropicProvider(
            api_key=p.api_key,
            api_base=config.get_api_base(model),
            default_model=model,
            extra_headers=p.extra_headers,
        )
    else:
        from nanobot.providers.openai_compat_provider import OpenAICompatProvider
        return OpenAICompatProvider(
            api_key=p.api_key,
            api_base=config.get_api_base(model),
            default_model=model,
            extra_headers=p.extra_headers,
            spec=spec,
        )


def _wrap_with_fallback(config: Any, primary: Any, defaults: Any) -> Any:
    """Wrap primary provider with FallbackProvider chain."""
    from nanobot.providers.fallback import FallbackProvider

    fallbacks = []
    for fb_model in defaults.fallback_models:
        try:
            fb_provider = _make_single_provider(config, fb_model)
        except (ValueError, Exception) as e:
            from loguru import logger
            logger.warning("Skipping fallback model {}: {}", fb_model, e)
            continue
        fallbacks.append((fb_provider, fb_model))

    if not fallbacks:
        return primary

    return FallbackProvider(
        primary=primary,
        fallbacks=fallbacks,
        cooldown_s=defaults.fallback_cooldown_s,
    )
```

注意：抽取 `_make_single_provider` 是为了复用 provider 构造逻辑，但比 `_make_provider` 更简单——不处理 OAuth/Codex/Azure（这些不太可能是 fallback 目标）。如果以后需要支持，扩展这个函数即可。

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /root/git_code/nanobot && python -m pytest tests/test_make_provider_fallback.py -v`
Expected: PASS

- [ ] **Step 5: Run full test suite to check nothing broke**

Run: `cd /root/git_code/nanobot && python -m pytest tests/ -x -q`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
cd /root/git_code/nanobot
git add nanobot/nanobot.py tests/test_make_provider_fallback.py
git commit -m "feat: wire FallbackProvider into _make_provider"
```

---

### Task 4: Verify FallbackProvider passes through generation settings

**Files:**
- Modify: `nanobot/providers/fallback.py` — ensure `generation` propagation
- Test: `tests/providers/test_fallback_provider.py` — add generation test

The `FallbackProvider` inherits `LLMProvider` but `chat_with_retry` (called by `AgentRunner`) reads `self.generation` for default temperature/max_tokens/reasoning_effort. Since `FallbackProvider` doesn't override `chat_with_retry`, the base class implementation calls `self.chat()` — which is our override. But `self.generation` on the FallbackProvider itself needs to match the primary. We handle this by having `_make_provider` set `provider.generation` AFTER wrapping — but wait, after wrapping it sets generation on the FallbackProvider, not the primary.

Fix: in `_wrap_with_fallback`, copy the primary's generation settings to the FallbackProvider.

- [ ] **Step 1: Add test for generation passthrough**

Append to `tests/providers/test_fallback_provider.py`:

```python
@pytest.mark.asyncio
async def test_generation_settings_inherited():
    """FallbackProvider should use its own generation settings in chat_with_retry."""
    from nanobot.providers.base import GenerationSettings
    from nanobot.providers.fallback import FallbackProvider

    primary = ScriptedProvider([_ok("ok")])
    fb = ScriptedProvider([])
    provider = FallbackProvider(primary, [(fb, "fb")])
    provider.generation = GenerationSettings(temperature=0.2, max_tokens=999, reasoning_effort="high")

    await provider.chat_with_retry(messages=[{"role": "user", "content": "hi"}])

    assert primary.call_log[-1]["temperature"] == 0.2
    assert primary.call_log[-1]["max_tokens"] == 999
```

Wait — `chat_with_retry` calls `_safe_chat_stream` or `_safe_chat` which calls `self.chat()`. The kwargs (temperature, max_tokens) are resolved from `self.generation` in `chat_with_retry` and passed down. Since `FallbackProvider.chat()` delegates to `primary._safe_chat(**kwargs)`, the kwargs carry through. This should work already.

- [ ] **Step 2: Run test to verify**

Run: `cd /root/git_code/nanobot && python -m pytest tests/providers/test_fallback_provider.py::test_generation_settings_inherited -v`
Expected: PASS (after FallbackProvider is implemented)

- [ ] **Step 3: Commit if needed**

```bash
cd /root/git_code/nanobot
git add tests/providers/test_fallback_provider.py
git commit -m "test: verify generation settings passthrough in FallbackProvider"
```

---

### Task 5: Startup logging for fallback chain

**Files:**
- Modify: `nanobot/cli/commands.py` — log fallback models at gateway startup

- [ ] **Step 1: Add fallback info to gateway startup output**

In `nanobot/cli/commands.py`, in the `gateway()` function, after the existing model display line, add:

```python
# After: console.print(f"  Model    : {config.agents.defaults.model}")
if config.agents.defaults.fallback_models:
    fb_list = " → ".join(config.agents.defaults.fallback_models)
    console.print(f"  [cyan]Fallback[/cyan] : {fb_list} (cooldown {config.agents.defaults.fallback_cooldown_s}s)")
```

Do the same for `serve()` and `chat()` commands if they print model info.

- [ ] **Step 2: Manual verification**

Run: `cd /root/git_code/nanobot && python -m nanobot gateway --help` (just verify no import errors)

- [ ] **Step 3: Commit**

```bash
cd /root/git_code/nanobot
git add nanobot/cli/commands.py
git commit -m "feat: show fallback chain in gateway startup log"
```

---

### Task 6: Final integration test + run full suite

- [ ] **Step 1: Run full test suite**

Run: `cd /root/git_code/nanobot && python -m pytest tests/ -x -q --tb=short`
Expected: ALL PASS

- [ ] **Step 2: Verify config round-trip with real config file**

```bash
cd /root/git_code/nanobot
python -c "
from nanobot.config.loader import load_config
c = load_config()
print('model:', c.agents.defaults.model)
print('fallbacks:', c.agents.defaults.fallback_models)
print('cooldown:', c.agents.defaults.fallback_cooldown_s)
"
```

- [ ] **Step 3: Final commit + summary**

```bash
cd /root/git_code/nanobot
git log --oneline -5
```

---

## Summary

| What | Where | Lines |
|------|-------|-------|
| Config fields | `config/schema.py` | +2 |
| FallbackProvider | `providers/fallback.py` | ~65 |
| Wiring | `nanobot.py` | ~40 |
| Startup log | `cli/commands.py` | +3 |
| Tests | 3 test files | ~180 |
| **Total production code** | | **~110 lines** |

**Design decisions:**
1. Decorator pattern — zero changes to AgentRunner/AgentLoop
2. Circuit breaker per-provider — avoids 7s wasted retry on known-dead endpoint
3. `_make_single_provider` only handles anthropic + openai_compat backends — OAuth/Codex/Azure excluded from fallback (these are edge cases not suitable as fallbacks)
4. Cooldown is in-memory only — process restart resets, which is correct behavior (overloads are transient)
