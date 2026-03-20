# Phase 3: Testing & Documentation Review

## Test Coverage Findings

### Critical Severity

**[TEST-C1] No regression test for SEC-M3 false positive: file-not-found → PERMANENT_CONFIG**
- The `classify_failure` static method maps `"not found"` and `"no such"` to `PERMANENT_CONFIG`, which would permanently disable `read_file` for the turn when a file simply doesn't exist. This is the highest-priority security/correctness gap identified in Phase 2 (SEC-M3), and there is no test exercising this false-positive path.
- Recommended test: `test_classify_failure_file_not_found_is_logical_not_permanent` — assert that `ToolResult.fail("File not found: /tmp/foo.txt", error_type="not_found")` classifies as `LOGICAL_ERROR`, not `PERMANENT_CONFIG`.

**[TEST-C2] No test verifying tool is available in turn N+1 after turn-scoped suppression (CQ-H3 fix)**
- The CQ-H3 fix introduced `disabled_tools: set[str]` scoped to `_run_agent_loop`. There is no test that starts a second invocation of `_run_agent_loop` and verifies the previously suppressed tool is available again. Without this, regression to permanent removal goes undetected.
- Recommended test: use `ScriptedProvider` to simulate two sequential turns where `web_search` fails in turn 1 and succeeds in turn 2; assert both calls are made.

### High Severity

**[TEST-H1] `TRANSIENT_ERROR` FailureClass path not covered**
- `test_tool_call_tracker.py` tests `PERMANENT_CONFIG`, `PERMANENT_AUTH`, `TRANSIENT_TIMEOUT`, and `LOGICAL_ERROR` but has no test for `TRANSIENT_ERROR` (generic non-timeout transient failure). This leaves a gap in the classification coverage.

**[TEST-H2] Permanent-failure immediate removal not tested at loop level**
- Unit tests in `test_tool_call_tracker.py` verify that `permanent_failures` is populated correctly, but no integration test verifies that a tool with a permanent failure is excluded from `tools_def` in the same turn (the `disabled_tools` filtering at line 887–892 of `loop.py`).

**[TEST-H3] Delegation depth limit (SEC-H2) not covered**
- No test exercises a delegation chain with 4+ distinct roles. The current golden scenarios mock delegation at one level. A chain A→B→C→D (4 distinct roles) with no explicit depth guard is untested — the finding notes each level runs up to 12 LLM iterations.

**[TEST-H4] `_build_failure_prompt` content not specifically asserted**
- `test_coverage_push_wave6.py` asserts the string `"alternative"` appears in the injected prompt, but does not test: (a) that `PERMANENT_CONFIG` failures include the "tool permanently disabled" language, (b) that `TRANSIENT_TIMEOUT` failures include retry/patience guidance, (c) that an empty failure set results in no failure block being injected.

### Medium Severity

**[TEST-M1] Compression skipped under budget — not tested at loop level**
- `summarize_and_compress` is called unconditionally (PERF-C1 finding). There is no test asserting it is *not* called (or called with a no-op result) when messages are well under the context budget.

**[TEST-M2] `classify_failure` keyword boundary cases not parametrized**
- The existing tests cover one example per class. Edge cases like `"forbidden"` (ambiguous between auth and access-control), `"rate limit"` vs `"timeout"`, and `"invalid api key"` with mixed casing are not parametrized.

**[TEST-M3] Role switching (`_apply_role_for_turn` / `_reset_role_after_turn`) not unit tested**
- These methods have identified concurrency risks (AR-H2 / SEC-H1). There are no unit tests verifying that after `_reset_role_after_turn`, `self.model`, `self.temperature`, and the tool set match their pre-turn values.

**[TEST-M4] `MemoryStore` `to_thread` wrapping not tested**
- PERF-M5 identified two sequential `asyncio.to_thread` calls for in-memory operations. Whether these are necessary is not covered by a test that exercises the memory path without file I/O.

### Low Severity

