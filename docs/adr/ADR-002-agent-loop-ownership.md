# ADR-002: Agent Loop Ownership and Lifecycle

## Status

Accepted — Phase 2 implemented (2026-03-12)

## Date

2026-03-11

## Context

`AgentLoop` in `nanobot/agent/loop.py` is the central processing engine (~1,800 lines). It
currently owns:

1. Message ingestion (bus consume)
2. Context assembly (system prompt, skills, memory, tool schemas)
3. LLM interaction (chat, streaming, retries)
4. Tool execution (parallel/sequential batching, result shaping)
5. Multi-agent delegation (coordinator routing, sub-loop dispatch, scratchpad)
6. Session management (lookup, scratchpad swap)
7. Metrics recording
8. MCP server connections
9. Memory consolidation
10. Verification pass (self-critique)

This concentration of responsibility makes the file hard to navigate, test in isolation,
and modify safely.

## Decision

1. **AgentLoop remains the single orchestration entry point.** All model interaction flows
   through `AgentLoop`. No other module calls the LLM provider directly for agent tasks.

2. **Extract internal sub-services** from AgentLoop:

   - **`ToolExecutor`** — owns parallel/sequential tool batching, timeout enforcement,
     result shaping. Lives in `nanobot/agent/tool_executor.py`.
   - **`DelegationDispatcher`** — owns coordinator routing, sub-loop execution,
     scratchpad I/O, cycle detection. Lives in `nanobot/agent/delegation.py`.
   - **Prompt loading** — system prompts loaded from `nanobot/templates/prompts/` files
     instead of Python string constants.

3. **Target size.** After extraction, `loop.py` should be ~800–1,000 lines focused on:
   - Ingest → context → mode selection → LLM call → validate → delegate to ToolExecutor
     → update state → decide continue/stop.

   > **Implementation note (Phase 2):** Actual post-extraction size is ~1,830 lines.
   > The gap is explained by features added after the ADR was written (streaming,
   > multi-agent routing metrics, consolidation orchestration, context compression).
   > These are orchestration concerns that belong in the loop.  A future ADR may
   > propose further extraction if the file continues to grow.

   > **Implementation note (Phase 4C):** Three further extractions reduced `loop.py`
   > to ~1,598 lines: `StreamingLLMCaller` → `streaming.py` (~160 lines),
   > `AnswerVerifier` → `verifier.py` (~170 lines),
   > `ConsolidationOrchestrator` → `consolidation.py` (~95 lines).
   > Loop thin-delegates to each; public API unchanged.

4. **AgentLoop controls all orchestration policies:**
   - Token budgets and truncation
   - Retry policy and recursion depth
   - Max iterations and fallback model selection
   - Guardrails and verification

## Consequences

### Positive

- Smaller, focused files are easier to review and test.
- `ToolExecutor` and `DelegationDispatcher` can be tested independently.
- Prompt changes don't require Python code edits.
- Clear ownership: "AgentLoop orchestrates, sub-services execute."

### Negative

- Extraction requires careful interface design to avoid creating pass-through wrappers.
- More files to navigate (3 instead of 1).
- Existing tests need updating after extraction.

### Neutral

- The public API of AgentLoop (`run()`, `run_tool_loop()`) does not change.
- Sub-services (`ToolExecutor`, `DelegationDispatcher`, `PromptLoader`) **are** exported
  from `nanobot/agent/__init__.py` to support direct testing and reuse.
  (Original ADR said "not exported" — revised after Phase 2 implementation.)
