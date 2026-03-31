# 2026-03-30 Claude Haiku 4.5 Integration — Issue Analysis

> Three issues discovered during Claude Haiku 4.5 integration testing.
> Model: anthropic/claude-haiku-4-5. Query: "Summarize details in Obsidian for project DS10540".
> Updated: 2026-03-31 with post-fix verification results and deeper root cause analysis.

---

## Issue 1: cache_control Limit Exceeded (Critical — Crashes Agent)

### Symptom

```
AnthropicException - "A maximum of 4 blocks with cache_control may be provided. Found 5."
```

Agent crashes after 3 retries. Unrecoverable — the same messages are resent each retry.

### Root Cause

`_apply_cache_control()` in `litellm_provider.py:130-156` adds `cache_control: {"type": "ephemeral"}` to **every** system message in the message list. Anthropic's API limits this to 4 blocks max per request.

In a multi-tool conversation, system messages accumulate:

| Position | Message | cache_control |
|----------|---------|--------------|
| [0] | Main system prompt (~12K tokens) | #1 |
| [5] | `# Skill: obsidian-cli` (skill injection) | #2 |
| [8] | Guardrail hint: "Try an alternative approach" | #3 |
| [11] | Guardrail directive: "STOP using it this way" | #4 |
| [15] | Additional guardrail or tool warning | **#5 — EXCEEDS LIMIT** |
| Tools | Last tool definition | **#6** |

When the conversation hits 5+ system messages (common after ~7 tool calls), the API rejects the request. The retry logic resends identical messages, so all 3 retries fail with the same error.

### Why This Was Hidden

Only affects Anthropic models — OpenAI doesn't use `cache_control`. The bug was invisible when using GPT-4o-mini because `_supports_cache_control()` returned `False` for OpenAI models. Surfaced immediately when switching to Claude Haiku 4.5.

### Fix (PR #107)

