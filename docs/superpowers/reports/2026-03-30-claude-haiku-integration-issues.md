# 2026-03-30 Claude Haiku 4.5 Integration — Issue Analysis

> Three issues discovered during Claude Haiku 4.5 integration testing.
> Model: anthropic/claude-haiku-4-5. Query: "Summarize details in Obsidian for project DS10540".

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

### Recommended Fix

1. Improve the strategy extraction prompt to require **concrete, actionable instructions** with specific tool names and argument patterns — not summaries.
2. Include the actual recovery sequence in the extraction context (what failed → what worked) so the LLM can identify the key insight.
3. Consider template-based extraction: `"When looking for {X}, {tool_A} failed because {reason}. Use {tool_B} instead because {reason}."`

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

### Recommended Fix

1. **Better skill decision tree**: The obsidian-cli skill should have a clearer decision guide that says "project codes/identifiers → `obsidian folders` first, not `obsidian search`".
2. **Higher-quality procedural strategies** (Issue 2): If the strategies actually said "use folders for project codes", this would be prevented.
3. **Write guard awareness**: The reasoning protocol could include "Does the user want read-only or write access?" to prevent unsolicited file creation.

---

## Summary

| Issue | Severity | Root Cause | Fix | Status |
|-------|----------|-----------|-----|--------|
| cache_control limit | **Critical** (crashes) | Every system message gets cache_control; Anthropic allows max 4 | Cap to 4 blocks in `_apply_cache_control()` | PR #107 |
| Strategies useless | Medium | Strategy extractor produces vague text, not actionable instructions | Improve extraction prompt or template | Open |
| Wrong document read | Low | Search found a document *about* DS10540 in the wrong vault | Better skill decision tree; strategies would help if specific | Open |

### Cross-Issue Dependencies

- Issue 3 would be mitigated by fixing Issue 2 (specific strategies prevent wrong tool choice)
- Issue 1 must be fixed first — without it, longer conversations always crash regardless of other improvements
- Issue 2 is the key to the learning feedback loop working as designed in the cognitive architecture