**[TEST-L1]** `_needs_planning` heuristic (22 substring signals) has no parametrized test. A signal like `"and"` could produce false positives.

**[TEST-L2]** `safe_filename` (used for session key from untrusted channel metadata) is not tested against null bytes, very long strings, or Unicode normalization.

**[TEST-L3]** `ToolCallTracker._key()` SHA-256 computation is not tested for stability across Python versions (dict key ordering in `json.dumps`).

---

## Documentation Findings

### High Severity

**[DOC-H1] `docs/prompt-inventory.md` line 18 is factually incorrect post-Layer-4**
- States: `failure_strategy.md` → `AgentLoop._run_agent_loop()` (injected every turn).
- Actual behavior since the Layer 4 implementation: `failure_strategy.md` is no longer injected directly. `_build_failure_prompt()` generates a dynamic prompt from live tracker state; `failure_strategy.md` now serves as documentation of the approach, not as a runtime template.
- Fix: Update line 18 to reflect that `failure_strategy.md` is a design reference, not a runtime injection. Add an entry for `_build_failure_prompt()` as the runtime path.

**[DOC-H2] CHANGELOG has no entry for Layer 4 implementation**
- No CHANGELOG entry exists for: `FailureClass` enum, `classify_failure()`, `_build_failure_prompt()`, `disabled_tools` turn-scoping (CQ-H3 fix), or the `ToolCallTracker` API change (return type changed from `int` to `tuple[int, FailureClass]`).
- The `ToolCallTracker.record_failure()` return type change is a breaking API change for any code calling it.

**[DOC-H3] `loop.py` module docstring does not mention FailureClass or turn-scoped suppression**
- The module-level docstring describes the Plan-Act-Observe-Reflect loop but makes no mention of failure classification, `FailureClass`, or the `disabled_tools` mechanism. These are core to understanding the module's behavior.

### Medium Severity

**[DOC-M1] `ToolCallTracker` class docstring not updated**
- Still describes the tracker as counting failures and tracking permanent failures via `unregister()`. The new behavior (classify on first occurrence, populate `_permanent_failures`, return `FailureClass` from `record_failure`) is undocumented.

**[DOC-M2] `AgentLoop` class docstring is generic**
- Does not mention key collaborators (`ToolCallTracker`, `CapabilityRegistry`, `DelegationDispatcher`) or the `disabled_tools` per-turn suppression pattern. A developer reading the class docstring gets no orientation to the system.

**[DOC-M3] ADR-009 incorrectly annotates `unregister()` usage**
- After the CQ-H3 fix, `unregister()` is no longer called by `ToolCallTracker`'s interaction with `_run_agent_loop`. ADR-009's note that `unregister()` is "for ToolCallTracker" is now misleading.

### Low Severity

**[DOC-L1]** `_build_failure_prompt()` has no docstring explaining the `disabled_tools` parameter or the format of the returned string.

**[DOC-L2]** `classify_failure()` docstring does not enumerate which `error_type` values map to which `FailureClass` — developers extending the system must read the implementation to understand the mapping.

**[DOC-L3]** `FailureClass.is_permanent` property has no docstring.

**[DOC-L4]** `docs/agent-intelligence-layers.md` was updated to reflect completion but does not cross-reference the security audit findings (SEC-M3 false-positive risk) as a known limitation of the current `classify_failure` implementation.

---

## Critical Issues for Phase 4 Context

1. **[TEST-C1 + SEC-M3] False-positive permanent disabling** — the most impactful gap. A missing file permanently disables `read_file` for the turn. Both a test gap and a correctness risk.
2. **[DOC-H1] prompt-inventory.md inaccuracy** — actively misleads developers about how failure prompts are injected. Should be fixed with the next commit.
3. **[DOC-H2] CHANGELOG gap** — the `record_failure` return-type change is a breaking API change with no documented migration path.
4. **[TEST-C2] Turn-scoped suppression regression guard** — without a test, the CQ-H3 fix can silently regress to permanent removal.
