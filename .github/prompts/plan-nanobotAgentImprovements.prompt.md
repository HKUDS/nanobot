## Plan: Nanobot Agent — Significant Improvements

All four goals matter, primary use case is personal chat assistant, open to large changes, must stay model-agnostic. Here is a comprehensive plan organized by impact tier.

---

### TL;DR

Nanobot is architecturally clean (bus-based, provider-agnostic, ~4K LoC core) but has five systemic weaknesses holding it back from the next level: **(1)** a flat react loop with zero planning or self-critique, **(2)** a 4,792-line monolithic memory file, **(3)** lossy context compression that discards information instead of summarizing it, **(4)** no integration tests for the core agent path, and **(5)** heuristic-only memory retrieval. The plan addresses all of these plus several high-value additions.

---

**Steps**

### Tier 1 — High Impact, Addresses Core Agent Quality

**1. Add explicit planning and task decomposition to the agent loop**

Currently `nanobot/agent/loop.py` (L243-L325) runs a flat tool-call loop — the LLM picks tools ad hoc with no plan structure. This is the single biggest quality bottleneck.

- Before the main loop, inject a **planning prompt** that asks the model to output a numbered plan of steps given the user's request and available tools. Parse and store the plan as structured data (list of step descriptions).
- After each tool-call round, inject a **progress check** prompt: "You planned N steps. You've completed steps 1–K. Re-evaluate: is the plan still correct, or does it need revision?" This replaces the current `_REFLECT_PROMPT` which only fires on failure.
- On tool failure, instead of simply retrying, inject an **alternative strategy** prompt: "Step K failed with error X. Propose 2 alternative approaches and choose the best one."
- Store the current plan in the message history so the model can self-reference it across iterations.
- Gate this behind a config flag (`planning_enabled`, default `True`) so lightweight usage isn't penalized.

**2. Add a self-critique / verification step before final answer delivery**

Currently the agent delivers the first text response the LLM produces — there's no quality gate. For a personal assistant, wrong answers erode trust fast.

- After the loop produces a candidate answer but before sending it, insert a **critique pass**: a second LLM call with a system prompt like "You are a fact-checker. Given the user's question and the candidate answer, rate confidence 1-5 and list any unsupported claims." This uses the same provider — no vendor lock-in.
- If confidence < 3 or unsupported claims are found, re-enter the loop with the critique injected as context (max 1 retry to avoid latency spiral).
- This subsumes the current `_should_force_verification()` mechanism in `loop.py` (L500-L517) which is limited to memory-grounding checks.
- Make this configurable: `verification_mode: always | on_uncertainty | off`.

**3. Replace lossy context compression with summarization-based compression**

The current `compress_context()` in `nanobot/agent/context.py` (L53-L100) uses a 3-phase drop strategy (truncate tool results → drop tool results → drop middle messages). Dropped information is *permanently lost* for the remainder of the conversation. For a personal assistant handling long multi-topic sessions, this is severely limiting.

- Replace phase 3 (drop middle messages) with **LLM-based summarization**: before dropping, batch the oldest N messages and call the LLM with "Summarize this conversation segment in ≤200 tokens, preserving all facts, decisions, and action items." Insert the summary as a single system message.
- Cache summaries by message range so re-summarization isn't needed on each iteration.
- Keep the current truncation phases as fast first-pass compression; summarization fires only when those aren't sufficient.
- Use a cheaper/faster model for summarization if available (add a `summary_model` config option, falling back to the main model).

**4. Decompose the 4,792-line `nanobot/agent/memory.py` into focused modules**

This file contains 7+ distinct responsibilities and is the #1 maintainability risk. Split into:

| New Module | Responsibility | Approx Lines |
|---|---|---|
| `memory/store.py` | `MemoryStore` class, file I/O, `MEMORY.md`/`HISTORY.md` persistence | ~600 |
| `memory/retrieval.py` | Intent classification, policy selection, scoring, re-ranking, token assembly | ~800 |
| `memory/consolidation.py` | Conversation extraction, dedup, merge, event/profile updates | ~700 |
| `memory/mem0_adapter.py` | `_Mem0Adapter` class, fallback chain, vector health checks | ~500 |
| `memory/profile.py` | Profile CRUD, contradiction detection, conflict resolution | ~400 |
| `memory/evaluation.py` | Eval framework, recall/precision computation, report generation | ~300 |
| `memory/rollout.py` | Feature flags, shadow mode, gate evaluation | ~300 |
| _(removed)_ | Legacy `MetricsCollector` removed — now in Langfuse | — |
| `memory/types.py` | Shared dataclasses, enums, constants | ~150 |