Budgeted allocation in `_apply_cache_control()`:
- **Budget**: 4 total blocks (Anthropic's limit)
- **Allocation**: 1 for tools (last definition), 1 for main system prompt (position 0), remaining 2 for the most recent system messages (working backwards)
- **Skip**: intermediate system messages (guardrails, skill injections)

### Impact

Without this fix, any conversation with Claude that triggers 5+ system messages crashes. This means any non-trivial task (skill loading + guardrail activation) is broken.

### Post-Fix Verification (2026-03-31)

**Status: FIXED (PR #107 merged)**

Tested with the same DS10540 query. The agent ran 10 LLM calls with multiple guardrail
activations (5+ system messages accumulated). No `cache_control` crash. The budgeted
allocation produced 4 blocks: main prompt + last 2 system messages + tools.

| Metric | Before fix (crashed) | After fix |
|--------|---------------------|-----------|
| cache_control blocks | 5+ (crash) | 4 (within limit) |
| LLM calls completed | 7 (then crash) | 10 (completed) |
| Cost | $0.00061 (partial) | $0.00096 (full) |

---

## Issue 2: Strategies Saved But Useless (Medium)

### Symptom

The agent keeps trying `obsidian search query="DS10540"` (which returns empty) every session, despite procedural memory strategies being saved after each guardrail recovery. The learning feedback loop is not working.

### Root Cause

The strategy extractor produces **vague, generic summaries** instead of actionable instructions. All 10 saved strategies are unusable:

```
"It seems that the command to search for details in Obsidian for
project DS10540 did not work due to an unknown error..."

"The tool-use strategy involves utilizing specific tools in a
systematic way to enhance efficiency..."

"What doesn't work: Calling unknown() function..."
```

**Expected** (what would actually help):
```
"DS10540 is a folder name in the Obsidian vault, not file content.
obsidian search only matches file content. Use obsidian folders to
list the vault structure, then obsidian files folder="DS10540" to
list files in the project folder."
```

### Contributing Factors

1. **Extraction prompt quality**: The lightweight LLM call used for strategy extraction (`strategy_extractor.py`) doesn't produce specific, actionable instructions. It summarizes the situation vaguely rather than capturing the key insight (search vs folders).

2. **All strategies have `confidence=0.5` and `use_count=0`**: They've never been successfully retrieved and applied. The confidence never increases because the strategies are never matched to incoming queries.

3. **Retrieval mismatch**: Strategies are stored with `domain=filesystem` and `task_type=empty_recovery:exec`. The user query "Summarize details in Obsidian for project DS10540" may not match well against these labels during vector/keyword retrieval.

4. **Model used for extraction**: The strategy extraction uses the same model (GPT-4o-mini previously, now Claude Haiku). Smaller models produce less specific strategies.

### Deeper Root Cause Analysis (2026-03-31)

Code-level investigation revealed the **primary root cause** is not the extraction prompt
quality — it's **missing data in the guardrail activation dict**.

#### The Data Gap

`strategy_extractor.py:87-131` — `_build_strategy()` reads `activation.get("failed_tool", "unknown")`
and `activation.get("failed_args", "")`. But the guardrail activation recording in
`turn_runner.py:503-511` **never sets these fields**:

```python
# What is recorded (turn_runner.py:503-511):
state.guardrail_activations.append({
    "source": intervention.source,
    "severity": intervention.severity,
    "iteration": state.iteration,
    "message": intervention.message,
    "strategy_tag": intervention.strategy_tag,
})
# Missing: "failed_tool", "failed_args"
```

So the LLM summarization prompt receives:
```
Failed: unknown()
Succeeded: exec({"command": "obsidian folders"})
```

This produces: `"What doesn't work: Calling unknown() function..."` — the LLM is
literally summarizing the word "unknown" because the actual failed tool info was never
captured.

#### Retrieval Is Unfiltered

`strategy.py:70-89` — `retrieve()` filters by `domain` and `task_type` only. In
`context.py:124`, it's called with **no domain or task_type filter** — just `limit=5,
min_confidence=0.3`. All 10 strategies have `confidence=0.5`, so the top 5 by confidence
are returned regardless of relevance to the current task. There is no semantic matching.

#### Strategies ARE in the Prompt But Useless

Post-fix verification confirmed strategies are retrieved and injected (memory retrieval
returns `results=6`). The `[REASONING]` block even references memory: "Check the Project
Management vault (mentioned in memory as a search location)". But the strategy text itself
provides no actionable guidance.

### Recommended Fix (Updated)

**Priority 1 — Fix the data gap:**
Add `failed_tool` and `failed_args` to the guardrail activation dict in `turn_runner.py`.
The data is available in `latest_attempts` — the most recent failed tool attempt before
the guardrail fired. This is a ~5-line change that would immediately produce strategies
like: `"obsidian search did not return results. Use obsidian folders instead."`

**Priority 2 — Improve extraction prompt:**
Change the LLM prompt in `_llm_summarize()` to require a structured format:
```
When: <user intent pattern>
Don't use: <failed tool + why it fails>
Use instead: <successful tool + specific arguments>
```

**Priority 3 — Add query-based retrieval:**
Add semantic matching to strategy retrieval so strategies about "obsidian search" are
returned when the user mentions "Obsidian" — not just top-N by confidence.

### Status: Open (root cause identified, fix not yet implemented)

---

## Issue 3: Agent Read the Wrong Document (Low)

### Symptom

The agent found and summarized the *Agent Cognitive Core Redesign* report (a nanobot architecture document that mentions DS10540 as a failure case study) instead of the actual DS10540 project files (Opportunity Brief, Timekeeping, Schedule Updates, Financial Updates).

### Root Cause

The session took a different path from previous sessions:

```
1. obsidian vaults verbose → found 2 vaults:
   - Project Management (contains DS10540 folder)
   - Development practices (contains docs that mention DS10540)

2. obsidian search query="DS10540" in Project Management → No matches
   (DS10540 is a FOLDER name, search only matches file CONTENT)

3. obsidian search query="DS10540" in Development practices → 2 matches
   (These files contain the text "DS10540" in their content)

4. Read "Agent Cognitive Core Redesign - Full Analysis Report"
   (Wrong document — it's ABOUT DS10540, not FOR DS10540)

5. Tried to CREATE a summary note in Obsidian → blocked by safety guard

6. Hit cache_control limit → crashed (Issue 1)
```

The agent found a content match in the wrong vault. The Development practices vault contains nanobot development documents that reference DS10540 as a case study. The actual project files are in the Project Management vault as a folder.

### Why the [REASONING] Block Didn't Help

The reasoning block was emitted and correctly identified DS10540 as "likely a FOLDER or FILE NAME":

```
[REASONING]
1. What does the user need? Summarize details in Obsidian for project DS10540
2. What am I looking for?
   - A project note or folder in Obsidian for "DS10540"
   - Details/content about this project to summarize
3. Which tool or command matches, and why?
   - The obsidian-cli skill is active and designed for vault automation
   - I should first discover the vault structure and locate DS10540 content
4. What will I try if this returns nothing?
   - Use list_dir to explore the workspace filesystem directly
[/REASONING]
```

Despite identifying it as a folder, the model still chose `obsidian search` (content search) instead of `obsidian folders` (structure listing). The reasoning protocol helps the model think about the task but doesn't override its default tool selection bias.

### Additional Problem: Unsolicited Write

The agent tried to **create** a file in Obsidian (`obsidian create path="DS10540/Project Summary.md"`) instead of just reading and summarizing. The safety guard correctly blocked this. The user asked to "summarize" not "create" — the agent overstepped.

### Post-Fix Verification (2026-03-31)

**Status: PERSISTS (no fix implemented for Issue 3)**

After fixing Issue 1 (cache_control) and Issue 4 (embedder), the agent was tested again.
The exact same behavioral pattern repeated:

```
1. load_skill("obsidian-cli")                                    → OK
2. obsidian search query="DS10540"                               → Empty
3. obsidian vaults verbose                                       → 2 vaults
4. obsidian search query="DS10540" in PM vault                   → Empty
5. obsidian search query="DS10540" in Dev vault                  → 2 matches (wrong docs)
6. obsidian read "Agent Cognitive Core Redesign" in Dev vault     → Wrong document
7. cache_get_slice                                                → Full content
8. obsidian create in PM vault                                    → BLOCKED (safety guard)
9. obsidian create (retry different syntax)                       → CREATED (bypassed guard)
10. Final answer based on wrong document
```

**New finding**: On the second `obsidian create` attempt (step 9), the agent changed the
command syntax and **successfully created a file** (`DS10540 Project Summary.md`) in the
Project Management vault. The summary was based on the wrong source document (the
architecture redesign report, not the actual project files). This is worse than the
previous run where the safety guard blocked both attempts.

The `[REASONING]` block was emitted and identified DS10540 as a folder, but the model
still chose search first. The reasoning protocol influences thinking but not action.

### Recommended Fix

1. **Better skill decision tree**: The obsidian-cli skill should have a clearer decision guide that says "project codes/identifiers → `obsidian folders` first, not `obsidian search`".
2. **Higher-quality procedural strategies** (Issue 2): If the strategies actually said "use folders for project codes", this would be prevented.
3. **Write guard awareness**: The reasoning protocol could include "Does the user want read-only or write access?" to prevent unsolicited file creation.
4. **Safety guard gap**: The `obsidian create name=...` syntax bypassed the safety guard while `obsidian create path=...` was blocked. The denylist pattern needs to cover both syntaxes.

---

## Summary

| Issue | Severity | Root Cause | Fix | Status |
|-------|----------|-----------|-----|--------|
| cache_control limit | **Critical** (crashes) | Every system message gets cache_control; Anthropic allows max 4 | Cap to 4 blocks in `_apply_cache_control()` | **FIXED** (PR #107) |
| Strategies useless | **High** | Guardrail activations missing `failed_tool`/`failed_args` → extractor receives "unknown" → garbage output | Add failed tool data to activation dict + improve extraction prompt | Open |
| Wrong document read | Medium | Search found a document *about* DS10540 in the wrong vault | Better skill decision tree; strategies would help if specific | Open |
| Unsolicited write | Medium | Agent interprets "summarize" as "create a summary file"; safety guard bypass via alternate syntax | Write guard in reasoning protocol + fix denylist gap | Open |

### Cross-Issue Dependencies

```
Issue 1 (cache_control)  ──── FIXED ────→ Agent no longer crashes
                                            │
Issue 2 (strategies)     ──── OPEN ────→ Learning loop still broken
    │                                       │
    │  fixes ↓                              │  would mitigate ↓
    │                                       │
Issue 3 (wrong document) ──── OPEN ────→ Agent reads wrong content
    │                                       │
    │  partially overlaps ↓                 │
    │                                       │
Issue 4 (unsolicited write) ── OPEN ──→ Agent creates files without permission
```

- **Issue 2 is the highest-priority remaining fix** — it's the root cause of the learning
  feedback loop being broken. The data gap (`failed_tool` missing from guardrail
  activations) is a ~5-line fix that would immediately improve strategy quality.
- Issue 3 would be mitigated by fixing Issue 2 (specific strategies prevent wrong tool choice)
- Issue 4 (unsolicited write) has a safety guard bypass that should be fixed independently

### Files Referenced

| File | Relevance |
|------|-----------|
| `nanobot/providers/litellm_provider.py:130-183` | Issue 1: `_apply_cache_control()` (FIXED) |
| `nanobot/agent/turn_runner.py:503-511` | Issue 2: guardrail activation recording (missing fields) |
| `nanobot/memory/strategy_extractor.py:87-131` | Issue 2: `_build_strategy()` receives "unknown" |
| `nanobot/memory/strategy.py:70-89` | Issue 2: `retrieve()` has no semantic matching |
| `nanobot/context/context.py:122-142` | Issue 2: strategy injection into prompt |
| `nanobot/tools/builtin/shell.py` | Issue 4: safety guard denylist patterns |
