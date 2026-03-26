# ContextBuilder Config Refactoring Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace three scalar memory parameters in `ContextBuilder.__init__` with a typed `MemoryConfig` reference, eliminating manual unpacking in `agent_factory.py`.

**Architecture:** `ContextBuilder` currently receives `memory_retrieval_k`, `memory_token_budget`, and `memory_md_token_cap` as individual `int` parameters, unpacked from `config.memory` in `agent_factory.py` with conditional zeroing when memory is disabled. Instead, pass `MemoryConfig` directly and let `ContextBuilder` read the fields it needs. When memory is disabled, pass `None`.

**Tech Stack:** Python 3.10+, Pydantic, pytest

---

### Task 1: Replace scalar params with MemoryConfig in ContextBuilder

**Files:**
- Modify: `nanobot/context/context.py`
- Modify: `nanobot/agent/agent_factory.py`
- Modify: `tests/test_agent_factory.py`

Steps:

- [ ] Update `ContextBuilder.__init__` — replace 3 scalar params with `memory_config`
- [ ] Update `build_system_prompt` — read from `self._memory_config`
- [ ] Update `agent_factory.py` — pass `memory_config=config.memory if config.memory_enabled else None`
- [ ] Update `tests/test_agent_factory.py` — assert on `memory_config` instead of scalars
- [ ] Run `make lint && make typecheck`
- [ ] Run tests
- [ ] Commit
