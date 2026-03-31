# 2026-03-30 Cognitive Improvements Session

> Session summary: inspectable reasoning, bug fixes, and model migration.
> Duration: ~6 hours. Model: Claude Opus 4.6 (Claude Code).

## Context

Started from a question about whether the agent has pre-action reasoning (Chain of Thought). Discovered it was prompt-based only, with no visible output. This led to a series of investigations and fixes that improved the agent's cognitive pipeline.

## What Was Done

### 1. Inspectable Reasoning Block (PR #100 — merged)

**Problem:** The reasoning protocol in `reasoning.md` asked the model to "work through these steps before calling any tool" but the reasoning was invisible — no structured output.

**Fix:** Updated `reasoning.md` to require a visible `[REASONING]` block before the first tool call:
```
[REASONING]
1. What does the user need? <answer>
2. What am I looking for? <answer>
3. Which tool or command matches, and why? <answer>
4. What will I try if this returns nothing? <answer>
[/REASONING]
```

Used question-driven format (not labels) to preserve reflective thinking.

**Files:** `nanobot/templates/prompts/reasoning.md`, `nanobot/templates/prompts/identity.md`, `prompts_manifest.json`

### 2. Tool Result Message Ordering (PR #102 — merged)

**Problem:** When 2+ parallel tool calls were made, system messages (skill content, tool removal warnings) were injected *between* tool result messages inside the processing loop. OpenAI's API requires all tool-role messages to be contiguous after the assistant message, causing `BadRequestError: tool_call_ids did not have response messages`.

**Root cause:** 4 `state.messages.append({role: "system", ...})` calls inside the `for tc, result in zip(...)` loop in `_execute_tool_batch()`.

**Fix:** Collect system messages in a `deferred_messages` list during the loop, `extend()` after all tool results are added.

**Files:** `nanobot/agent/turn_runner.py`, `tests/test_turn_runner.py`

### 3. Preserve Assistant Content with Tool Calls (PR #103 — merged)

**Problem:** When Claude emits text alongside tool_use blocks (e.g., the `[REASONING]` block), nanobot discarded the text — `add_assistant_message()` was called with `content=None` hardcoded.

**Root cause investigation:** Three-layer analysis revealed:
- Layer 1 (model): Claude does emit text + tool_use — confirmed by API docs
- Layer 2 (litellm): Correctly preserves text content during format conversion
- Layer 3 (nanobot): `turn_runner.py:368` passed `None` instead of `response.content`

**Fix:** One-line change — pass `response.content` instead of `None`.

**Result:** Claude Haiku 4.5 now emits and preserves `[REASONING]` blocks in session logs:
```json
{"role": "assistant", "content": "[REASONING]\n1. What does the user need?...\n[/REASONING]\n\nI'll search for...", "tool_calls": [...]}
```

**Files:** `nanobot/agent/turn_runner.py`, `tests/test_turn_runner.py`

### 4. Export All Provider API Keys (PR #105 — merged)

**Problem:** When the default model was switched from OpenAI to Anthropic, the embedder broke — `OPENAI_API_KEY` was never exported to the environment because `_setup_env()` only exported the matched provider's key.

**Root cause:** `LiteLLMProvider._setup_env()` uses `find_by_model()` to match the default model, then only sets that provider's `env_key`. The embedder (`OpenAIEmbedder`) needs `OPENAI_API_KEY` regardless of which LLM model is selected.

**Impact:** Memory retrieval completely broken — no procedural strategies loaded, no declarative memory, guardrail learning loop disconnected.

**Fix:** New `_export_all_provider_keys()` helper in `_shared.py` that iterates all configured providers and sets env vars for any with a non-empty API key, called before provider construction.

**Files:** `nanobot/cli/_shared.py`

### 5. Cache Control Block Limit (PR #107 — pending)

**Problem:** Anthropic limits `cache_control` markers to 4 per request. `_apply_cache_control()` added one to every system message + last tool definition. In multi-tool conversations with 5+ system messages, this caused unrecoverable `BadRequestError`.

**Fix:** Budgeted allocation — 1 for tools, 1 for main prompt, remaining slots for most recent system messages. Total never exceeds 4.

**Files:** `nanobot/providers/litellm_provider.py`, `tests/test_litellm_provider.py`

## Model Comparison

Tested the DS10540 Obsidian query across 4 models:

| Metric | GPT-4o-mini | GPT-5.4 Nano | Claude Haiku 4.5 |
|--------|------------|-------------|-------------------|
| LLM calls | 17 | 14 | 7 |
| Duration | 66s | 35s | 25-31s |
| Prompt tokens | 218K | 185K | 121K |
| `[REASONING]` block | No | No | Yes |
| Guardrails fired | 3 | 3 | 1 |
| Correct answer | Yes (eventually) | Yes (wrong project first) | Yes |

**Decision:** Switched default model to `anthropic/claude-haiku-4-5` ($1/$5 per 1M tokens).

## Key Findings

1. **OpenAI models cannot emit text + tool_calls** — trained to return `content: null` when `tool_calls` present. This is RLHF behavior, not an API limitation. GPT-5.4 has a "preambles" feature but only via the Responses API.

2. **Claude natively supports text + tool_use** in the same response. The `[REASONING]` block works as designed with Claude models.

3. **nanobot was discarding Claude's text output** — a one-line bug that silently broke a key feature for any non-OpenAI model.

4. **Provider key isolation** — switching the default model shouldn't break subsystems that depend on a different provider's API.

## Open Issues

1. **Strategy quality** — Extracted strategies are vague/generic ("use tools in a systematic way"). The extraction prompt needs improvement to produce actionable instructions like "DS10540 is a folder name, use `obsidian folders` not `obsidian search`".

2. **obsidian search vs folders** — The agent still tries `obsidian search` first for project codes (folder names). The reasoning protocol identifies it as "likely a FOLDER or FILE NAME" but the model still picks search. Better skill decision trees or higher-quality strategies would fix this.

3. **Rate limiting** — Anthropic's 50K tokens/minute limit on the basic tier causes failures in longer conversations.
