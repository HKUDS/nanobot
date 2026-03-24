# Phase 3: Extract Compression from `context.py`

**Date:** 2026-03-23
**Topic:** Separate compression logic from prompt assembly in context.py
**Status:** Approved
**Part of:** Comprehensive agent refactoring (Phase 3 of 5)
**Depends on:** Phase 1 (agent_factory.py) — reduces churn when modifying imports

---

## Goal

Extract all context compression logic from `context.py` (709 lines) into a new `compression.py` module. After this change, `context.py` owns only prompt assembly (`ContextBuilder` class) and `compression.py` owns all token estimation, message truncation, and LLM-based summarization.

## Motivation

`context.py` currently has two distinct concerns separated by a clear boundary at line 389:
- **Lines 63-387**: Compression — `_ChatProvider` Protocol, `estimate_tokens`, `estimate_messages_tokens`, `_collect_tail_tool_call_ids`, `_paired_drop_tools`, `compress_context`, `_summary_cache`, `_hash_messages`, `summarize_and_compress`
- **Lines 389-710**: Prompt assembly — `ContextBuilder` class with system prompt, memory injection, skills, bootstrap files

These concerns have zero runtime coupling — `ContextBuilder` never calls any compression function, and the compression functions never reference `ContextBuilder`. The only shared symbols (`estimate_tokens`, `estimate_messages_tokens`) are pure utility functions that belong with compression.

Extracting compression:
- Reduces `context.py` from 709 to ~320 lines (just `ContextBuilder`)
- Makes compression independently testable and reusable
- Eliminates the `_ChatProvider` Protocol from `context.py` (it exists solely for `summarize_and_compress`)

## Approach

### New file: `nanobot/agent/compression.py`

Contains all compression logic extracted verbatim from `context.py`:

| Symbol | Current lines | Type |
|--------|--------------|------|
| `_ChatProvider` | 63-68 | Protocol (structural typing for LLM provider) |
| `estimate_tokens(text)` | 76-81 | Heuristic token count (`len(text) // 4`) |
| `estimate_messages_tokens(messages)` | 84-100 | Sum token estimate across message list |
| `_collect_tail_tool_call_ids(tail)` | 103-115 | Collects tool_call_ids referenced in tail messages |
| `_paired_drop_tools(middle, tail)` | 118-172 | Drops unreferenced tool results, annotates orphaned calls |
| `compress_context(messages, max_tokens, ...)` | 175-233 | Synchronous 3-phase compression |
| `_SUMMARY_CACHE_MAX` | 243 | Constant (256) |
| `_summary_cache` | 244 | Module-level `OrderedDict` LRU cache |
| `_hash_messages(messages)` | 247-250 | SHA-256 cache key for summary dedup |
| `summarize_and_compress(messages, max_tokens, provider, model, ...)` | 253-386 | Async 3-phase compression with LLM fallback |

**Total: ~325 lines.**

All functions, constants, and the `_ChatProvider` Protocol move as-is. No signature changes, no behavioral changes.

### What stays in `context.py`

- `_PLATFORM_INFO` constant (line 56)
- `ContextBuilder` class (lines 389-710) — all prompt assembly logic
- Imports needed only by `ContextBuilder`

**`context.py` drops from 709 to ~320 lines.**

### Import changes

**`compression.py`** (new) — imports:
- `collections.OrderedDict`, `hashlib`, `json`, `typing` (stdlib)
- `loguru.logger` (third-party)
- `nanobot.observability.langfuse.span` (for Langfuse span in `summarize_and_compress`)
- `nanobot.context.prompt_loader.prompts` (for the `"compress"` prompt template)
- `nanobot.observability.tracing.bind_trace` (for structured logging)

**`context.py`** (modified) — drops imports for:
- `collections.OrderedDict`
- `hashlib`
- `_ChatProvider` Protocol definition removed

**`turn_orchestrator.py`** — the sole production caller:
- Line 33: `from nanobot.agent.context import estimate_messages_tokens` → `from nanobot.agent.compression import estimate_messages_tokens`
- Line 34: `from nanobot.agent.context import summarize_and_compress` → `from nanobot.agent.compression import summarize_and_compress`

**`loop.py`** — backward-compat re-export:
- Line 95: `from nanobot.agent.context import summarize_and_compress` → `from nanobot.agent.compression import summarize_and_compress`

**Backward compatibility in `context.py`:**
```python
# Backward compat — moved to compression.py
from nanobot.agent.compression import (  # noqa: F401
    compress_context,
    estimate_messages_tokens,
    estimate_tokens,
    summarize_and_compress,
)
```

This preserves all existing test imports:
- `tests/test_context.py` imports `compress_context`, `estimate_messages_tokens`, `summarize_and_compress`, `_summary_cache` from `context`
- `tests/test_pass2_smoke.py` imports `compress_context`, `estimate_messages_tokens` from `context`
- `tests/test_compression_coherence.py` imports `_paired_drop_tools` from `context`
- `tests/test_observability_plumbing.py` imports `summarize_and_compress` from `context`

**Private symbol handling — tests must be updated:**

The following test files import private symbols that move to `compression.py`. Since these are private (`_`-prefixed), we update the test imports directly rather than adding backward-compat re-exports:

- `tests/test_context.py` lines 170, 210: `from nanobot.agent.context import _summary_cache` → `from nanobot.agent.compression import _summary_cache`
- `tests/test_compression_coherence.py` lines 12-13: `from nanobot.agent.context import _collect_tail_tool_call_ids, _paired_drop_tools` → `from nanobot.agent.compression import _collect_tail_tool_call_ids, _paired_drop_tools`
- `tests/test_observability_plumbing.py` line 527: patch target `"nanobot.agent.context.langfuse_span"` → `"nanobot.agent.compression.langfuse_span"` (the `langfuse_span` call inside `summarize_and_compress` moves with it; patching the old module would silently stop working)

### `__init__.py` exports

No changes. Neither `compress_context` nor `summarize_and_compress` is currently in `nanobot/agent/__init__.py`'s `__all__`. `ContextBuilder` remains the only export from the context/compression layer.

## Constraints

- No behavioral change — identical compression behavior
- All existing tests pass (via backward-compat re-exports for public symbols)
- `_ChatProvider` Protocol moves to `compression.py` — it is exclusively a compression concern
- `_PLATFORM_INFO` stays in `context.py` — it is exclusively a prompt assembly concern
- `estimate_tokens` and `estimate_messages_tokens` move to `compression.py` — they are token estimation utilities used only by compression and `turn_orchestrator`

## Success criteria

- `context.py` contains only `ContextBuilder` and its helpers (~320 lines)
- `compression.py` contains all compression logic (~325 lines)
- Zero cross-imports between `compression.py` and `ContextBuilder`
- `make check` passes
- All existing tests pass
- `compression.py` has its own test file (`test_compression.py`) with tests for `compress_context`, `summarize_and_compress`, `_paired_drop_tools`, cache behavior