- Maintain the public API surface (`MemoryStore.retrieve()`, `MemoryStore.consolidate()`, `get_memory_context()`) via re-exports from `memory/__init__.py`.
- This is a pure refactor — no behavior changes. Run existing memory tests after each module extraction to verify.

### Tier 2 — High Impact, Memory & Personalization

**5. Cap and manage `MEMORY.md` injection**

Currently `memory.py` (L4098-L4100) injects the full `MEMORY.md` content into every system prompt with no token cap. As the user accumulates long-term memories over months, this will silently crowd out the context window.

- Add a `memory_md_token_cap` config (default 1500 tokens).
- When `MEMORY.md` exceeds the cap, use the retrieval system to select the most query-relevant lines rather than injecting everything. Fall back to recency-based truncation if retrieval is unavailable.
- Periodically (during consolidation), run a **memory compaction** pass: LLM call to merge redundant entries, remove obsolete facts, and compress `MEMORY.md` to fit within the cap.

**7. Upgrade memory retrieval with a learned re-ranker**

Currently all retrieval scoring is hand-tuned heuristics (additive weights of 0.03–0.22). This works but doesn't improve with usage.

- Add an optional **cross-encoder re-ranker** stage after the initial mem0 retrieval. Use `sentence-transformers` `CrossEncoder` with a small model (e.g., `cross-encoder/ms-marco-MiniLM-L-6-v2`, 22M params, runs on CPU).
- Score = `α * cross_encoder_score + (1−α) * current_heuristic_score`, with α configurable (start at 0.5).
- Gate behind the existing rollout system (`rollout.reranker: enabled | shadow | disabled`). Shadow mode logs both rankings for offline comparison.
- Long-term: collect implicit feedback (which retrieved memories the LLM actually used in its response) to fine-tune the cross-encoder or train a lightweight re-ranker on the user's data.

**8. Add user feedback loop for memory and answer quality**

The agent has no mechanism to learn from explicit user feedback.

- After delivering an answer, optionally append a subtle prompt in the system message: "If the user corrects you or expresses dissatisfaction, record the correction and adjust." The correction extraction in `MemoryExtractor` already handles some of this, but it's passive.
- Add a `feedback` tool (or react to emoji reactions on channels that support them — Telegram, Discord, Slack all have reaction APIs) that captures thumbs-up/down + optional text.
- Store feedback events in `events.jsonl` with type `feedback`. Use these to:
  - Downweight memories that led to corrected answers
  - Track per-skill success rates
  - Surface "the user has corrected you N times about X" during retrieval

### Tier 3 — Reliability & Robustness

**9. ~~Replace file-based metrics with in-memory counters~~ (DONE — removed entirely)**

Legacy `MetricsCollector` and `metrics.json` have been removed.  All observability
counters are now captured via Langfuse.

**10. Add integration tests for the core agent loop**

There are zero tests for `AgentLoop._process_message()` or `_run_agent_loop()`. This is the most critical untested path.

- Create `tests/test_agent_loop.py` with a mock LLM provider that returns scripted responses.
- Test cases:
  - Single-turn Q&A (no tool use)
  - Multi-step tool use (tool call → result → final answer)
  - Tool failure → reflect → retry
  - Max iterations hit
  - Context compression triggered
  - Consecutive LLM errors → graceful fallback
  - Nudge for final answer
- Create `tests/test_context.py` for `compress_context()` and system prompt assembly.
- Create `tests/test_shell_safety.py` for deny pattern coverage (current deny patterns in `shell.py` (L24-L37) are untested and bypassable).

**11. Harden the shell tool security**

The current regex deny patterns can be bypassed via variable expansion (`$'\x72\x6d' -rf /`), base64 encoding, or less common destructive commands.

- Add a whitelist mode option: `shell_mode: allowlist | denylist`.
- In allowlist mode, only explicitly permitted command prefixes run (e.g., `git`, `curl`, `python`, `node`, `ls`, `cat`, `grep`).
- Add `--dry-run` support: before executing, show the user what command will run and require confirmation (for non-headless channels).
- Long-term: consider optional lightweight sandboxing via `firejail` or `bubblewrap` (both are model-agnostic, Linux-native).

**12. Add structured error taxonomy**

Currently errors are caught as generic `Exception` with string messages. Create an error taxonomy:

- `ToolExecutionError(tool_name, error_type, recoverable: bool)`
- `ProviderError(provider, status_code, retryable: bool)`
- `MemoryError(operation, cause)`
- `ContextOverflowError(budget, actual)`

This enables the planning system (step 1) to make smarter recovery decisions based on error type rather than parsing error strings.

### Tier 4 — Developer Experience & Extensibility

**13. Replace 35+ constructor parameters with a config object**

`AgentLoop.__init__` in `loop.py` (L47-L93) takes 35+ parameters, duplicated between config and constructor in `commands.py` (L277-L315).

- Create an `AgentConfig` Pydantic model. `AgentLoop.__init__` takes `config: AgentConfig` plus `provider` and `bus`.
- This also enables config validation, serialization, and makes it trivial to add new config fields without modifying 3+ call sites.

**14. Make skills able to register custom tools**

Currently skills are markdown-only — they can't extend the tool registry. This limits the skill system's power.

- Allow skills to include a `tools.py` file that defines `Tool` subclasses.
- `SkillLoader` discovers and registers these tools when the skill is activated.
- This enables community skills that bring their own capabilities (e.g., a "calendar" skill that registers `create_event`, `list_events` tools backed by Google Calendar API).

**15. Add streaming response support**

The agent currently waits for full LLM responses. For long answers in a chat assistant, this creates noticeable latency.

- Use `litellm.acompletion(stream=True)` to yield token-by-token.
- For channels that support editing messages (Telegram, Discord, Slack), progressively update the response message.
- For channels that don't support editing, buffer until complete (current behavior is the fallback).
- Streaming also enables early tool-call detection — start executing the first tool call as soon as it's fully emitted, before the rest of the response completes.

**16. Add dead letter replay for failed outbound messages**

`ChannelManager` (L35-L51) writes failed outbound messages to a JSONL dead letter file, but there's no replay mechanism. Add a `nanobot replay-deadletters` CLI command and an automatic retry on startup.

---

**Verification**

- **Steps 1–3 (agent loop):** Create a benchmark of 20 multi-step tasks (mix of factual Q&A, research, scheduling, memory recall). Measure task completion rate before/after. Target: +15-25% completion rate on multi-step tasks.
- **Step 4 (memory decomposition):** All 38+ existing memory tests must pass after refactor with no behavior changes.
- **Steps 5–8 (memory quality):** Run the existing eval framework in `memory.py` (L2497-L2663) with the `memory_eval_cases.json` test suite. Measure recall@5 and precision@5 before/after. Target: +10% recall with re-ranker.
- **Steps 9–12 (reliability):** `pytest tests/` achieves >80% line coverage on `loop.py`, `context.py`, `shell.py`. Zero race conditions under concurrent consolidation (test with 3 parallel sessions).
- **Steps 13–16 (DX):** Verify skills with custom tools via a sample skill. Measure time-to-first-token for streaming on Telegram channel.

---

**Decisions**

- **Planning approach: structured plan-in-context over external planner** — Keeps the model-agnostic constraint; any model that handles multi-turn tool use can plan. No need for a specialized planning model.
- **Re-ranker: cross-encoder over embedding similarity** — Cross-encoders are significantly more accurate for re-ranking than bi-encoder cosine similarity, at minimal latency cost (22M param model, ~5ms per candidate on CPU).
- **Summarization over RAG for context compression** — For a personal assistant, important context is conversational state (decisions, commitments), not code. A summary preserves this better than retrieval chunks.
- **File-level memory decomposition over microservice split** — Keeps the single-process simplicity that makes nanobot lightweight. Just better code organization.
